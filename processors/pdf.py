from pathlib import Path

import fitz

from .pdf_ocr import ocr_pdf_to_markdown
from .summarizer import render_summary_markdown, summarize_text
from .utils import copy_file, load_config, sha256_file


def process_pdf(file_path: str, raw_dir: Path) -> dict:
    src = Path(file_path)
    if not src.exists():
        raise FileNotFoundError(f"PDF not found: {file_path}")
    cfg = load_config(); pdf_cfg = cfg.get("pdf", {}); image_cfg = cfg.get("image", {})
    raw_pdf_path = raw_dir / src.name; copy_file(src, raw_pdf_path)
    doc = fitz.open(file_path)
    title = src.stem
    metadata = doc.metadata or {}
    if metadata.get("title"):
        title = metadata["title"].strip() or title
    author = metadata.get("author")
    all_pages = []; all_text_parts = []
    for i, page in enumerate(doc):
        page_text = (page.get_text("text") or "").strip()
        if page_text:
            all_pages.append(f"## 第 {i + 1} 页\n\n{page_text}"); all_text_parts.append(page_text)
        else:
            all_pages.append(f"## 第 {i + 1} 页\n\n（本页未提取到文本，可能是扫描页）")
    doc.close()
    direct_md = "\n\n".join(all_pages); direct_text = "\n\n".join(all_text_parts)
    use_text_first = pdf_cfg.get("text_first", True); use_ocr_fallback = pdf_cfg.get("ocr_fallback", True); direct_text_min_chars = pdf_cfg.get("direct_text_min_chars", 80)
    if use_text_first and len(direct_text.strip()) >= direct_text_min_chars:
        summary_data = summarize_text(direct_text, content_type="pdf")
        content_md = "\n".join([render_summary_markdown(summary_data), "", direct_md])
        return {"type": "pdf", "source": str(src.resolve()), "source_type": "file", "title": title, "author": author, "summary": summary_data.get("summary", ""), "summary_data": summary_data, "content_md": content_md, "content_text": direct_text, "raw_path": str(raw_pdf_path), "source_file_hash": sha256_file(src), "status": "processed", "pdf_extract_mode": "direct"}
    if use_ocr_fallback:
        ocr_result = ocr_pdf_to_markdown(str(src), raw_dir / "ocr_pages", dpi=pdf_cfg.get("ocr_dpi", 200), lang=image_cfg.get("tesseract_lang", "chi_sim+eng"), max_pages=pdf_cfg.get("max_ocr_pages", 20))
        content_text = ocr_result["content_text"]
        summary_data = summarize_text(content_text, content_type="pdf")
        content_md = "\n".join([render_summary_markdown(summary_data), "", ocr_result["content_md"]])
        status = "processed" if content_text.strip() else "partial"
        return {"type": "pdf", "source": str(src.resolve()), "source_type": "file", "title": title, "author": author, "summary": summary_data.get("summary", ""), "summary_data": summary_data, "content_md": content_md, "content_text": content_text, "raw_path": str(raw_pdf_path), "source_file_hash": sha256_file(src), "status": status, "pdf_extract_mode": "ocr_fallback", "ocr_page_images": ocr_result.get("ocr_page_images", []), "ocr_pages_processed": ocr_result.get("ocr_pages_processed"), "ocr_total_pages": ocr_result.get("ocr_total_pages"), "direct_text_chars": len(direct_text)}
    return {"type": "pdf", "source": str(src.resolve()), "source_type": "file", "title": title, "author": author, "content_md": direct_md, "content_text": direct_text, "raw_path": str(raw_pdf_path), "source_file_hash": sha256_file(src), "status": "processed" if direct_text.strip() else "partial", "pdf_extract_mode": "direct_partial"}
