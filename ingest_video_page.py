import argparse
import io
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

# Windows GBK 终端下强制 UTF-8 输出，避免打印中文时崩溃
if sys.stdout.encoding and sys.stdout.encoding.lower() in ("gbk", "gb2312", "cp936"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import httpx
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from processors.utils import load_config
from lib.baidu_video_extract import is_baidu_video_url, run_extraction as _baidu_extract

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

VIDEO_URL_PATTERNS = [
    re.compile(r'"playurl":"(?P<url>https:\\/\\/[^\"]+?(?:\.mp4|\.m3u8)[^\"]*)"', re.I),
    re.compile(r'"url":"(?P<url>https:\\/\\/[^\"]+?(?:\.mp4|\.m3u8)[^\"]*)"', re.I),
    re.compile(r'https?://[^\s\"\'""<>]+?(?:\.mp4|\.m3u8)(?:\?[^\s\"\'""<>]*)?', re.I),
]

TITLE_PATTERNS = [
    re.compile(r'"title":"(?P<title>.*?)"'),
    re.compile(r'<title>(?P<title>.*?)</title>', re.I | re.S),
]

DEFAULT_BLOCK_HINTS = [
    "安全验证",
    "验证码",
    "请稍后重试",
    "访问异常",
    "请求异常",
    "验证后继续",
    "网络不给力",
    "人机验证",
    "secverify",
    "captcha",
]

DEFAULT_BROWSER_FIRST_HOSTS = {
    "baidu.com",
    "mbd.baidu.com",
    "qq.com",
    "v.qq.com",
    "video.qq.com",
    "weixin.qq.com",
    "mp.weixin.qq.com",
}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat()


def decode_escaped_text(text: str) -> str:
    try:
        return bytes(text, "utf-8").decode("unicode_escape")
    except Exception:
        return text.replace('\\/', '/').replace('\\u002F', '/').replace('&amp;', '&')


def decode_escaped_url(url: str) -> str:
    return decode_escaped_text(url).replace('\\/', '/').replace('\\u002F', '/').replace('&amp;', '&')


def extract_video_url_from_text(text: str) -> str | None:
    for pattern in VIDEO_URL_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        raw = match.groupdict().get("url") or match.group(0)
        return decode_escaped_url(raw)
    return None


def extract_title_from_text(text: str) -> str:
    for pattern in TITLE_PATTERNS:
        match = pattern.search(text)
        if match:
            return decode_escaped_text(match.group("title")).strip()
    return ""


def get_video_page_config() -> dict:
    try:
        cfg = load_config() or {}
        return cfg.get("video_page") or {}
    except Exception:
        return {}


def get_block_hints() -> list[str]:
    cfg = get_video_page_config()
    configured = cfg.get("block_hints") or []
    hints = [str(item).strip() for item in configured if str(item).strip()]
    return hints or list(DEFAULT_BLOCK_HINTS)


def get_browser_first_hosts() -> set[str]:
    cfg = get_video_page_config()
    configured = cfg.get("browser_first_hosts") or []
    hosts = {str(item).strip().lower() for item in configured if str(item).strip()}
    return hosts or set(DEFAULT_BROWSER_FIRST_HOSTS)


def get_config_int(key: str, default: int) -> int:
    cfg = get_video_page_config()
    value = cfg.get(key)
    try:
        return int(value)
    except Exception:
        return default


def get_config_str(key: str, default: str = "") -> str:
    cfg = get_video_page_config()
    value = cfg.get(key)
    if value is None:
        return default
    return str(value).strip()


def looks_blocked(text: str) -> bool:
    lowered = text.lower()
    return any(h.lower() in lowered for h in get_block_hints())


def fetch_page_text(url: str, timeout: int = 30) -> str:
    with httpx.Client(timeout=timeout, follow_redirects=True, headers=DEFAULT_HEADERS) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.text


def should_skip_http_extract(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    browser_first_hosts = get_browser_first_hosts()
    return any(host == item or host.endswith("." + item) for item in browser_first_hosts)


def notify_event(event: str, payload: dict, notify_file: str = "", notify_webhook: str = ""):
    body = {
        "event": event,
        "time": now_iso(),
        **payload,
    }

    if notify_file:
        path = Path(notify_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")

    if notify_webhook:
        try:
            with httpx.Client(timeout=15, follow_redirects=True) as client:
                client.post(notify_webhook, json=body)
        except Exception as e:
            print(f"Webhook notify failed: {e}")


def extract_with_http(url: str) -> tuple[str | None, str, str, bool]:
    text = fetch_page_text(url)
    video_url = extract_video_url_from_text(text)
    title = extract_title_from_text(text)
    blocked = looks_blocked(text)
    return video_url, title, text, blocked


def extract_with_browser(url: str, headless: bool = False, wait_seconds: int = 20, pause_on_block: bool = True, block_wait_seconds: int = 300, notify_file: str = "", notify_webhook: str = "") -> tuple[str | None, str, str, bool]:
    seen_video_urls: list[str] = []
    page_html = ""
    page_title = ""
    blocked = False

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, channel="chrome")
        page = browser.new_page()

        def handle_response(resp):
            rurl = resp.url
            lower = rurl.lower()
            if ".mp4" in lower or ".m3u8" in lower:
                seen_video_urls.append(rurl)

        page.on("response", handle_response)
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except PlaywrightTimeoutError:
            pass

        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            page_html = page.content()
            page_title = page.title()
            direct = extract_video_url_from_text(page_html)
            blocked = looks_blocked(page_html + "\n" + page_title)
            if direct:
                browser.close()
                return direct, page_title, page_html, blocked
            if seen_video_urls:
                browser.close()
                return seen_video_urls[0], page_title, page_html, blocked
            time.sleep(1)

        page_html = page.content()
        page_title = page.title()
        blocked = looks_blocked(page_html + "\n" + page_title)

        if blocked and pause_on_block and not headless:
            print("检测到风控/验证页面，已暂停自动流程。")
            print("请在刚打开的浏览器里手动完成验证，完成后返回这里等待脚本继续。")
            notify_event(
                "blocked_pause",
                {
                    "url": url,
                    "title": page_title,
                    "reason": "risk_control_detected",
                    "block_wait_seconds": block_wait_seconds,
                },
                notify_file,
                notify_webhook,
            )
            pause_deadline = time.time() + block_wait_seconds
            while time.time() < pause_deadline:
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except PlaywrightTimeoutError:
                    pass
                page_html = page.content()
                page_title = page.title()
                direct = extract_video_url_from_text(page_html)
                blocked = looks_blocked(page_html + "\n" + page_title)
                if direct:
                    notify_event(
                        "resume_success",
                        {
                            "url": url,
                            "title": page_title,
                            "resolved_video_url": direct,
                        },
                        notify_file,
                        notify_webhook,
                    )
                    browser.close()
                    return direct, page_title, page_html, False
                if seen_video_urls:
                    notify_event(
                        "resume_success",
                        {
                            "url": url,
                            "title": page_title,
                            "resolved_video_url": seen_video_urls[0],
                        },
                        notify_file,
                        notify_webhook,
                    )
                    browser.close()
                    return seen_video_urls[0], page_title, page_html, False
                time.sleep(2)
            print("等待人工验证超时。请完成验证后重新运行命令。")
            notify_event(
                "blocked_timeout",
                {
                    "url": url,
                    "title": page_title,
                    "reason": "manual_verification_timeout",
                    "block_wait_seconds": block_wait_seconds,
                },
                notify_file,
                notify_webhook,
            )

        browser.close()
        return (seen_video_urls[0] if seen_video_urls else extract_video_url_from_text(page_html)), page_title, page_html, blocked


def run_ingest_remote(video_url: str, tags: str = "", title: str = "", force: bool = False):
    cmd = [sys.executable, "ingest_remote.py", video_url]
    if tags:
        cmd.extend(["--tags", tags])
    if title:
        cmd.extend(["--title", title])
    if force:
        cmd.append("--force")
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def run_local_script(script_name: str):
    script_path = Path(__file__).resolve().parent / script_name
    if not script_path.exists():
        return 127, f"script not found: {script_name}"
    result = subprocess.run(
        [sys.executable, str(script_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
    return result.returncode, output.strip()


def infer_default_tags(url: str, current_tags: str) -> str:
    if current_tags:
        return current_tags
    host = (urlparse(url).hostname or "").lower()
    if "baidu.com" in host:
        return "Baidu,视频,转写"
    return "视频页,转写"


def main():
    parser = argparse.ArgumentParser(description="Extract real video URL from a landing page, then ingest it.")
    parser.add_argument("url", help="Video landing page URL")
    parser.add_argument("--tags", default="", help="comma-separated tags")
    parser.add_argument("--title", default="", help="override title")
    parser.add_argument("--force", action="store_true", help="force duplicate import")
    parser.add_argument("--headless", action="store_true", help="run browser headless")
    parser.add_argument("--extract-only", action="store_true", help="only print extracted real video URL")
    parser.add_argument("--browser-wait-seconds", type=int, default=None, help="seconds to wait for automatic browser extraction")
    parser.add_argument("--block-wait-seconds", type=int, default=None, help="seconds to pause for manual verification when blocked")
    parser.add_argument("--no-pause-on-block", action="store_true", help="do not pause for manual verification when blocked")
    parser.add_argument("--notify-file", default="", help="write latest event JSON to a local file")
    parser.add_argument("--notify-webhook", default="", help="POST latest event JSON to a webhook URL")
    parser.add_argument("--export-site", action="store_true", help="run export_site_data.py after successful ingest")
    parser.add_argument("--publish-site", action="store_true", help="run publish_site_data.py after successful ingest")
    args = parser.parse_args()

    video_url = None
    detected_title = ""
    raw_text = ""
    blocked = False

    browser_first_hosts = get_browser_first_hosts()
    browser_wait_seconds = args.browser_wait_seconds if args.browser_wait_seconds is not None else get_config_int("browser_wait_seconds", 20)
    block_wait_seconds = args.block_wait_seconds if args.block_wait_seconds is not None else get_config_int("block_wait_seconds", 300)
    notify_file = args.notify_file or get_config_str("notify_file", "")
    notify_webhook = args.notify_webhook or get_config_str("notify_webhook", "")
    auto_export_site = args.export_site or str(get_video_page_config().get("auto_export_site", "false")).lower() == "true"
    auto_publish_site = args.publish_site or str(get_video_page_config().get("auto_publish_site", "false")).lower() == "true"
    if auto_publish_site:
        auto_export_site = True

    notify_event(
        "start",
        {
            "url": args.url,
            "browser_wait_seconds": browser_wait_seconds,
            "block_wait_seconds": block_wait_seconds,
        },
        notify_file,
        notify_webhook,
    )

    notify_event(
        "start",
        {
            "url": args.url,
            "browser_wait_seconds": browser_wait_seconds,
            "block_wait_seconds": block_wait_seconds,
        },
        notify_file,
        notify_webhook,
    )

    # ── 百度视频：优先走专用提取模块 ──────────────────────────────────────
    if is_baidu_video_url(args.url):
        print("Baidu video URL detected. Using extract_baidu_video module.")
        notify_event(
            "baidu_extract_start",
            {"url": args.url},
            notify_file,
            notify_webhook,
        )
        baidu_result = _baidu_extract(
            url=args.url,
            headless=args.headless,
            total_timeout=15,
            save_debug_on_fail=True,
        )
        if not baidu_result.get("ok"):
            reason = baidu_result.get("reason", "unknown")
            debug_dir = baidu_result.get("debug_dir")
            print(f"Baidu video extraction failed: {reason}")
            if debug_dir:
                print(f"Debug artifacts saved to: {debug_dir}")
            notify_event(
                "baidu_extract_failed",
                {
                    "url": args.url,
                    "reason": reason,
                    "step": baidu_result.get("step"),
                    "debug_dir": debug_dir,
                },
                notify_file,
                notify_webhook,
            )
            raise SystemExit(2)
        video_url = baidu_result["video_url"]
        detected_title = args.title or baidu_result.get("title", "")
        print(f"Baidu extract succeeded: {video_url}")
        notify_event(
            "baidu_extract_done",
            {
                "url": args.url,
                "resolved_video_url": video_url,
                "source": baidu_result.get("source"),
                "title": detected_title,
            },
            notify_file,
            notify_webhook,
        )
        # 直接跳到下载/转录逻辑
        final_title = detected_title
        final_tags = infer_default_tags(args.url, args.tags)
        notify_event(
            "resolved",
            {
                "url": args.url,
                "title": final_title,
                "resolved_video_url": video_url,
                "tags": final_tags,
            },
            notify_file,
            notify_webhook,
        )
        if not args.extract_only:
            result = run_ingest_remote(video_url, tags=final_tags, title=final_title, force=args.force)
            if result.stdout:
                print(result.stdout.strip())
            if result.returncode != 0:
                if result.stderr:
                    print(result.stderr.strip())
                notify_event(
                    "ingest_failed",
                    {
                        "url": args.url,
                        "title": final_title,
                        "resolved_video_url": video_url,
                        "returncode": result.returncode,
                        "stderr": (result.stderr or "")[-4000:],
                    },
                    notify_file,
                    notify_webhook,
                )
                raise SystemExit(result.returncode)
            notify_event(
                "done",
                {
                    "url": args.url,
                    "title": final_title,
                    "resolved_video_url": video_url,
                    "stdout": (result.stdout or "")[-4000:],
                },
                notify_file,
                notify_webhook,
            )
        return
    # ── 非百度：走原有 HTTP + Playwright 流程 ────────────────────────────
        print("Browser-first whitelist matched. Skipping HTTP direct extraction.")
        print("Configured browser-first hosts: " + ", ".join(sorted(browser_first_hosts)))
        notify_event(
            "browser_first",
            {
                "url": args.url,
                "browser_first_hosts": sorted(browser_first_hosts),
            },
            notify_file,
            notify_webhook,
        )
    else:
        try:
            video_url, detected_title, raw_text, blocked = extract_with_http(args.url)
        except Exception as e:
            print(f"HTTP extract failed: {e}")
            notify_event(
                "http_extract_error",
                {"url": args.url, "error": str(e)},
                notify_file,
                notify_webhook,
            )

    if not video_url:
        if blocked:
            print("HTTP path detected a risk-control / verification page.")
        else:
            print("HTTP path did not yield a real video URL.")
        print("Falling back to Playwright browser extraction...")
        notify_event(
            "browser_fallback",
            {
                "url": args.url,
                "blocked": blocked,
            },
            notify_file,
            notify_webhook,
        )
        video_url, page_title, page_html, browser_blocked = extract_with_browser(
            args.url,
            headless=args.headless,
            wait_seconds=browser_wait_seconds,
            pause_on_block=not args.no_pause_on_block,
            block_wait_seconds=block_wait_seconds,
            notify_file=notify_file,
            notify_webhook=notify_webhook,
        )
        detected_title = args.title or detected_title or page_title
        raw_text = page_html or raw_text
        blocked = browser_blocked

    if not video_url:
        print("未能自动提取到真实视频地址。")
        if blocked:
            print("原因：检测到风控/验证页面，且在等待窗口内未完成验证。")
        print("请在本机浏览器完成验证后重新运行，或直接把真实 mp4/m3u8 链接发给我。")
        notify_event(
            "failed",
            {
                "url": args.url,
                "title": detected_title,
                "blocked": blocked,
                "reason": "video_url_not_resolved",
            },
            notify_file,
            notify_webhook,
        )
        raise SystemExit(2)

    final_title = args.title or detected_title
    final_tags = infer_default_tags(args.url, args.tags)

    print(f"Resolved video URL: {video_url}")
    if final_title:
        print(f"Resolved title: {final_title}")

    notify_event(
        "resolved",
        {
            "url": args.url,
            "title": final_title,
            "resolved_video_url": video_url,
            "tags": final_tags,
        },
        notify_file,
        notify_webhook,
    )

    if args.extract_only:
        return

    result = run_ingest_remote(video_url, tags=final_tags, title=final_title, force=args.force)
    if result.stdout:
        print(result.stdout.strip())
    if result.returncode != 0:
        if result.stderr:
            print(result.stderr.strip())
        notify_event(
            "ingest_failed",
            {
                "url": args.url,
                "title": final_title,
                "resolved_video_url": video_url,
                "returncode": result.returncode,
                "stderr": (result.stderr or "")[-4000:],
            },
            notify_file,
            notify_webhook,
        )
        raise SystemExit(result.returncode)

    if auto_export_site:
        print("[auto-export] start: export_site_data.py")
        notify_event(
            "export_start",
            {
                "url": args.url,
                "title": final_title,
            },
            notify_file,
            notify_webhook,
        )
        export_code, export_output = run_local_script("export_site_data.py")
        if export_code != 0:
            print(f"[auto-export] failed: exit={export_code}")
            if export_output:
                print(export_output[-4000:])
            notify_event(
                "export_failed",
                {
                    "url": args.url,
                    "title": final_title,
                    "returncode": export_code,
                    "output": export_output[-4000:],
                },
                notify_file,
                notify_webhook,
            )
            raise SystemExit(export_code)
        print("[auto-export] done")
        if export_output:
            print(export_output[-4000:])
        notify_event(
            "export_done",
            {
                "url": args.url,
                "title": final_title,
                "output": export_output[-4000:],
            },
            notify_file,
            notify_webhook,
        )

    if auto_publish_site:
        print("[auto-publish] start: publish_site_data.py")
        notify_event(
            "publish_start",
            {
                "url": args.url,
                "title": final_title,
            },
            notify_file,
            notify_webhook,
        )
        publish_code, publish_output = run_local_script("publish_site_data.py")
        if publish_code != 0:
            print(f"[auto-publish] failed: exit={publish_code}")
            if publish_output:
                print(publish_output[-4000:])
            notify_event(
                "publish_failed",
                {
                    "url": args.url,
                    "title": final_title,
                    "returncode": publish_code,
                    "output": publish_output[-4000:],
                },
                notify_file,
                notify_webhook,
            )
            raise SystemExit(publish_code)
        print("[auto-publish] done")
        if publish_output:
            print(publish_output[-4000:])
        notify_event(
            "publish_done",
            {
                "url": args.url,
                "title": final_title,
                "output": publish_output[-4000:],
            },
            notify_file,
            notify_webhook,
        )

    notify_event(
        "done",
        {
            "url": args.url,
            "title": final_title,
            "resolved_video_url": video_url,
            "stdout": (result.stdout or "")[-4000:],
            "auto_export_site": auto_export_site,
            "auto_publish_site": auto_publish_site,
        },
        notify_file,
        notify_webhook,
    )


if __name__ == "__main__":
    main()
