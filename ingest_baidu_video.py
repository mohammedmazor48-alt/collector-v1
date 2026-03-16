import subprocess
import sys


def main():
    args = [sys.executable, "ingest_video_page.py", *sys.argv[1:]]
    raise SystemExit(subprocess.call(args))


if __name__ == "__main__":
    main()
