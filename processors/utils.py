import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import pytesseract
import yaml
from PIL import Image

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


def first_non_empty(*values):
    for v in values:
        if v is not None and v != "":
            return v
    return None


def now_iso():
    return datetime.now().astimezone().isoformat()


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def is_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def write_text(path: Path, content: str):
    ensure_dir(path.parent)
    path.write_text(content, encoding="utf-8")


def write_json(path: Path, data: dict):
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def copy_file(src: Path, dst: Path):
    ensure_dir(dst.parent)
    shutil.copy2(src, dst)


def md_to_text(md: str) -> str:
    if not md:
        return ""
    text = md
    text = re.sub(r"```[\s\S]*?```", "\n", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s{0,3}>\s?", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"(\*\*|__)(.*?)\1", r"\2", text)
    text = re.sub(r"(\*|_)(.*?)\1", r"\2", text)
    text = re.sub(r"^\s*([-*_]\s*){3,}$", "", text, flags=re.MULTILINE)
    lines = [line.strip() for line in text.splitlines()]
    cleaned = []
    blank = False
    for line in lines:
        if not line:
            if not blank:
                cleaned.append("")
            blank = True
        else:
            cleaned.append(line)
            blank = False
    return "\n".join(cleaned).strip()


def resolve_tool_path(name: str) -> str:
    cfg = load_config()
    tools_cfg = cfg.get("tools", {})
    configured = tools_cfg.get(name)
    if configured and Path(configured).exists():
        return str(Path(configured))
    return name


def run_cmd(cmd: list[str]):
    resolved_cmd = list(cmd)
    if resolved_cmd:
        resolved_cmd[0] = resolve_tool_path(resolved_cmd[0])
    result = subprocess.run(resolved_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(resolved_cmd)}\nstdout:\n{result.stdout}\n\nstderr:\n{result.stderr}")
    return result


def format_timestamp(seconds: float) -> str:
    total = int(seconds)
    hh = total // 3600
    mm = (total % 3600) // 60
    ss = total % 60
    return f"{hh:02d}:{mm:02d}:{ss:02d}"


def ffmpeg_extract_audio(src: Path, dst: Path):
    ensure_dir(dst.parent)
    run_cmd(["ffmpeg", "-y", "-i", str(src), "-vn", "-acodec", "libmp3lame", "-ar", "16000", "-ac", "1", str(dst)])


def ffmpeg_normalize_audio(src: Path, dst: Path):
    ensure_dir(dst.parent)
    run_cmd(["ffmpeg", "-y", "-i", str(src), "-ar", "16000", "-ac", "1", str(dst)])


def ocr_image_tesseract(image_path: Path, lang: str = "chi_sim+eng") -> str:
    tesseract_path = resolve_tool_path("tesseract")
    if tesseract_path and tesseract_path != "tesseract":
        pytesseract.pytesseract.tesseract_cmd = tesseract_path
    img = Image.open(image_path)
    text = pytesseract.image_to_string(img, lang=lang)
    return text.strip()


def get_image_info(image_path: Path) -> dict:
    with Image.open(image_path) as img:
        return {"format": img.format, "mode": img.mode, "width": img.width, "height": img.height}


def render_image_ocr_markdown(ocr_text: str) -> str:
    if not ocr_text.strip():
        return "## OCR 文本\n\n（未识别到文本）"
    return f"## OCR 文本\n\n{ocr_text.strip()}"
