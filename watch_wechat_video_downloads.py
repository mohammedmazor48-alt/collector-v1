"""
watch_wechat_video_downloads.py

监听微信视频下载目录，自动发现新视频文件并调用 ingest.py 入库。
适用环境：Windows 本机，稳定优先。
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
DEFAULT_WATCH_DIR = Path(r"D:\Downloads\wechatvideos")
DEFAULT_STATE_FILE = PROJECT_ROOT / "knowledge-vault" / "logs" / "watch-wechat-video-state.json"
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm"}
TZ_SHANGHAI = timezone(timedelta(hours=8))


def log(tag: str, msg: str):
    ts = datetime.now(TZ_SHANGHAI).strftime("%H:%M:%S")
    print(f"[{ts}] [{tag}] {msg}", flush=True)


def normalize_path(path: Path) -> str:
    return str(path.resolve())


def load_state(state_file: Path) -> dict:
    if not state_file.exists():
        return {"processed": []}
    try:
        with open(state_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"processed": []}
        processed = data.get("processed", [])
        if not isinstance(processed, list):
            processed = []
        return {"processed": processed}
    except Exception as e:
        log("warn", f"状态文件读取失败，重置为空：{e}")
        return {"processed": []}


def save_state(state_file: Path, state: dict):
    state_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_file.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    tmp.replace(state_file)


def file_signature(filepath: Path) -> dict:
    stat = filepath.stat()
    return {
        "path": normalize_path(filepath),
        "size": stat.st_size,
        "mtime": stat.st_mtime,
    }


def is_already_processed(state: dict, filepath: Path) -> bool:
    try:
        current = file_signature(filepath)
    except FileNotFoundError:
        return True
    except Exception:
        current = {"path": normalize_path(filepath), "size": None, "mtime": None}

    for entry in state.get("processed", []):
        if entry.get("path") != current["path"]:
            continue
        saved_size = entry.get("size")
        saved_mtime = entry.get("mtime")
        if saved_size == current["size"] and saved_mtime == current["mtime"]:
            return True
    return False


def wait_for_stable(filepath: Path, check_seconds: float, rounds: int) -> bool:
    prev_size = None
    stable_count = 0
    while stable_count < rounds:
        try:
            curr_size = filepath.stat().st_size
        except FileNotFoundError:
            log("warn", f"文件消失：{filepath.name}")
            return False
        except Exception as e:
            log("warn", f"检查文件大小出错：{e}")
            return False

        if curr_size <= 0:
            stable_count = 0
            log("wait", f"文件大小仍为 0，继续等待：{filepath.name}")
        elif prev_size is not None and curr_size == prev_size:
            stable_count += 1
            log("wait", f"稳定检查 {stable_count}/{rounds}：{filepath.name}（{curr_size:,} bytes）")
        else:
            stable_count = 0
            log("wait", f"file still growing: {filepath.name}（{curr_size:,} bytes）")

        prev_size = curr_size
        time.sleep(check_seconds)

    return True


def scan_candidates(watch_dir: Path) -> list[Path]:
    candidates = []
    try:
        for item in watch_dir.iterdir():
            if item.is_file() and item.suffix.lower() in VIDEO_EXTS:
                candidates.append(item)
    except Exception as e:
        log("error", f"扫描目录失败：{e}")
    return sorted(candidates, key=lambda p: p.stat().st_mtime)


def run_command(cmd: list[str], stage: str, cwd: Path | None = None) -> bool:
    log(stage, f"命令: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, cwd=str(cwd or PROJECT_ROOT), check=False)
        if result.returncode == 0:
            log(stage, "done")
            return True
        log("error", f"{stage} 返回非零退出码 {result.returncode}")
        return False
    except Exception as e:
        log("error", f"{stage} 执行失败：{e}")
        return False


def run_ingest(video_path: Path, tags: str, python_exe: str) -> bool:
    log("ingest", f"start: {video_path.name}")
    return run_command(
        [python_exe, str(PROJECT_ROOT / "ingest.py"), str(video_path), "--tags", tags],
        stage="ingest",
        cwd=PROJECT_ROOT,
    )


def run_export(python_exe: str) -> bool:
    export_script = PROJECT_ROOT / "export_site_data.py"
    if not export_script.exists():
        log("error", "export_site_data.py 不存在，跳过导出")
        return False
    log("export", "start")
    return run_command([python_exe, str(export_script)], stage="export", cwd=PROJECT_ROOT)


def run_publish(python_exe: str, skip_export: bool = True) -> bool:
    publish_script = PROJECT_ROOT / "publish_site_data.py"
    if not publish_script.exists():
        log("error", "publish_site_data.py 不存在，请检查路径或去掉 --publish-site 参数")
        return False
    log("publish", "start")
    cmd = [python_exe, str(publish_script)]
    if skip_export:
        cmd.append("--skip-export")
    return run_command(cmd, stage="publish", cwd=PROJECT_ROOT)


def mark_processed(state: dict, video_path: Path):
    signature = file_signature(video_path)
    entry = {
        **signature,
        "processed_at": datetime.now(TZ_SHANGHAI).isoformat(),
    }
    state.setdefault("processed", []).append(entry)


def do_one_scan(
    watch_dir: Path,
    state: dict,
    state_file: Path,
    check_seconds: float,
    stable_rounds: int,
    tags: str,
    do_export: bool,
    do_publish: bool,
    python_exe: str,
):
    candidates = scan_candidates(watch_dir)
    log("scan", f"found {len(candidates)} candidate files")

    new_files = []
    for candidate in candidates:
        if is_already_processed(state, candidate):
            log("skip", f"already processed: {candidate.name}")
        else:
            new_files.append(candidate)

    for video_path in new_files:
        log("found", f"new file: {video_path.name}")
        if not wait_for_stable(video_path, check_seconds, stable_rounds):
            log("warn", f"文件未稳定或消失，跳过：{video_path.name}")
            continue

        log("ready", f"stable file detected: {video_path.name}")
        if not run_ingest(video_path, tags, python_exe):
            log("error", f"ingest 失败，不标记为已处理，下次重试：{video_path.name}")
            continue

        mark_processed(state, video_path)
        save_state(state_file, state)

        if do_export:
            export_ok = run_export(python_exe)
            if not export_ok:
                log("warn", "export 失败，但 ingest 已成功")

        if do_publish:
            publish_ok = run_publish(python_exe, skip_export=do_export)
            if not publish_ok:
                log("warn", "publish 失败，但 ingest 已成功")



def main():
    parser = argparse.ArgumentParser(
        description="监听微信视频下载目录，自动 ingest 新视频文件",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--watch-dir",
        default=str(DEFAULT_WATCH_DIR),
        help="监听目录（微信视频下载落地目录）",
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=5.0,
        help="轮询间隔（秒）",
    )
    parser.add_argument(
        "--stable-check-seconds",
        type=float,
        default=2.0,
        help="文件稳定检查间隔（秒）",
    )
    parser.add_argument(
        "--stable-rounds",
        type=int,
        default=3,
        help="连续多少轮文件大小不变视为稳定",
    )
    parser.add_argument(
        "--tags",
        default="微信视频号,视频,转写",
        help="ingest 时附加的标签（逗号分隔）",
    )
    parser.add_argument(
        "--export-site",
        action="store_true",
        help="ingest 成功后自动执行 export_site_data.py",
    )
    parser.add_argument(
        "--publish-site",
        action="store_true",
        help="ingest 成功后自动执行 publish_site_data.py（隐含 --export-site）",
    )
    parser.add_argument(
        "--state-file",
        default=str(DEFAULT_STATE_FILE),
        help="已处理文件状态记录路径",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="只扫描一次后退出（用于测试）",
    )
    args = parser.parse_args()

    watch_dir = Path(args.watch_dir)
    watch_dir.mkdir(parents=True, exist_ok=True)
    if not watch_dir.is_dir():
        print(f"错误：指定路径不是目录：{watch_dir}", file=sys.stderr)
        sys.exit(1)

    state_file = Path(args.state_file)
    if not state_file.is_absolute():
        state_file = PROJECT_ROOT / state_file

    do_export = args.export_site or args.publish_site
    do_publish = args.publish_site

    if do_publish and not (PROJECT_ROOT / "publish_site_data.py").exists():
        print("错误：指定了 --publish-site 但 publish_site_data.py 不存在", file=sys.stderr)
        sys.exit(1)

    python_exe = sys.executable

    print("=" * 60)
    print("微信视频下载监听器 V1")
    print("=" * 60)
    print(f"  监听目录     : {watch_dir}")
    print(f"  轮询间隔     : {args.poll_seconds}s")
    print(f"  稳定检查间隔 : {args.stable_check_seconds}s × {args.stable_rounds} 轮")
    print(f"  默认标签     : {args.tags}")
    print(f"  自动导出     : {'是' if do_export else '否'}")
    print(f"  自动发布     : {'是' if do_publish else '否'}")
    print(f"  状态文件     : {state_file}")
    print(f"  单次模式     : {'是' if args.once else '否'}")
    print(f"  Python       : {python_exe}")
    print("=" * 60)
    print("按 Ctrl+C 优雅退出", flush=True)

    state = load_state(state_file)

    try:
        while True:
            do_one_scan(
                watch_dir=watch_dir,
                state=state,
                state_file=state_file,
                check_seconds=args.stable_check_seconds,
                stable_rounds=args.stable_rounds,
                tags=args.tags,
                do_export=do_export,
                do_publish=do_publish,
                python_exe=python_exe,
            )

            if args.once:
                log("done", "单次扫描完成，退出")
                break

            log("sleep", f"等待 {args.poll_seconds}s 后下一轮扫描...")
            time.sleep(args.poll_seconds)

    except KeyboardInterrupt:
        print("\n[Ctrl+C] 收到退出信号，已安全退出。", flush=True)


if __name__ == "__main__":
    main()
