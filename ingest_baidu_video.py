"""
ingest_baidu_video.py — 百度视频一键入库

调用新版提取模块（lib/baidu_video_extract）完成：
  1. URL 规范化
  2. 三层提取策略（HTML → 页面对象 → 网络抓包）
  3. 失败自动输出 debug 工件
  4. 成功后转入 ingest_remote.py 下载/转录/入库

用法：
  python ingest_baidu_video.py <百度视频URL> [--tags TAG] [--title TITLE] [--force]
"""

import subprocess
import sys
from pathlib import Path

# 确保项目根目录在 sys.path
_here = Path(__file__).resolve().parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from lib.baidu_video_extract import is_baidu_video_url, run_extraction


def main():
    import argparse
    import io

    if sys.stdout.encoding and sys.stdout.encoding.lower() in ("gbk", "gb2312", "cp936"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="百度视频一键提取入库")
    parser.add_argument("url", help="百度视频分享页 URL")
    parser.add_argument("--tags", default="Baidu,视频,转写", help="逗号分隔的标签")
    parser.add_argument("--title", default="", help="覆盖标题")
    parser.add_argument("--force", action="store_true", help="强制重复导入")
    parser.add_argument("--headless", action="store_true", help="无头模式运行浏览器")
    parser.add_argument("--timeout", type=int, default=15, help="提取超时秒数")
    args = parser.parse_args()

    if not is_baidu_video_url(args.url):
        print(f"错误：不是有效的百度视频 URL：{args.url}")
        raise SystemExit(1)

    print(f"[baidu] 开始提取：{args.url}")
    result = run_extraction(
        url=args.url,
        headless=args.headless,
        total_timeout=args.timeout,
        save_debug_on_fail=True,
    )

    if not result.get("ok"):
        reason = result.get("reason", "unknown")
        debug_dir = result.get("debug_dir")
        print(f"[baidu] 提取失败：{reason}（step={result.get('step')}）")
        if debug_dir:
            print(f"[baidu] 调试工件：{debug_dir}")
        raise SystemExit(2)

    video_url = result["video_url"]
    title = args.title or result.get("title", "")
    print(f"[baidu] 提取成功：{video_url}")
    if title:
        print(f"[baidu] 标题：{title}")

    cmd = [sys.executable, "ingest_remote.py", video_url]
    if args.tags:
        cmd.extend(["--tags", args.tags])
    if title:
        cmd.extend(["--title", title])
    if args.force:
        cmd.append("--force")

    raise SystemExit(subprocess.call(cmd))


if __name__ == "__main__":
    main()
