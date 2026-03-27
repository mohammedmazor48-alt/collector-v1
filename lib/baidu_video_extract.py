"""
lib/baidu_video_extract.py — 百度视频提取核心库

三层提取策略：
  Layer 1: HTML 静态提取（httpx fetch + regex/JSON 解析）
  Layer 2: 页面对象提取（Playwright JS 执行 window 全局对象）
  Layer 3: 网络抓包（Playwright response 监听 mp4/m3u8）

公开接口：
  is_baidu_video_url(url) -> bool
  canonicalize_baidu_video_url(url) -> str
  extract_from_html(html) -> dict | None
  extract_from_page_objects(page) -> dict | None
  extract_from_network(page) -> list[dict]
  pick_best_candidate(candidates) -> dict | None
  save_debug_artifacts(...) -> str
  run_extraction(url, **kwargs) -> dict
"""

import json
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# URL 参数白名单
_KEEP_PARAMS = {"nid", "sourceFrom"}

# HTML 中视频地址的 regex 模式（由宽到窄）
_VIDEO_PATTERNS = [
    re.compile(r'"playurl"\s*:\s*"(?P<url>https:\\/\\/[^"]+?(?:\.mp4|\.m3u8)[^"]*)"', re.I),
    re.compile(r'"videoUrl"\s*:\s*"(?P<url>https?:\\/\\/[^"]+?(?:\.mp4|\.m3u8)[^"]*)"', re.I),
    re.compile(r'"url"\s*:\s*"(?P<url>https:\\/\\/[^"]+?(?:\.mp4|\.m3u8)[^"]*)"', re.I),
    re.compile(r'https?://[^\s"\'<>\u201c\u201d]+?(?:\.mp4|\.m3u8)(?:\?[^\s"\'<>\u201c\u201d]*)?', re.I),
]

_TITLE_PATTERNS = [
    re.compile(r'"title"\s*:\s*"(?P<title>[^"]{1,200})"'),
    re.compile(r'<title>(?P<title>[^<]{1,200})</title>', re.I),
]

# 在 window 对象中查找视频地址的键名
_VIDEO_KEYS = [
    "videoUrl", "playUrl", "mp4Url", "m3u8Url",
    "video_url", "play_url", "playurl", "videourl",
]

# 要检查的 window 全局变量
_WINDOW_GLOBALS = [
    "__INITIAL_STATE__", "pageData", "__NUXT__", "videoData", "__NEXT_DATA__",
]


# ── 工具函数 ──────────────────────────────────────────────────────────────

def _decode_url(raw: str) -> str:
    try:
        return bytes(raw, "utf-8").decode("unicode_escape").replace("\\/", "/").replace("\\u002F", "/").replace("&amp;", "&")
    except Exception:
        return raw.replace("\\/", "/").replace("\\u002F", "/").replace("&amp;", "&")


def _fmt(url: str) -> str:
    return "m3u8" if ".m3u8" in url.lower() else "mp4"


def _extract_title(html: str) -> str:
    for pat in _TITLE_PATTERNS:
        m = pat.search(html)
        if m:
            return _decode_url(m.group("title")).strip()
    return ""


def _search_video_in_obj(obj, depth: int = 0) -> str | None:
    """递归在 dict/list 中查找视频 URL 字符串。"""
    if depth > 10 or not obj:
        return None
    if isinstance(obj, str):
        lower = obj.lower()
        if obj.startswith("http") and (".mp4" in lower or ".m3u8" in lower):
            return obj
        return None
    if isinstance(obj, dict):
        for k in _VIDEO_KEYS:
            v = obj.get(k)
            if isinstance(v, str) and v.startswith("http"):
                lower = v.lower()
                if ".mp4" in lower or ".m3u8" in lower:
                    return v
        for v in obj.values():
            r = _search_video_in_obj(v, depth + 1)
            if r:
                return r
    if isinstance(obj, list):
        for item in obj:
            r = _search_video_in_obj(item, depth + 1)
            if r:
                return r
    return None


