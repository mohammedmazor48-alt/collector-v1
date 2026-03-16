"""
download_from_feishu_rpa.py

飞书 RPA 下载脚本 V1
从飞书桌面端聊天窗口中自动下载视频文件到固定目录。
不负责转录，转录由 watch_wechat_video_downloads.py 接管。

使用前提：
1. 手动打开飞书桌面端
2. 手动进入目标聊天窗口
3. 让包含视频文件的消息处于当前可见区域
4. 运行本脚本
"""

import argparse
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ_SHANGHAI = timezone(timedelta(hours=8))


def log(tag: str, msg: str):
    ts = datetime.now(TZ_SHANGHAI).strftime("%H:%M:%S")
    print(f"[{ts}] [{tag}] {msg}", flush=True)


def get_dir_snapshot(directory: Path) -> set:
    """获取目录当前所有视频文件快照。"""
    VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
    try:
        return {
            f for f in directory.iterdir()
            if f.is_file() and f.suffix.lower() in VIDEO_EXTS
        }
    except Exception:
        return set()


def wait_for_new_file(directory: Path, before: set, timeout: int) -> Path | None:
    """等待目录中出现新视频文件，返回新文件路径或 None。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        after = get_dir_snapshot(directory)
        new_files = after - before
        if new_files:
            # 等文件大小稳定
            new_file = sorted(new_files, key=lambda f: f.stat().st_mtime)[-1]
            log("wait", f"detected new file: {new_file.name}")
            prev_size = -1
            stable = 0
            while stable < 3:
                try:
                    size = new_file.stat().st_size
                except FileNotFoundError:
                    break
                if size == prev_size and size > 0:
                    stable += 1
                else:
                    stable = 0
                prev_size = size
                time.sleep(2)
            return new_file
        time.sleep(1)
    return None


def find_feishu_window():
    """查找飞书主窗口。"""
    try:
        import pywinauto
        app = pywinauto.Application(backend="uia").connect(title_re=".*飞书.*", timeout=5)
        win = app.top_window()
        return win
    except Exception:
        pass
    try:
        import pywinauto
        app = pywinauto.Application(backend="uia").connect(title_re=".*Lark.*", timeout=5)
        win = app.top_window()
        return win
    except Exception:
        pass
    return None


def activate_feishu(wait_seconds: float, dry_run: bool):
    """激活飞书窗口。"""
    import pyautogui

    log("window", "searching for Feishu/Lark window...")

    win = find_feishu_window()
    if win:
        try:
            win.set_focus()
            log("window", "Feishu window activated via pywinauto")
            time.sleep(wait_seconds)
            return True
        except Exception as e:
            log("warn", f"pywinauto set_focus failed: {e}, trying pyautogui fallback")

    # 兜底：用 Alt+Tab 切换到飞书（用户需要确保飞书在任务栏）
    log("window", "trying to find Feishu in taskbar via pyautogui...")
    if dry_run:
        log("dry-run", "would activate Feishu window")
        return True

    # 尝试通过任务栏图标激活
    import pygetwindow as gw
    wins = gw.getWindowsWithTitle("飞书") + gw.getWindowsWithTitle("Lark")
    if wins:
        try:
            wins[0].activate()
            log("window", f"activated: {wins[0].title}")
            time.sleep(wait_seconds)
            return True
        except Exception as e:
            log("warn", f"pygetwindow activate failed: {e}")

    log("error", "cannot find Feishu window. Please open Feishu manually and try again.")
    return False


def enter_chat(chat_name: str, wait_seconds: float, dry_run: bool) -> bool:
    """搜索并进入指定聊天（可选功能）。"""
    import pyautogui

    log("chat", f"searching for chat: {chat_name}")
    if dry_run:
        log("dry-run", f"would search and enter chat: {chat_name}")
        return True

    # Ctrl+K 打开飞书搜索
    pyautogui.hotkey("ctrl", "k")
    time.sleep(wait_seconds)
    pyautogui.typewrite(chat_name, interval=0.05)
    time.sleep(wait_seconds)
    pyautogui.press("enter")
    time.sleep(wait_seconds)
    log("chat", f"entered chat: {chat_name}")
    return True


def trigger_download(save_dir: Path, wait_seconds: float, dry_run: bool) -> bool:
    """
    尝试触发飞书中视频文件的下载/另存为。

    策略：
    1. 先尝试 Ctrl+S（部分版本支持）
    2. 如果弹出另存为对话框，输入目标路径并确认
    """
    import pyautogui

    log("action", "trying to trigger download...")

    if dry_run:
        log("dry-run", f"would trigger download and save to: {save_dir}")
        return True

    # 策略1：尝试右键菜单 -> 另存为
    # 先移动鼠标到屏幕中央（消息区域大概位置），右键
    screen_w, screen_h = pyautogui.size()
    cx, cy = screen_w // 2, screen_h // 2

    log("action", f"right-clicking at screen center ({cx}, {cy})")
    pyautogui.rightClick(cx, cy)
    time.sleep(wait_seconds)

    # 截图检查右键菜单是否出现（简单等待）
    time.sleep(0.5)

    # 尝试按下"另存为"快捷键 A（飞书右键菜单通常有另存为选项）
    # 先尝试直接按 S 触发另存为
    pyautogui.press("escape")  # 先关掉右键菜单
    time.sleep(0.3)

    # 策略2：Ctrl+Shift+S 或 Ctrl+S
    log("action", "trying Ctrl+S...")
    pyautogui.hotkey("ctrl", "s")
    time.sleep(wait_seconds * 2)

    # 检查是否弹出了另存为对话框
    if handle_save_dialog(save_dir, wait_seconds):
        return True

    # 策略3：再次右键，寻找"另存为"文字菜单项
    log("action", "trying right-click context menu again...")
    pyautogui.rightClick(cx, cy)
    time.sleep(wait_seconds)

    # 尝试用键盘导航菜单（按方向键找到另存为）
    # 飞书右键菜单"另存为"通常在靠前位置
    for _ in range(8):
        pyautogui.press("down")
        time.sleep(0.15)
        # 每次按下后检查是否弹出了保存对话框
        if handle_save_dialog(save_dir, wait_seconds, quick_check=True):
            return True
        pyautogui.press("enter")
        time.sleep(wait_seconds)
        if handle_save_dialog(save_dir, wait_seconds, quick_check=True):
            return True

    log("error", "could not trigger download automatically")
    log("error", "manual fallback: right-click the video in Feishu -> save as -> choose D:\\Downloads\\wechatvideos")
    return False


def handle_save_dialog(save_dir: Path, wait_seconds: float, quick_check: bool = False) -> bool:
    """
    处理 Windows 另存为对话框。
    输入目标路径并确认保存。
    """
    import pyautogui

    # 检查是否有另存为窗口
    try:
        import pywinauto
        # 查找常见的另存为对话框标题
        for title in ["另存为", "Save As", "保存", "Save"]:
            try:
                dlg = pywinauto.Application(backend="uia").connect(
                    title_re=f".*{title}.*", timeout=2 if not quick_check else 0.5
                )
                win = dlg.top_window()
                log("save", f"found save dialog: {title}")

                # 在文件名输入框输入完整路径
                # 先用 Ctrl+L 或直接在地址栏输入路径
                pyautogui.hotkey("ctrl", "l")
                time.sleep(0.3)
                pyautogui.hotkey("ctrl", "a")
                pyautogui.typewrite(str(save_dir), interval=0.03)
                pyautogui.press("enter")
                time.sleep(wait_seconds)

                # 确认保存（按回车或点保存按钮）
                pyautogui.press("enter")
                time.sleep(wait_seconds)
                log("save", f"saving to: {save_dir}")
                return True
            except Exception:
                continue
    except Exception:
        pass

    if quick_check:
        return False

    # 兜底：直接用 pyautogui 操作当前焦点窗口
    # 假设另存为对话框已经打开，直接输入路径
    try:
        # Alt+D 聚焦地址栏（Windows 文件对话框通用）
        pyautogui.hotkey("alt", "d")
        time.sleep(0.3)
        pyautogui.hotkey("ctrl", "a")
        pyautogui.typewrite(str(save_dir), interval=0.03)
        pyautogui.press("enter")
        time.sleep(wait_seconds)
        pyautogui.press("enter")
        time.sleep(wait_seconds)
        return True
    except Exception as e:
        log("warn", f"save dialog handling failed: {e}")
        return False


def run(args):
    save_dir = Path(args.save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)

    log("start", "Feishu RPA download started")
    log("start", f"save directory: {save_dir}")
    if args.dry_run:
        log("start", "DRY RUN mode - no actual clicks will be performed")

    # 记录下载前的文件快照
    before = get_dir_snapshot(save_dir)
    log("start", f"current files in save dir: {len(before)}")

    # 1. 激活飞书窗口
    if not activate_feishu(args.wait_seconds, args.dry_run):
        sys.exit(1)

    # 2. 可选：进入指定聊天
    if args.chat_name:
        if not enter_chat(args.chat_name, args.wait_seconds, args.dry_run):
            log("warn", "failed to enter chat, continuing anyway...")

    # 3. 触发下载
    if not trigger_download(save_dir, args.wait_seconds, args.dry_run):
        log("error", "download trigger failed")
        log("error", "please manually: right-click video in Feishu -> save as -> D:\\Downloads\\wechatvideos")
        sys.exit(1)

    if args.dry_run:
        log("dry-run", "dry run complete, no files were downloaded")
        return

    # 4. 等待新文件出现
    log("wait", f"waiting for new file in {save_dir} (timeout: {args.download_timeout}s)...")
    new_file = wait_for_new_file(save_dir, before, args.download_timeout)

    if new_file:
        log("done", f"downloaded: {new_file}")
        log("done", "watcher (watch_wechat_video_downloads.py) will handle transcription")
    else:
        log("error", f"no new file appeared in {save_dir} within {args.download_timeout}s")
        log("error", "manual fallback: save the video manually to D:\\Downloads\\wechatvideos")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="飞书 RPA 下载脚本 V1 - 从飞书聊天窗口下载视频到固定目录"
    )
    parser.add_argument(
        "--save-dir",
        default=r"D:\Downloads\wechatvideos",
        help="视频保存目录 (default: D:\\Downloads\\wechatvideos)",
    )
    parser.add_argument(
        "--chat-name",
        default="",
        help="可选：自动搜索并进入该聊天名称",
    )
    parser.add_argument(
        "--wait-seconds",
        type=float,
        default=1.5,
        help="操作之间的等待时间（秒）(default: 1.5)",
    )
    parser.add_argument(
        "--download-timeout",
        type=int,
        default=120,
        help="等待文件出现的超时时间（秒）(default: 120)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="执行一次后退出",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印计划动作，不真正点击/保存",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("飞书 RPA 下载脚本 V1")
    print("=" * 60)
    print(f"  保存目录     : {args.save_dir}")
    print(f"  聊天名称     : {args.chat_name or '（手动定位）'}")
    print(f"  操作等待     : {args.wait_seconds}s")
    print(f"  下载超时     : {args.download_timeout}s")
    print(f"  Dry Run      : {'是' if args.dry_run else '否'}")
    print("=" * 60)
    print("使用前请确认：")
    print("  1. 飞书桌面端已打开")
    print("  2. 已进入目标聊天窗口")
    print("  3. 视频文件消息在当前屏幕可见")
    print("=" * 60)

    run(args)


if __name__ == "__main__":
    main()
