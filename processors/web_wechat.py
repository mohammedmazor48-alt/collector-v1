from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from .summarizer import render_summary_markdown, summarize_text
from .utils import md_to_text, write_text
from .web_browser import classify_wechat_playwright_result, try_fetch_with_playwright

PROJECT_ROOT = Path(__file__).parent.parent


def is_wechat_article_url(url: str) -> bool:
    return "mp.weixin.qq.com" in url.lower()


def classify_wechat_html(html: str, final_url: str) -> dict:
    text = html or ""
    final_url = final_url or ""
    if "wappoc_appmsgcaptcha" in final_url:
        return {"status": "blocked", "block_reason": "wechat_captcha", "message": "微信公众号文章触发验证码/人机校验"}
    if "该内容已被发布者删除" in text or "内容已被删除" in text:
        return {"status": "blocked", "block_reason": "wechat_deleted", "message": "文章可能已删除或不可访问"}
    if "访问过于频繁" in text or "环境异常" in text:
        return {"status": "blocked", "block_reason": "wechat_unknown_block", "message": "访问受限，可能命中微信风控"}
    if "js_content" in text or "rich_media_content" in text:
        return {"status": "ok", "block_reason": None, "message": "检测到可能的正文区域"}
    return {"status": "blocked", "block_reason": "wechat_empty", "message": "未检测到正文，疑似空页或受限页"}


def classify_jina_wechat_markdown(text: str) -> dict:
    lowered = (text or "").lower()
    signals = [
        "requiring captcha",
        "weixin official accounts platform",
        "当前环境异常",
        "完成验证后即可继续访问",
        "去验证",
        "warning: this page maybe requiring captcha",
    ]
    if any(signal in lowered for signal in [s.lower() for s in signals]):
        return {
            "status": "blocked",
            "block_reason": "wechat_captcha",
            "message": "Jina Reader 返回了微信验证页，而不是文章正文",
        }
    if not text or len(text.strip()) < 80:
        return {
            "status": "empty",
            "block_reason": None,
            "message": "Jina Reader 未返回足够正文内容",
        }
    return {
        "status": "ok",
        "block_reason": None,
        "message": "Jina Reader 返回了可用正文",
    }


def try_jina_reader_markdown(url: str) -> dict | None:
    jina_url = f"https://r.jina.ai/http://{url}" if url.startswith("https://") else f"https://r.jina.ai/{url}"
    headers = {"Accept": "text/markdown", "User-Agent": "Mozilla/5.0"}
    try:
        with httpx.Client(timeout=40, follow_redirects=True, headers=headers) as client:
            resp = client.get(jina_url)
            resp.raise_for_status()
            text = (resp.text or "").strip()
        classification = classify_jina_wechat_markdown(text)
        return {"markdown": text, "reader_url": jina_url, "classification": classification}
    except Exception:
        return None


def infer_wechat_title(page_title: str | None, content_text: str) -> str:
    body = (content_text or "").strip()
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    for line in lines[:8]:
        if 8 <= len(line) <= 60 and "原创" not in line and "观复日课" not in line and not line.startswith("20"):
            return line
    if page_title:
        cleaned = page_title.replace(" - 微信公众号", "").replace("_微信公众平台", "").strip()
        if cleaned:
            return cleaned
    return "wechat-article"