# ── 公开函数 ──────────────────────────────────────────────────────────────

def is_baidu_video_url(url: str) -> bool:
    """判断是否为百度视频 URL。"""
    host = (urlparse(url).hostname or "").lower()
    return "baidu.com" in host


def canonicalize_baidu_video_url(url: str) -> str:
    """
    规范化百度视频 URL：
    - 保留 nid（必须）、sourceFrom（可选）
    - 去掉 ruk / mcpParams / sid_for_share / source 等噪声参数
    - 统一使用 videolanding 路径
    """
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=False)
    nid = (params.get("nid") or [""])[0]
    source_from = (params.get("sourceFrom") or [""])[0]

    if nid:
        base = "https://mbd.baidu.com/newspage/data/videolanding"
        query = f"nid={nid}"
        if source_from:
            query += f"&sourceFrom={source_from}"
        return f"{base}?{query}"

    # nid 缺失时退化：仅保留白名单参数
    filtered = {k: v[0] for k, v in params.items() if k in _KEEP_PARAMS}
    return urlunparse(parsed._replace(query=urlencode(filtered)))


def extract_from_html(html: str) -> dict | None:
    """
    Layer 1：从 HTML 文本提取视频地址。
    优先解析内嵌 JSON 结构，失败则用正则匹配。
    返回 {"video_url", "format", "source"} 或 None。
    """
    # 尝试解析内嵌 JSON blob
    json_patterns = [
        re.compile(r'window\.__(?:INITIAL_STATE__|pageData|NUXT__)\s*=\s*(\{.+?\})\s*[;\n]', re.S),
        re.compile(r'"videoInfo"\s*:\s*(\{.+?\})', re.S),
    ]
    for pat in json_patterns:
        for m in pat.finditer(html):
            try:
                obj = json.loads(m.group(1))
                url = _search_video_in_obj(obj)
                if url:
                    url = _decode_url(url)
                    return {"video_url": url, "format": _fmt(url), "source": "html-json"}
            except Exception:
                continue

    # Regex fallback
    for pat in _VIDEO_PATTERNS:
        m = pat.search(html)
        if m:
            raw = m.groupdict().get("url") or m.group(0)
            url = _decode_url(raw)
            return {"video_url": url, "format": _fmt(url), "source": "html-regex"}

    return None


def extract_from_page_objects(page) -> dict | None:
    """
    Layer 2：在 Playwright 页面执行 JS，从 window 全局对象提取视频地址。
    返回 {"video_url", "format", "source"} 或 None。
    """
    js = """
    () => {
        const VIDEO_KEYS = ['videoUrl', 'playUrl', 'mp4Url', 'm3u8Url',
                            'video_url', 'play_url', 'playurl', 'videourl'];
        const GLOBALS  = ['__INITIAL_STATE__', 'pageData', '__NUXT__',
                          'videoData', '__NEXT_DATA__'];

        function search(obj, depth) {
            if (!obj || depth > 10) return null;
            if (typeof obj === 'string') {
                const lo = obj.toLowerCase();
                if (obj.startsWith('http') && (lo.includes('.mp4') || lo.includes('.m3u8')))
                    return obj;
                return null;
            }
            if (typeof obj === 'object') {
                for (const k of VIDEO_KEYS) {
                    const v = obj[k];
                    if (typeof v === 'string' && v.startsWith('http')) {
                        const lo = v.toLowerCase();
                        if (lo.includes('.mp4') || lo.includes('.m3u8')) return v;
                    }
                }
                try {
                    for (const v of Object.values(obj)) {
                        const r = search(v, depth + 1);
                        if (r) return r;
                    }
                } catch(e) {}
            }
            return null;
        }

        for (const g of GLOBALS) {
            if (window[g]) {
                const r = search(window[g], 0);
                if (r) return r;
            }
        }
        return null;
    }
    """
    try:
        url = page.evaluate(js)
        if url and isinstance(url, str) and url.startswith("http"):
            return {"video_url": url, "format": _fmt(url), "source": "page-objects"}
    except Exception:
        pass
    return None


