from datetime import datetime
from pathlib import Path

from slugify import slugify

from .utils import ensure_dir, load_config, now_iso, sha256_text


def build_doc_id():
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    short = datetime.now().strftime("%f")[:6]
    return f"{ts}-{short}"


def safe_title_for_filename(title: str | None) -> str:
    if not title:
        return "untitled"
    s = slugify(title, allow_unicode=True)
    return s[:80] if s else "untitled"


def build_storage_paths(doc_id: str, title: str | None):
    cfg = load_config()
    base = Path(cfg["storage"]["base_dir"])
    now = datetime.now()
    year = str(now.year)
    month = f"{now.month:02d}"
    raw_dir = base / cfg["storage"]["raw_dir"] / year / month
    notes_dir = base / cfg["storage"]["notes_dir"] / year / month
    meta_dir = base / cfg["storage"]["meta_dir"] / year / month
    ensure_dir(raw_dir)
    ensure_dir(notes_dir)
    ensure_dir(meta_dir)
    safe_title = safe_title_for_filename(title)
    return {
        "raw_dir": raw_dir,
        "notes_dir": notes_dir,
        "meta_dir": meta_dir,
        "note_path": notes_dir / f"{doc_id}-{safe_title}.md",
        "meta_path": meta_dir / f"{doc_id}.json",
    }


def make_frontmatter(doc: dict) -> str:
    tags = doc.get("tags", [])
    tags_yaml = "\n".join([f"  - {t}" for t in tags]) if tags else "  - untagged"
    return f"""---
id: {doc['id']}
type: {doc['type']}
title: {doc.get('title', '')}
source: {doc.get('source', '')}
captured_at: {doc['captured_at']}
author: {doc.get('author', '')}
published_at: {doc.get('published_at', '')}
language: {doc.get('language', '')}
tags:
{tags_yaml}
status: {doc.get('status', 'processed')}
content_hash: {doc.get('content_hash', '')}
summary: {doc.get('summary', '')}
---
"""


def render_markdown(doc: dict) -> str:
    duplicate_warning = doc.get("duplicate_warning")
    duplicate_block = ""
    if duplicate_warning:
        duplicate_block = f"\n> ⚠️ 重复记录：已存在 {duplicate_warning.get('existing_id')} - {duplicate_warning.get('existing_title', '')}\n"
    frontmatter = make_frontmatter(doc)
    title = doc.get('title') or 'Untitled'
    content_md = doc.get('content_md', '') or ''
    body = f"# {title}\n\n{duplicate_block}{content_md}\n"
    return frontmatter + "\n" + body


def finalize_document(base: dict) -> dict:
    content_text = base.get("content_text") or ""
    content_hash = base.get("content_hash") or sha256_text(content_text)
    return {
        "id": base.get("id") or build_doc_id(),
        "type": base["type"],
        "title": base.get("title"),
        "source": base.get("source"),
        "source_type": base.get("source_type"),
        "captured_at": base.get("captured_at") or now_iso(),
        "published_at": base.get("published_at"),
        "author": base.get("author"),
        "language": base.get("language", "zh"),
        "summary": base.get("summary", ""),
        "content_md": base.get("content_md", ""),
        "content_text": content_text,
        "content_hash": content_hash,
        "source_file_hash": base.get("source_file_hash"),
        "status": base.get("status", "processed"),
        "tags": base.get("tags", []),
        "created_at": base.get("created_at") or now_iso(),
        "updated_at": now_iso(),
        "raw_path": base.get("raw_path"),
    }
