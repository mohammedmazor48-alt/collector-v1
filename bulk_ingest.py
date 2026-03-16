import argparse
import subprocess
import sys
from pathlib import Path

SUPPORTED_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".pdf", ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".mp4", ".mkv", ".mov", ".avi", ".webm"}


def iter_files(root: Path, recursive: bool = True):
    items = root.rglob("*") if recursive else root.glob("*")
    for p in items:
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS:
            yield p


def run_ingest(file_path: Path, tags: str = "", force: bool = False):
    cmd = [sys.executable, "ingest.py", str(file_path)]
    if tags:
        cmd.extend(["--tags", tags])
    if force:
        cmd.append("--force")
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def main():
    parser = argparse.ArgumentParser(description="Bulk ingest files from a directory")
    parser.add_argument("directory")
    parser.add_argument("--tags", default="")
    parser.add_argument("--no-recursive", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    root = Path(args.directory)
    if not root.exists() or not root.is_dir():
        raise NotADirectoryError(f"Invalid directory: {root}")
    files = list(iter_files(root, recursive=not args.no_recursive))
    if args.limit > 0:
        files = files[:args.limit]
    if not files:
        print("No supported files found."); return
    print(f"Found {len(files)} files.")
    success = skipped = failed = 0
    for idx, file_path in enumerate(files, start=1):
        print("=" * 72); print(f"[{idx}/{len(files)}] Processing: {file_path}")
        result = run_ingest(file_path, tags=args.tags, force=args.force)
        stdout = result.stdout.strip(); stderr = result.stderr.strip()
        if result.returncode == 0:
            print(stdout)
            if "Skipped:" in stdout:
                skipped += 1
            else:
                success += 1
        else:
            failed += 1; print("FAILED")
            if stdout: print("stdout:\n" + stdout)
            if stderr: print("stderr:\n" + stderr)
    print("=" * 72); print("Bulk ingest finished."); print(f"success: {success}"); print(f"skipped: {skipped}"); print(f"failed: {failed}")


if __name__ == "__main__":
    main()
