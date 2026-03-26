"""
extract_baidu_video.py — 百度视频 URL 提取 CLI

用法：
  python extract_baidu_video.py <URL> [选项]

选项：
  --headless            无头模式运行浏览器（默认：有头）
  --timeout <秒>        总超时秒数（默认：15）
  --no-debug            失败时不保存调试工件
  --debug-dir <路径>    调试工件根目录（默认：debug/）
  --json-only           只输出 JSON，不打印其他日志

退出码：
  0  成功提取到视频地址
  2  提取失败（已输出失败 JSON）
  1  参数错误

也可作为模块导入：
  from extract_baidu_video import extract_baidu_video
  result = extract_baidu_video("https://mbd.baidu.com/...")
"""

import argparse
import io
import json
import sys
from pathlib import Path

# Windows GBK 终端下强制 UTF-8 输出
if sys.stdout.encoding and sys.stdout.encoding.lower() in ("gbk", "gb2312", "cp936"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# 确保项目根目录在 sys.path（兼容直接运行和模块导入）
_here = Path(__file__).resolve().parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from lib.baidu_video_extract import is_baidu_video_url, run_extraction


def extract_baidu_video(
    url: str,
    headless: bool = True,
    total_timeout: int = 15,
    save_debug_on_fail: bool = True,
    debug_base: str = "debug",
) -> dict:
    """
    可编程调用接口。
    返回结构化 dict，格式与 CLI 输出一致。
    """
    return run_extraction(
        url=url,
        headless=headless,
        total_timeout=total_timeout,
        save_debug_on_fail=save_debug_on_fail,
        debug_base=debug_base,
    )


def main():
    parser = argparse.ArgumentParser(
        description="从百度视频分享页提取真实视频地址，输出结构化 JSON。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("url", help="百度视频分享页 URL")
    parser.add_argument(
        "--headless", action="store_true", default=False,
        help="无头模式运行浏览器（默认：有头）",
    )
    parser.add_argument(
        "--timeout", type=int, default=15, metavar="秒",
        help="单次提取总超时秒数（默认：15）",
    )
    parser.add_argument(
        "--no-debug", action="store_true", default=False,
        help="失败时不保存调试工件",
    )
    parser.add_argument(
        "--debug-dir", default="debug", metavar="路径",
        help="调试工件根目录（默认：debug/）",
    )
    parser.add_argument(
        "--json-only", action="store_true", default=False,
        help="只输出 JSON，不打印进度日志",
    )
    args = parser.parse_args()

    if not is_baidu_video_url(args.url):
        error = {
            "ok": False,
            "reason": "not_a_baidu_url",
            "page_url": args.url,
            "canonical_url": args.url,
            "step": "init",
            "debug_dir": None,
        }
        print(json.dumps(error, ensure_ascii=False, indent=2))
        raise SystemExit(1)

    if not args.json_only:
        print(f"[extract] URL: {args.url}")
        print(f"[extract] timeout={args.timeout}s  headless={args.headless}")

    result = run_extraction(
        url=args.url,
        headless=args.headless,
        total_timeout=args.timeout,
        save_debug_on_fail=not args.no_debug,
        debug_base=args.debug_dir,
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))

    if not result.get("ok"):
        if not args.json_only and result.get("debug_dir"):
            print(f"[extract] 调试工件已保存至：{result['debug_dir']}")
        raise SystemExit(2)

    if not args.json_only:
        print(f"[extract] 成功：{result['video_url']}")


if __name__ == "__main__":
    main()
