import argparse
import json
import mimetypes
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from processors.db import init_db
from processors.utils import ensure_dir, load_config, now_iso, sha256_text


CONTENT_TYPE_EXT_MAP = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mp4": ".m4a",
    "audio/aac": ".aac",
    "audio/flac": ".flac",
    "audio/ogg": ".ogg",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/x-msvideo": ".avi",
    "video/x-matroska": ".mkv",
    "video/webm": ".webm",
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
    "text/html": ".html",
}

FILE_CONTENT_PREFIXES = (
    "audio/",
    "video/",
    "image/",
)


def get_video_page_config() -> dict:
    try:
        cfg = load_config() or {}
        return cfg.get("video_page") or {}
    except Exception:
        return {}


def get_config_str(key: str, default: str = "") -> str:
    cfg = get_video_page_config()
    value = cfg.get(key)
    if value is None:
        return default
    return str(value).strip()


def notify_event(event: str, payload: dict, notify_file: str = "", notify_webhook: str = ""):
    body = {
        "event": event,
        "time": now_iso(),
        **payload,
    }

    if notify_file:
        path = Path(notify_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")

    if notify_webhook:
        try:
            with httpx.Client(timeout=15, follow_redirects=True) as client:
                client.post(notify_webhook, json=body)
        except Exception as e:
            print(f"Webhook notify failed: {e}")


def guess_extension(url: str, content_type: str | None = None) -> str:
    if content_type:
        ct = content_type.split(";")[0].strip().lower()
        if ct in CONTENT_TYPE_EXT_MAP:
            return CONTENT_TYPE_EXT_MAP[ct]
    parsed = urlparse(url)
    ext = Path(parsed.path).suffix.lower()
    if ext:
        return ext
    guessed = mimetypes.guess_extension((content_type or "").split(";")[0].strip().lower()) if content_type else None
    return guessed or ".bin"


def guess_filename(url: str, content_type: str | None = None, override_name: str | None = None) -> str:
    if override_name:
        name = Path(override_name).name
        if Path(name).suffix:
            return name
        return name + guess_extension(url, content_type)

    parsed = urlparse(url)
    candidate = Path(parsed.path).name or "downloaded"
    if candidate and Path(candidate).suffix:
        return candidate
    return (candidate or "downloaded") + guess_extension(url, content_type)


def build_download_dir() -> Path:
    cfg = load_config()
    base_dir = Path(cfg["storage"]["base_dir"])
    return base_dir / "raw" / "remote_downloads"


def inspect_remote(url: str, timeout: int = 30) -> dict:
    headers = {"User-Agent": "Mozilla/5.0"}
    with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
        try:
            resp = client.head(url)
            if resp.status_code >= 400 or not resp.headers:
                raise RuntimeError("HEAD not usable")
        except Exception:
            resp = client.get(url, headers={**headers, "Range": "bytes=0-0"})
        final_url = str(resp.url)
        content_type = resp.headers.get("content-type", "")
        content_length = resp.headers.get("content-length", "")

    kind = classify_remote_kind(final_url, content_type)
    return {
        "source_url": url,
        "final_url": final_url,
        "content_type": content_type,
        "content_length": content_length,
        "kind": kind,
        "inspected_at": now_iso(),
    }


def classify_remote_kind(url: str, content_type: str | None = None) -> str:
    ct = (content_type or "").split(";")[0].strip().lower()
    ext = Path(urlparse(url).path).suffix.lower()

    if ct == "text/html":
        return "web"
    if ct == "application/pdf":
        return "file"
    if ct.startswith(FILE_CONTENT_PREFIXES):
        return "file"

    if ext in {".html", ".htm", ""}:
        if ct in {"", "application/octet-stream"}:
            return "unknown"
        return "web" if ct.startswith("text/") else "file"

    if ext in {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".mp4", ".mkv", ".mov", ".avi", ".webm"}:
        return "file"

    return "unknown"


def download_file(url: str, out_dir: Path, filename: str | None = None, retries: int = 3, timeout: int = 120, notify_file: str = "", notify_webhook: str = "") -> tuple[Path, dict]:
    ensure_dir(out_dir)
    headers = {"User-Agent": "Mozilla/5.0"}
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            notify_event(
                "downloading",
                {
                    "url": url,
                    "attempt": attempt,
                    "out_dir": str(out_dir),
                },
                notify_file,
                notify_webhook,
            )
            with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
                with client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    content_type = resp.headers.get("content-type", "")
                    final_url = str(resp.url)
                    resolved_name = guess_filename(final_url, content_type, filename)
                    out_path = out_dir / resolved_name

                    with open(out_path, "wb") as f:
                        for chunk in resp.iter_bytes():
                            if chunk:
                                f.write(chunk)

            meta = {
                "source_url": url,
                "final_url": final_url,
                "content_type": content_type,
                "downloaded_at": now_iso(),
                "filename": out_path.name,
                "attempt": attempt,
            }
            notify_event(
                "downloaded",
                {
                    "url": url,
                    "final_url": final_url,
                    "downloaded_path": str(out_path),
                    "filename": out_path.name,
                    "attempt": attempt,
                },
                notify_file,
                notify_webhook,
            )
            return out_path, meta
        except Exception as e:
            last_error = e
            if attempt < retries:
                wait_seconds = attempt * 2
                print(f"Download attempt {attempt} failed: {e}. Retrying in {wait_seconds}s...")
                notify_event(
                    "download_retry",
                    {
                        "url": url,
                        "attempt": attempt,
                        "error": str(e),
                        "wait_seconds": wait_seconds,
                    },
                    notify_file,
                    notify_webhook,
                )
                time.sleep(wait_seconds)
            else:
                break

    notify_event(
        "download_failed",
        {
            "url": url,
            "retries": retries,
            "error": str(last_error),
        },
        notify_file,
        notify_webhook,
    )
    raise RuntimeError(f"Failed to download after {retries} attempts: {last_error}")


def run_local_ingest(target: str, tags: str = "", title: str = "", force: bool = False, notify_file: str = "", notify_webhook: str = ""):
    cmd = [sys.executable, "ingest.py", str(target)]
    if tags:
        cmd.extend(["--tags", tags])
    if title:
        cmd.extend(["--title", title])
    if force:
        cmd.append("--force")
    if notify_file:
        cmd.extend(["--notify-file", notify_file])
    if notify_webhook:
        cmd.extend(["--notify-webhook", notify_webhook])

    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def save_json(path: Path, data: dict):
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Download a remote file or route a remote web URL into local ingest")
    parser.add_argument("url", help="Remote URL")
    parser.add_argument("--tags", default="", help="comma-separated tags")
    parser.add_argument("--title", default="", help="override title")
    parser.add_argument("--filename", default="", help="preferred local filename")
    parser.add_argument("--force", action="store_true", help="force import duplicates")
    parser.add_argument("--retries", type=int, default=3, help="download retry count")
    parser.add_argument("--timeout", type=int, default=120, help="download timeout in seconds")
    parser.add_argument("--inspect-only", action="store_true", help="inspect remote URL and print detected kind without ingesting")
    parser.add_argument("--notify-file", default="", help="write latest event JSON to a local file")
    parser.add_argument("--notify-webhook", default="", help="POST latest event JSON to a webhook URL")
    args = parser.parse_args()

    notify_file = args.notify_file or get_config_str("notify_file", "")
    notify_webhook = args.notify_webhook or get_config_str("notify_webhook", "")

    init_db()
    notify_event(
        "remote_start",
        {
            "url": args.url,
            "title": args.title,
            "tags": args.tags,
        },
        notify_file,
        notify_webhook,
    )

    info = inspect_remote(args.url, timeout=min(args.timeout, 30))
    print(f"Remote kind: {info['kind']}")
    print(f"Final URL: {info['final_url']}")
    print(f"Content-Type: {info['content_type']}")
    if info.get("content_length"):
        print(f"Content-Length: {info['content_length']}")

    notify_event(
        "remote_inspected",
        {
            "url": args.url,
            "kind": info["kind"],
            "final_url": info["final_url"],
            "content_type": info["content_type"],
            "content_length": info.get("content_length", ""),
        },
        notify_file,
        notify_webhook,
    )

    if args.inspect_only:
        return

    if info["kind"] == "web":
        print("Routing as web URL directly into ingest.py")
        notify_event(
            "local_ingest_start",
            {
                "url": args.url,
                "mode": "web_url",
                "target": args.url,
            },
            notify_file,
            notify_webhook,
        )
        result = run_local_ingest(args.url, tags=args.tags, title=args.title, force=args.force, notify_file=notify_file, notify_webhook=notify_webhook)
    else:
        download_dir = build_download_dir()
        url_hash = sha256_text(args.url).replace("sha256:", "")[:12]
        out_dir = download_dir / url_hash
        print(f"Downloading: {args.url}")
        downloaded_path, remote_meta = download_file(
            url=args.url,
            out_dir=out_dir,
            filename=args.filename or None,
            retries=args.retries,
            timeout=args.timeout,
            notify_file=notify_file,
            notify_webhook=notify_webhook,
        )
        remote_meta.update(info)
        print(f"Downloaded to: {downloaded_path}")
        save_json(out_dir / "download_meta.json", remote_meta)
        notify_event(
            "local_ingest_start",
            {
                "url": args.url,
                "mode": "downloaded_file",
                "target": str(downloaded_path),
                "title": args.title,
            },
            notify_file,
            notify_webhook,
        )
        result = run_local_ingest(str(downloaded_path), tags=args.tags, title=args.title, force=args.force, notify_file=notify_file, notify_webhook=notify_webhook)

    if result.returncode != 0:
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr)
        notify_event(
            "local_ingest_failed",
            {
                "url": args.url,
                "returncode": result.returncode,
                "stdout": (result.stdout or "")[-4000:],
                "stderr": (result.stderr or "")[-4000:],
            },
            notify_file,
            notify_webhook,
        )
        raise SystemExit(result.returncode)

    print(result.stdout.strip())
    notify_event(
        "local_ingest_done",
        {
            "url": args.url,
            "stdout": (result.stdout or "")[-4000:],
        },
        notify_file,
        notify_webhook,
    )


if __name__ == "__main__":
    main()
