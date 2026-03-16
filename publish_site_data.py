import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def run_command(cmd, cwd=None, check=True):
    """运行命令并返回结果（Windows 下强制 UTF-8 解码，避免 gbk 崩溃）"""
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=check,
            shell=False,
        )
        return result
    except subprocess.CalledProcessError as e:
        pretty = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        print(f"[!] 命令执行失败: {pretty}")
        print(f"    stderr: {e.stderr}")
        raise


def main():
    parser = argparse.ArgumentParser(
        description="发布 site-data 到 collector-site 并推送到 GitHub"
    )
    parser.add_argument(
        "--site-dir",
        default=r"D:\openclaw\workspaces\think-tank\collector-site",
        help="collector-site 项目目录"
    )
    parser.add_argument(
        "--message",
        default="update site data",
        help="Git commit 消息"
    )
    parser.add_argument(
        "--skip-export",
        action="store_true",
        help="跳过执行 export_site_data.py"
    )
    parser.add_argument(
        "--skip-push",
        action="store_true",
        help="只同步和 commit，不 push"
    )

    args = parser.parse_args()

    # 路径设置
    project_root = Path(__file__).parent
    site_data_dir = project_root / "site-data"
    site_dir = Path(args.site_dir)
    site_data_target = site_dir / "data"

    print("[*] 开始发布流程...")
    print(f"    源目录: {site_data_dir}")
    print(f"    目标目录: {site_data_target}")

    # 步骤 1: 导出数据
    if not args.skip_export:
        print("\n[1/5] 导出 site data...")
        try:
            result = run_command(
                [sys.executable, "export_site_data.py"],
                cwd=project_root
            )
            print("    导出完成")
        except subprocess.CalledProcessError:
            print("[!] 导出失败")
            sys.exit(1)
    else:
        print("\n[1/5] 跳过导出 (--skip-export)")

    # 检查源目录
    if not site_data_dir.exists():
        print(f"[!] 错误: 源目录不存在: {site_data_dir}")
        sys.exit(1)

    # 检查目标目录
    if not site_dir.exists():
        print(f"[!] 错误: collector-site 目录不存在: {site_dir}")
        sys.exit(1)

    if not (site_dir / ".git").exists():
        print(f"[!] 错误: {site_dir} 不是 Git 仓库")
        sys.exit(1)

    # 步骤 2: 同步数据
    print("\n[2/5] 同步数据到 collector-site/data...")
    try:
        # 删除旧数据
        if site_data_target.exists():
            shutil.rmtree(site_data_target)
            print("    已删除旧数据")

        # 复制新数据
        shutil.copytree(site_data_dir, site_data_target)
        print("    数据同步完成")

        # 统计文件
        json_files = list(site_data_target.rglob("*.json"))
        print(f"    同步了 {len(json_files)} 个 JSON 文件")

    except Exception as e:
        print(f"[!] 同步失败: {e}")
        sys.exit(1)

    # 步骤 3: Git add
    print("\n[3/5] git add data...")
    try:
        run_command(["git", "add", "data"], cwd=site_dir)
        print("    git add 完成")
    except subprocess.CalledProcessError:
        print("[!] git add 失败")
        sys.exit(1)

    # 步骤 4: Git commit
    print("\n[4/5] git commit...")
    try:
        result = run_command(
            ["git", "commit", "-m", args.message],
            cwd=site_dir,
            check=False
        )

        if result.returncode == 0:
            print(f"    提交成功: {args.message}")
        elif "nothing to commit" in result.stdout or "nothing to commit" in result.stderr:
            print("    没有变更需要提交")
            print("\n[*] 完成: 数据已是最新，无需推送")
            return
        else:
            print(f"[!] git commit 失败")
            print(f"    stdout: {result.stdout}")
            print(f"    stderr: {result.stderr}")
            sys.exit(1)

    except Exception as e:
        print(f"[!] git commit 异常: {e}")
        sys.exit(1)

    # 步骤 5: Git push
    if not args.skip_push:
        print("\n[5/5] git push...")
        try:
            result = run_command(["git", "push"], cwd=site_dir)
            print("    推送成功")
            print(f"\n[+] 完成: site data 已成功发布")
            print(f"    Vercel 将自动部署更新")
        except subprocess.CalledProcessError as e:
            print("[!] git push 失败")
            print(f"    stderr: {e.stderr}")
            sys.exit(1)
    else:
        print("\n[5/5] 跳过 push (--skip-push)")
        print(f"\n[+] 完成: 数据已同步并提交，但未推送")


if __name__ == "__main__":
    main()
