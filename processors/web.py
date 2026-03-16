from pathlib import Path

import httpx
import trafilatura
from bs4 import BeautifulSoup

from .summarizer import render_summary_markdown, summarize_text
from .utils import load_config, md_to_text, write_text
from .web_wechat import is_wechat_article_url, process_web_wechat


def process_web(url: str, raw_dir: Path) -> dict:
    if is_wechat_article_url(url):
        return process_web_wechat(url, raw_dir)
    cfg = load_config()
    timeout = cfg["web"].get("timeout_sec", 20)
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        html = resp.text
    raw_path = raw_dir / "source.html"
    if cfg["web"].get("save_raw_html", True):
        write_text(raw_path, html)
    extracted_md = trafilatura.extract(html, include_comments=False, include_tables=True, output_format="markdown")
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.string.strip() if soup.title and soup.title.string else None
    author = None
    author_meta = soup.find("meta", attrs={"name": "author"})
    if author_meta and author_meta.get("content"):
        author = author_meta["content"].strip()
    published_at = None
    for key in [("meta", {"property": "article:published_time"}), ("meta", {"name": "pubdate"}), ("meta", {"name": "publishdate"}), ("meta", {"name": "date"})]:
        tag = soup.find(key[0], attrs=key[1])
        if tag and tag.get("content"):
            published_at = tag["content"].strip(); break
    if not extracted_md:
        extracted_md = soup.get_text("\n", strip=True)
    content_text = md_to_text(extracted_md)
    summary_data = summarize_text(content_text, content_type="web")
    summary = summary_data.get("summary", "")
    content_md = "\n".join([render_summary_markdown(summary_data), "", extracted_md])
    return {"type": "web", "source": url, "source_type": "url", "title": title, "author": author, "published_at": published_at, "summary": summary, "summary_data": summary_data, "content_md": content_md, "content_text": content_text, "raw_path": str(raw_path), "status": "processed" if content_text.strip() else "partial"}