def download_article_images(html: str, doc_id: str, base_dir: Path) -> str:
    """下载文章图片到本地，替换 src 为站内路径 /images/<doc_id>/"""
    soup = BeautifulSoup(html, "html.parser")
    imgs = [img for img in soup.find_all("img") if (img.get("src") or "").startswith("http")]
    if not imgs:
        return html

    img_dir = base_dir / "knowledge-vault" / "assets" / "images" / doc_id
    img_dir.mkdir(parents=True, exist_ok=True)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Referer": "https://mp.weixin.qq.com/",
    }
    ct_to_ext = {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif", "image/webp": "webp"}

    for idx, img in enumerate(imgs, 1):
        src = img["src"]
        try:
            with httpx.Client(timeout=20, follow_redirects=True) as client:
                resp = client.get(src, headers=headers)
                resp.raise_for_status()
            ct = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
            if ct not in ct_to_ext and "wx_fmt=" in src:
                fmt = src.split("wx_fmt=")[-1].split("&")[0]
                ext = "jpg" if fmt in ("jpeg", "jpg") else fmt if fmt in ("png", "gif", "webp") else "jpg"
            else:
                ext = ct_to_ext.get(ct, "jpg")
            filename = f"{idx:03d}.{ext}"
            (img_dir / filename).write_bytes(resp.content)
            img["src"] = f"/images/{doc_id}/{filename}"
            print(f"    [img] {idx}/{len(imgs)} {filename} ({len(resp.content)//1024}KB)")
        except Exception as e:
            print(f"[!] 图片下载失败 ({idx}): {src[:80]} - {e}")

    return str(soup)


def extract_article_html(html: str) -> str | None:
    """从微信文章页面提取正文 HTML，保留图片、链接、排版"""
    soup = BeautifulSoup(html, "html.parser")
    content = soup.find(id="js_content") or soup.find(class_="rich_media_content")
    if not content:
        return None
    for tag in content.find_all(["script", "style", "noscript"]):
        tag.decompose()
    for img in content.find_all("img"):
        if img.get("data-src") and not img.get("src"):
            img["src"] = img["data-src"]
        img.attrs = {k: v for k, v in img.attrs.items() if k in ("src", "alt", "width", "height")}
    return str(content)


def process_web_wechat(url: str, raw_dir: Path) -> dict:
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"}
    with httpx.Client(timeout=20, follow_redirects=True, headers=headers) as client:
        resp = client.get(url)
        resp.raise_for_status()
        html = resp.text
        final_url = str(resp.url)
    raw_path = raw_dir / "source-wechat.html"
    write_text(raw_path, html)
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.string.strip() if soup.title and soup.title.string else None

    pw_result = try_fetch_with_playwright(
        url,
        wait_ms=7000,
        headless=False,
        pause_on_block=True,
        block_wait_seconds=300,
        channel="chrome",
    )
    if pw_result:
        pw_raw_path = raw_dir / "source-wechat-playwright.html"
        write_text(pw_raw_path, pw_result["html"])
        pw_classification = classify_wechat_playwright_result(pw_result.get("text", ""), pw_result.get("html", ""), pw_result.get("final_url", ""))
        if pw_classification.get("status") == "ok":
            content_text = pw_result.get("text", "").strip()
            inferred_title = infer_wechat_title(title, content_text)
            summary_data = summarize_text(content_text, content_type="web")
            summary = summary_data.get("summary", "")
            content_html = extract_article_html(pw_result.get("html", ""))
            if content_html:
                doc_id = raw_dir.name
                content_html = download_article_images(content_html, doc_id, PROJECT_ROOT)
            content_md = "\n".join([render_summary_markdown(summary_data), "", content_text])
            return {
                "type": "web",
                "source": url,
                "source_type": "url",
                "title": inferred_title,
                "summary": summary,
                "summary_data": summary_data,
                "content_md": content_md,
                "content_html": content_html,
                "content_text": content_text,
                "raw_path": str(pw_raw_path),
                "status": "processed" if content_text.strip() else "partial",
                "block_reason": None,
                "final_url": pw_result.get("final_url", final_url),
                "wechat_backend": "playwright",
            }
        if pw_classification.get("status") == "blocked":
            return {
                "type": "web",
                "source": url,
                "source_type": "url",
                "title": title or "wechat-article-blocked",
                "summary": pw_classification.get("message", "微信文章读取受限"),
                "content_md": pw_classification.get("message", "微信文章读取受限"),
                "content_text": pw_classification.get("message", "微信文章读取受限"),
                "raw_path": str(pw_raw_path),
                "status": "blocked",
                "block_reason": pw_classification.get("block_reason", "wechat_captcha"),
                "final_url": pw_result.get("final_url", final_url),
                "wechat_backend": "playwright",
            }

    jina_result = try_jina_reader_markdown(url)
    if jina_result:
        jina_classification = jina_result.get("classification") or {}
        if jina_classification.get("status") == "blocked":
            return {
                "type": "web",
                "source": url,
                "source_type": "url",
                "title": title or "wechat-article-blocked",
                "summary": jina_classification.get("message", "微信文章读取受限"),
                "content_md": jina_classification.get("message", "微信文章读取受限"),
                "content_text": jina_classification.get("message", "微信文章读取受限"),
                "raw_path": str(raw_path),
                "status": "blocked",
                "block_reason": jina_classification.get("block_reason", "wechat_captcha"),
                "final_url": final_url,
                "wechat_backend": "jina_reader",
            }
        if jina_classification.get("status") == "ok":
            extracted_md = jina_result["markdown"]
            content_text = md_to_text(extracted_md)
            inferred_title = infer_wechat_title(title, content_text)
            summary_data = summarize_text(content_text, content_type="web")
            summary = summary_data.get("summary", "")
            content_md = "\n".join([render_summary_markdown(summary_data), "", extracted_md])
            return {
                "type": "web",
                "source": url,
                "source_type": "url",
                "title": inferred_title,
                "summary": summary,
                "summary_data": summary_data,
                "content_md": content_md,
                "content_text": content_text,
                "raw_path": str(raw_path),
                "status": "processed" if content_text.strip() else "partial",
                "block_reason": None,
                "final_url": final_url,
                "wechat_backend": "jina_reader",
            }

    classification = classify_wechat_html(html, final_url)
    if classification["status"] != "ok":
        return {"type": "web", "source": url, "source_type": "url", "title": title or "wechat-article-blocked", "summary": classification["message"], "content_md": f"## 抓取状态\n\n- 状态：{classification['status']}\n- 原因：{classification['block_reason']}\n- 说明：{classification['message']}\n- 最终跳转：{final_url}\n", "content_text": classification["message"], "raw_path": str(raw_path), "status": classification["status"], "block_reason": classification["block_reason"], "final_url": final_url, "wechat_backend": "html_fallback"}
    return {"type": "web", "source": url, "source_type": "url", "title": title or "wechat-article", "summary": "检测到微信正文页，但 Jina Reader 与 Playwright 都未成功返回可用正文", "content_md": f"## 微信文章抓取\n\n- 状态：ok\n- 说明：检测到正文页，但 Jina Reader 与 Playwright 都未成功返回可用正文\n- 最终跳转：{final_url}\n", "content_text": "检测到微信正文页", "raw_path": str(raw_path), "status": "partial", "block_reason": None, "final_url": final_url, "wechat_backend": "html_fallback"}
