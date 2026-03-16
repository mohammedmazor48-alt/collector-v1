from pathlib import Path

from pdf2image import convert_from_path

from .utils import ensure_dir, load_config, ocr_image_tesseract


def render_page_markdown(page_num: int, text: str) -> str:
    if not text.strip():
        return f"## 第 {page_num} 页\n\n（OCR 未识别到文本）"
    return f"## 第 {page_num} 页\n\n{text.strip()}"


def ocr_pdf_to_markdown(pdf_path: str, output_dir: Path, dpi: int = 200, lang: str = "chi_sim+eng", max_pages: int = 20):
    ensure_dir(output_dir)
    cfg = load_config()
    poppler_path = cfg.get("tools", {}).get("pdftoppm")
    poppler_bin = str(Path(poppler_path).parent) if poppler_path and Path(poppler_path).exists() else None
    images = convert_from_path(pdf_path, dpi=dpi, poppler_path=poppler_bin)
    page_markdowns = []
    page_texts = []
    saved_images = []
    for idx, image in enumerate(images[:max_pages], start=1):
        img_path = output_dir / f"page-{idx:04d}.png"
        image.save(img_path, "PNG")
        saved_images.append(str(img_path))
        text = ocr_image_tesseract(img_path, lang=lang)
        page_markdowns.append(render_page_markdown(idx, text))
        if text.strip():
            page_texts.append(text.strip())
    return {"content_md": "\n\n".join(page_markdowns), "content_text": "\n\n".join(page_texts), "ocr_page_images": saved_images, "ocr_pages_processed": min(len(images), max_pages), "ocr_total_pages": len(images)}