def extract_from_network(page) -> list[dict]:
    """
    Layer 3：注册 response 监听器，收集视频候选资源。
    必须在 page.goto() 前调用，返回的列表会在页面加载时被持续填充。
    """
    candidates: list[dict] = []

    def on_response(resp):
        url = resp.url
        lower = url.lower()
        ct = (resp.headers.get("content-type") or "").lower()
        is_video_ext = ".mp4" in lower or ".m3u8" in lower
        is_video_ct = "video/mp4" in ct or "application/vnd.apple.mpegurl" in ct or (
            "video/" in ct and "text" not in ct
        )
        if is_video_ext or is_video_ct:
            try:
                candidates.append({
                    "url": url,
                    "content_type": ct,
                    "status": resp.status,
                    "referer": resp.request.headers.get("referer", ""),
                    "timestamp": time.time(),
                })
            except Exception:
                pass

    page.on("response", on_response)
    return candidates


def pick_best_candidate(candidates: list[dict]) -> dict | None:
    """
    从候选资源列表中选出最优视频地址。
    优先级：mp4 > m3u8，status 200，非分片/分段，非明显临时资源。
    """
    if not candidates:
        return None

    def score(c: dict) -> tuple:
        url = c.get("url", "").lower()
        ct = c.get("content_type", "").lower()
        status = c.get("status", 0)
        is_mp4 = ".mp4" in url or "video/mp4" in ct
        is_m3u8 = ".m3u8" in url or "mpegurl" in ct
        is_ok = status == 200
        is_chunk = bool(re.search(r"[_\-](?:seg|chunk|part|ts)\d+", url))
        return (is_mp4, is_m3u8, is_ok, not is_chunk)

    best = sorted(candidates, key=score, reverse=True)[0]
    url = best["url"]
    return {
        "video_url": url,
        "format": _fmt(url),
        "source": "playwright-network",
        "candidates": candidates,
    }


