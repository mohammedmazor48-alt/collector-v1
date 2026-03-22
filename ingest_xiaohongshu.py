"""
ingest_xiaohongshu.py  —  小红书视频页 → 转录入库

用法:
  python ingest_xiaohongshu.py <URL> [--tags 小红书,视频] [--title "标题"] [--force]

流程:
  1. 从 xiaohongshu-mcp 的 cookies.json 加载登录 cookie
  2. Playwright 打开页面 (注入 cookie，非无头，视频自动播放)
  3. 拦截 CDN 视频请求 (.mp4 / xhscdn.com)
  4. 用 requests 流式下载视频到临时目录
  5. 调用 ingest.py 转录入库
"""

import argparse
import io
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

# Windows GBK 终端强制 UTF-8 输出
if sys.stdout.encoding and sys.stdout.encoding.lower() in ("gbk", "gb2312", "cp936"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

COOKIES_JSON = Path(r"D:\tools\xiaohongshu-mcp\cookies.json")
DOWNLOAD_DIR = Path(__file__).parent / "knowledge-vault" / "raw" / "xiaohongshu_videos"

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Referer": "https://www.xiaohongshu.com/",
    "Accept": "*/*",
}


def load_cookies() -> list[dict]:
    if not COOKIES_JSON.exists():
        raise FileNotFoundError(f"找不到 cookie 文件: {COOKIES_JSON}\n请先运行登录程序。")
    with open(COOKIES_JSON, encoding="utf-8") as f:
        raw = json.load(f)
    # Playwright 格式要求 expires 为 float 或 -1，sameSite 为枚举值
    result = []
    for c in raw:
        cookie = {
            "name": c.get("name", ""),
            "value": c.get("value", ""),
            "domain": c.get("domain", ".xiaohongshu.com"),
            "path": c.get("path", "/"),
        }
        expires = c.get("expires", -1)
        if expires and expires > 0:
            cookie["expires"] = float(expires)
        if c.get("httpOnly"):
            cookie["httpOnly"] = True
        if c.get("secure"):
            cookie["secure"] = True
        same_site = c.get("sameSite", "")
        if same_site in ("Strict", "Lax", "None"):
            cookie["sameSite"] = same_site
        result.append(cookie)
    return result


