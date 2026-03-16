import argparse
from pathlib import Path

from processors.audio import process_audio
from processors.db import find_by_content_hash, find_by_source, find_by_source_file_hash, init_db, upsert_document
from processors.image import process_image
from processors.normalize import build_doc_id, build_storage_paths, finalize_document, render_markdown
from processors.pdf import process_pdf
from processors.progress import make_progress_callback
from processors.utils import is_url, load_config, sha256_file, write_json, write_text
from processors.video import process_video
from processors.web import process_web

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
PDF_EXTS = {".pdf"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".webm"}


def detect_input_type(value: str) -> str:
    if is_url(value):
        return "web"
    ext = Path(value).suffix.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in PDF_EXTS:
        return "pdf"
    if ext in AUDIO_EXTS:
        return "audio"
    if ext in VIDEO_EXTS:
        return "video"
    raise ValueError(f"Unsupported input type: {value}")


def main():
    parser = argparse.ArgumentParser(description="Universal content ingestor V1")
    parser.add_argument("input")
    parser.add_argument("--tags", default="")
    parser.add_argument("--title", default="")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--notify-file", default="")
    parser.add_argument("--notify-webhook", default="")
    args = parser.parse_args()

    init_db()
    cfg = load_config(); dedupe_cfg = cfg.get("dedupe", {})
    input_value = args.input; kind = detect_input_type(input_value); tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    progress = make_progress_callback(args.notify_file, args.notify_webhook, {"input": input_value, "kind": kind})
    progress("processing_started", {"title": args.title, "tags": tags})
    source_value = input_value; source_file_hash = None
    if kind != "web":
        source_value = str(Path(input_value).resolve())
    if not args.force and dedupe_cfg.get("source_strict", True):
        existing = find_by_source(source_value)
        if existing:
            print("Skipped: duplicate source"); print(f"id: {existing['id']}"); print(f"title: {existing['title']}"); print(f"note: {existing['note_path']}"); return
    if not args.force and kind != "web":
        source_file_hash = sha256_file(Path(source_value))
        if dedupe_cfg.get("source_file_hash_strict", True):
            existing_file = find_by_source_file_hash(source_file_hash)
            if existing_file:
                print("Skipped: duplicate source file hash"); print(f"id: {existing_file['id']}"); print(f"title: {existing_file['title']}"); print(f"note: {existing_file['note_path']}"); return
    temp_doc_id = build_doc_id(); paths = build_storage_paths(temp_doc_id, args.title or None); raw_dir = paths["raw_dir"] / temp_doc_id; raw_dir.mkdir(parents=True, exist_ok=True)
    progress("processing_dispatch", {"doc_id": temp_doc_id, "raw_dir": str(raw_dir)})
    processor_map = {"web": process_web, "image": process_image, "pdf": process_pdf, "audio": process_audio, "video": process_video}
    processor = processor_map[kind]
    if kind in {"audio", "video"}:
        result = processor(input_value, raw_dir, progress=progress)
    else:
        result = processor(input_value, raw_dir)
    if kind != "web" and source_file_hash:
        result["source_file_hash"] = source_file_hash
    if args.title:
        result["title"] = args.title
    result["id"] = temp_doc_id; result["tags"] = tags
    doc = finalize_document(result)
    skip_content_hash_dedupe = doc.get("status") == "blocked" and dedupe_cfg.get("blocked_skip_content_hash", True)
    duplicate_warning = None
    if not args.force and not skip_content_hash_dedupe:
        existing_hash = find_by_content_hash(doc.get("content_hash"))
        if existing_hash:
            if kind == "web":
                if dedupe_cfg.get("web_content_hash_strict", True):
                    print("Skipped: duplicate web content hash"); print(f"id: {existing_hash['id']}"); print(f"title: {existing_hash['title']}"); print(f"note: {existing_hash['note_path']}"); return
            else:
                if dedupe_cfg.get("file_content_hash_strict", False):
                    print("Skipped: duplicate file content hash"); print(f"id: {existing_hash['id']}"); print(f"title: {existing_hash['title']}"); print(f"note: {existing_hash['note_path']}"); return
                elif dedupe_cfg.get("warn_on_file_content_hash_duplicate", True):
                    print("Warning: duplicate file content hash found")
                    duplicate_warning = {"type": "content_hash_duplicate", "existing_id": existing_hash["id"], "existing_title": existing_hash.get("title"), "existing_note": existing_hash.get("note_path"), "reason": "file_content_hash_matched_but_not_strict"}
    elif skip_content_hash_dedupe:
        print("Info: skipped content_hash dedupe because status=blocked")
    if duplicate_warning:
        doc["duplicate_warning"] = duplicate_warning
    if skip_content_hash_dedupe:
        doc["dedupe_skipped"] = {"content_hash": True, "reason": "status_blocked"}
    paths = build_storage_paths(doc["id"], doc.get("title")); note_path = paths["note_path"]; meta_path = paths["meta_path"]
    progress("writing_markdown", {"note_path": str(note_path)})
    write_text(note_path, render_markdown(doc))
    extra_meta = {k: v for k, v in result.items() if k not in doc}
    meta = {k: v for k, v in doc.items() if k not in ("content_md",)}
    meta.update(extra_meta)
    if duplicate_warning:
        meta["duplicate_warning"] = duplicate_warning
    if skip_content_hash_dedupe:
        meta["dedupe_skipped"] = {"content_hash": True, "reason": "status_blocked"}
    meta["note_path"] = str(note_path); meta["meta_path"] = str(meta_path)
    write_json(meta_path, meta)
    doc["note_path"] = str(note_path); doc["meta_path"] = str(meta_path)
    upsert_document(doc)
    progress("ingest_done", {"id": doc["id"], "type": doc["type"], "note": str(note_path), "meta": str(meta_path)})
    print("Done."); print(f"id: {doc['id']}"); print(f"type: {doc['type']}"); print(f"note: {note_path}"); print(f"meta: {meta_path}")


if __name__ == "__main__":
    main()
