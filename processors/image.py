from pathlib import Path

from .summarizer import render_summary_markdown, summarize_text
from .utils import copy_file, get_image_info, load_config, ocr_image_tesseract, render_image_ocr_markdown, sha256_file


def process_image(file_path: str, raw_dir: Path):
    src = Path(file_path)
    if not src.exists():
        raise FileNotFoundError(f"Image not found: {file_path}")
    cfg = load_config(); image_cfg = cfg.get("image", {}); processing_cfg = cfg.get("processing", {})
    raw_path = raw_dir / src.name; copy_file(src, raw_path)
    image_info = get_image_info(raw_path)
    lang = image_cfg.get("tesseract_lang", "chi_sim+eng")
    ocr_text = ocr_image_tesseract(raw_path, lang=lang)
    summary_data = summarize_text(ocr_text, content_type="image") if processing_cfg.get("summarize", True) and image_cfg.get("generate_summary", True) else {"summary": "", "bullets": [], "action_items": [], "keywords": []}
    summary_md = render_summary_markdown(summary_data)
    ocr_md = render_image_ocr_markdown(ocr_text)
    content_md = "\n".join([summary_md, "", "## 图片信息", "", f"- 文件格式：{image_info.get('format', '')}", f"- 尺寸：{image_info.get('width', 0)} x {image_info.get('height', 0)}", f"- 色彩模式：{image_info.get('mode', '')}", "", ocr_md])
    min_chars = image_cfg.get("min_text_chars_for_processed", 10)
    status = "processed" if len(ocr_text.strip()) >= min_chars else "partial"
    summary = summary_data.get("summary", "")
    if not ocr_text.strip():
        summary = "图片未识别到明显文字内容"
    elif not summary:
        summary = f"图片 OCR 提取文本 {len(ocr_text)} 字符"
    return {"type": "image", "source": str(src.resolve()), "source_type": "file", "title": src.stem, "summary": summary, "content_md": content_md, "content_text": ocr_text, "status": status, "raw_path": str(raw_path), "source_file_hash": sha256_file(src), "ocr_engine": image_cfg.get("ocr_engine", "tesseract"), "ocr_lang": lang, "image_info": image_info, "summary_data": summary_data}
