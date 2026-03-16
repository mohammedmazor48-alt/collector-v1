from pathlib import Path
import time


def try_fetch_with_playwright(url: str, wait_ms: int = 5000, headless: bool = True, pause_on_block: bool = False, block_wait_seconds: int = 180, channel: str = "chrome") -> dict | None:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception:
        return None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless, channel=channel)
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except PlaywrightTimeoutError:
                pass
            page.wait_for_timeout(wait_ms)
            final_url = page.url
            html = page.content()
            text = page.locator("body").inner_text(timeout=5000)

            if pause_on_block and not headless:
                classification = classify_wechat_playwright_result(text, html, final_url)
                if classification.get("status") == "blocked":
                    print("检测到微信验证/风控页，请在打开的浏览器中手动完成验证，脚本会继续等待。")
                    deadline = time.time() + block_wait_seconds
                    while time.time() < deadline:
                        try:
                            page.wait_for_load_state("networkidle", timeout=5000)
                        except PlaywrightTimeoutError:
                            pass
                        page.wait_for_timeout(1500)
                        final_url = page.url
                        html = page.content()
                        text = page.locator("body").inner_text(timeout=5000)
                        classification = classify_wechat_playwright_result(text, html, final_url)
                        if classification.get("status") == "ok":
                            break

            browser.close()
        return {
            "html": html,
            "text": text,
            "final_url": final_url,
        }
    except Exception:
        return None


def classify_wechat_playwright_result(text: str, html: str, final_url: str) -> dict:
    blob = "\n".join([text or "", html or "", final_url or ""]).lower()
    blocked_signals = [
        "wappoc_appmsgcaptcha",
        "requiring captcha",
        "环境异常",
        "完成验证后即可继续访问",
        "去验证",
        "weixin official accounts platform",
    ]
    if any(sig.lower() in blob for sig in blocked_signals):
        return {
            "status": "blocked",
            "block_reason": "wechat_captcha",
            "message": "Playwright 打开的仍是微信验证页",
        }
    if html and ("js_content" in html or "rich_media_content" in html) and text and len(text.strip()) > 120:
        return {
            "status": "ok",
            "block_reason": None,
            "message": "Playwright 检测到可能的微信正文",
        }
    return {
        "status": "empty",
        "block_reason": None,
        "message": "Playwright 未检测到可用正文",
    }