def is_xhs_video_url(url: str, content_type: str = "") -> bool:
    """判断是否为小红书视频 CDN 地址（通过 Content-Type 或 URL 特征）"""
    ct = content_type.lower()
    # 优先通过 Content-Type 判断
    if ct.startswith("video/"):
        return True
    lower = url.lower()
    parsed = urlparse(url)
    host = parsed.hostname or ""
    path = parsed.path.lower()
    # 排除明显的静态资源
    if any(path.endswith(ext) for ext in (".js", ".json", ".css", ".html", ".woff", ".woff2", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico")):
        return False
    # 小红书视频 CDN 域名 (sns-video-*, fe-video-qc)
    video_cdn_hosts = ("sns-video-bd.xhscdn.com", "sns-video-qc.xhscdn.com", "fe-video-qc.xhscdn.com")
    if any(host == h for h in video_cdn_hosts):
        return True
    # 通用 .mp4 / .m3u8
    return ".mp4" in lower or ".m3u8" in lower


def download_video(url: str, out_path: Path) -> bool:
    """流式下载视频，返回是否成功"""
    print(f"下载视频: {url[:80]}...")
    try:
        with httpx.Client(timeout=120, follow_redirects=True, headers=DEFAULT_HEADERS) as client:
            with client.stream("GET", url) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("content-length", 0))
                downloaded = 0
                with open(out_path, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=65536):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                if total:
                    print(f"  下载完成: {downloaded / 1024 / 1024:.1f} MB / {total / 1024 / 1024:.1f} MB")
                else:
                    print(f"  下载完成: {downloaded / 1024 / 1024:.1f} MB")
        return True
    except Exception as e:
        print(f"  下载失败: {e}")
        return False


def extract_video_url(page_url: str, wait_seconds: int = 30) -> tuple[str | None, str]:
    """使用 Playwright 打开页面，注入 cookie，拦截视频 CDN 请求"""
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

    cookies = load_cookies()
    # (url, content_type, size_bytes)
    seen: list[tuple[str, str, int]] = []
    seen_urls: set[str] = set()
    page_title = ""

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, channel="chrome")
        ctx = browser.new_context(
            user_agent=DEFAULT_HEADERS["User-Agent"],
            locale="zh-CN",
        )
        ctx.add_cookies(cookies)
        page = ctx.new_page()

        def on_response(resp):
            url = resp.url
            ct = resp.headers.get("content-type", "").split(";")[0].strip().lower()
            if is_xhs_video_url(url, ct) and url not in seen_urls:
                size = int(resp.headers.get("content-length", 0) or 0)
                print(f"  捕获: [{ct}] {size//1024}KB  {url[:80]}...")
                seen.append((url, ct, size))
                seen_urls.add(url)

        page.on("response", on_response)

        print("打开页面...")
        page.goto(page_url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except PlaywrightTimeout:
            pass

        page_title = page.title()
        deadline = time.time() + wait_seconds
        print(f"等待视频请求 (最多 {wait_seconds}s)...")

        while time.time() < deadline:
            if any(ct.startswith("video/") for _, ct, _ in seen):
                break  # 已捕获真实视频流，不用再等
            # 尝试点击播放按钮
            try:
                play_btn = page.query_selector("video")
                if play_btn:
                    play_btn.click()
            except Exception:
                pass
            time.sleep(1)

        browser.close()

    if seen:
        # 优先选 video/* 且文件最大的
        video_entries = [(u, ct, s) for u, ct, s in seen if ct.startswith("video/")]
        if video_entries:
            best_url, _, _ = max(video_entries, key=lambda x: x[2])
        else:
            best_url = max(seen, key=lambda x: x[2])[0]
        return best_url, page_title
    return None, page_title


def run_ingest(video_path: Path, tags: str, title: str, force: bool) -> int:
    import subprocess
    cmd = [sys.executable, "ingest.py", str(video_path)]
    if tags:
        cmd.extend(["--tags", tags])
    if title:
        cmd.extend(["--title", title])
    if force:
        cmd.append("--force")
    result = subprocess.run(
        cmd,
        encoding="utf-8",
        errors="replace",
        cwd=Path(__file__).parent,
    )
    return result.returncode


def main():
    parser = argparse.ArgumentParser(description="小红书视频 → 转录入库")
    parser.add_argument("url", help="小红书视频页 URL")
    parser.add_argument("--tags", default="小红书,视频,转写")
    parser.add_argument("--title", default="")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--extract-only", action="store_true", help="只打印视频 URL，不下载")
    parser.add_argument("--wait", type=int, default=30, help="等待视频请求的秒数")
    args = parser.parse_args()

    print(f"目标: {args.url}")

    video_url, page_title = extract_video_url(args.url, wait_seconds=args.wait)

    if not video_url:
        print("未能捕获到视频 URL。")
        print("可能原因：视频需要手动点击播放，或页面结构特殊。")
        sys.exit(1)

    print(f"视频 URL: {video_url}")
    print(f"页面标题: {page_title}")

    if args.extract_only:
        return

    title = args.title or page_title or "小红书视频"

    # 生成下载路径
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    url_hash = abs(hash(video_url)) % 10**9
    out_path = DOWNLOAD_DIR / f"xhs_{url_hash}.mp4"

    if not download_video(video_url, out_path):
        sys.exit(1)

    print(f"已保存到: {out_path}")
    print("开始转录入库...")

    rc = run_ingest(out_path, tags=args.tags, title=title, force=args.force)
    sys.exit(rc)


if __name__ == "__main__":
    main()