def save_debug_artifacts(
    debug_base: str | Path,
    url: str,
    canonical_url: str,
    html: str = "",
    screenshot_bytes: bytes | None = None,
    console_logs: list[str] | None = None,
    network_requests: list[dict] | None = None,
    result: dict | None = None,
) -> str:
    """
    保存调试工件到 debug/baidu/<timestamp>/ 目录。
    至少保存：page.html / screenshot.png / console.log / requests.json / result.json。
    返回目录路径字符串。
    """
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dir_path = Path(debug_base) / "baidu" / ts
    dir_path.mkdir(parents=True, exist_ok=True)

    if html:
        (dir_path / "page.html").write_text(html, encoding="utf-8", errors="replace")

    if screenshot_bytes:
        (dir_path / "screenshot.png").write_bytes(screenshot_bytes)

    if console_logs:
        (dir_path / "console.log").write_text(
            "\n".join(console_logs), encoding="utf-8", errors="replace"
        )

    if network_requests:
        (dir_path / "requests.json").write_text(
            json.dumps(network_requests, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    result_data = dict(result or {})
    result_data.setdefault("page_url", url)
    result_data.setdefault("canonical_url", canonical_url)
    (dir_path / "result.json").write_text(
        json.dumps(result_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return str(dir_path)


# ── 编排器 ────────────────────────────────────────────────────────────────

def run_extraction(
    url: str,
    headless: bool = True,
    total_timeout: int = 15,
    page_load_timeout: int = 5,
    network_wait: int = 6,
    save_debug_on_fail: bool = True,
    debug_base: str | Path = "debug",
) -> dict:
    """
    完整三层提取流程，返回结构化结果 dict。

    成功：{"ok": True, "title", "page_url", "canonical_url",
           "video_url", "format", "source", "debug_dir"}
    失败：{"ok": False, "reason", "page_url", "canonical_url",
           "step", "debug_dir"}
    """
    canonical = canonicalize_baidu_video_url(url)
    t0 = time.time()

    def elapsed() -> float:
        return time.time() - t0

    # ── Layer 1: HTTP + HTML（不启动浏览器）────────────────────────────────
    html_cache = ""
    try:
        with httpx.Client(timeout=5, follow_redirects=True, headers=DEFAULT_HEADERS) as client:
            resp = client.get(canonical)
            html_cache = resp.text
        r = extract_from_html(html_cache)
        if r:
            return _ok(url, canonical, r, _extract_title(html_cache))
    except Exception:
        pass

    if elapsed() >= total_timeout:
        return _fail(url, canonical, "timeout_after_layer1", "layer1", None)

    # ── Layer 2 & 3: Playwright ────────────────────────────────────────────
    page_html = html_cache
    title = ""
    screenshot_bytes: bytes | None = None
    console_logs: list[str] = []
    candidates: list[dict] = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            page = browser.new_page()

            # 注册 Layer 3 监听器（必须在 goto 前）
            candidates = extract_from_network(page)

            # 捕获 console 日志
            page.on("console", lambda msg: console_logs.append(f"[{msg.type}] {msg.text}"))

            # 导航
            remaining_ms = max(1000, int((total_timeout - elapsed()) * 1000))
            try:
                page.goto(
                    canonical,
                    wait_until="domcontentloaded",
                    timeout=min(page_load_timeout * 1000, remaining_ms),
                )
            except PlaywrightTimeoutError:
                pass

            try:
                page.wait_for_load_state("networkidle", timeout=3000)
            except PlaywrightTimeoutError:
                pass

            page_html = page.content()
            title = page.title()

            # Layer 1 重试（用浏览器渲染后的 HTML）
            r = extract_from_html(page_html)
            if r:
                browser.close()
                return _ok(url, canonical, r, title)

            # Layer 2: 页面对象
            r = extract_from_page_objects(page)
            if r:
                browser.close()
                return _ok(url, canonical, r, title)

            # Layer 3: 等待网络候选
            net_deadline = time.time() + max(0, total_timeout - elapsed() - 1)
            while time.time() < net_deadline and not candidates:
                time.sleep(0.3)

            if candidates:
                best = pick_best_candidate(candidates)
                if best:
                    browser.close()
                    result = _ok(url, canonical, best, title)
                    result["candidate_count"] = len(candidates)
                    return result

            # 全部失败，截图留证
            try:
                screenshot_bytes = page.screenshot(timeout=3000)
            except Exception:
                pass

            browser.close()

    except Exception:
        pass

    # ── 全部失败 ───────────────────────────────────────────────────────────
    debug_dir = None
    if save_debug_on_fail:
        fail_result = {
            "ok": False,
            "reason": "no_video_url_found",
            "page_url": url,
            "canonical_url": canonical,
            "step": "network_capture",
            "candidate_count": len(candidates),
        }
        debug_dir = save_debug_artifacts(
            debug_base=debug_base,
            url=url,
            canonical_url=canonical,
            html=page_html,
            screenshot_bytes=screenshot_bytes,
            console_logs=console_logs,
            network_requests=candidates,
            result=fail_result,
        )

    return _fail(url, canonical, "no_video_url_found", "network_capture", debug_dir)


def _ok(url: str, canonical: str, r: dict, title: str) -> dict:
    return {
        "ok": True,
        "title": title,
        "page_url": url,
        "canonical_url": canonical,
        "video_url": r["video_url"],
        "format": r["format"],
        "source": r["source"],
        "debug_dir": None,
    }


def _fail(url: str, canonical: str, reason: str, step: str, debug_dir: str | None) -> dict:
    return {
        "ok": False,
        "reason": reason,
        "page_url": url,
        "canonical_url": canonical,
        "step": step,
        "debug_dir": debug_dir,
    }
