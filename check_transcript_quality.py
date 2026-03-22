"""
check_transcript_quality.py

批量检查知识库笔记文件的质量，输出问题报告。
用法: python check_transcript_quality.py [--notes-dir path]
"""
import argparse
import sys
import io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def check_file(md_path: Path) -> dict:
    try:
        content = md_path.read_text(encoding="utf-8")
    except Exception as e:
        return {"file": md_path.name, "score": 0, "issues": [f"读取失败: {e}"], "passed": False}

    issues = []
    score = 100

    # 1. 乱码字符（真实编码损坏）
    replacement_count = content.count("\ufffd")
    if replacement_count > 0:
        issues.append(f"存在 {replacement_count} 个乱码字符 (\\ufffd)")
        score -= 40

    # 2. 内容是否为空
    # 去掉 YAML frontmatter 后的正文长度
    body = content
    if content.startswith("---"):
        end = content.find("\n---", 3)
        if end != -1:
            body = content[end + 4:]
    body = body.strip()
    if len(body) < 50:
        issues.append(f"正文内容过短（{len(body)} 字符）")
        score -= 30

    # 3. 是否有实际转录/正文内容（非纯元数据）
    # 去掉标题行后看是否有实质内容
    lines = [l for l in body.splitlines() if l.strip() and not l.startswith("#")]
    content_lines = [l for l in lines if not l.startswith("-") and not l.startswith("*")]
    if len(content_lines) < 3:
        issues.append("缺少实质性正文内容（非列表行 < 3 行）")
        score -= 20

    # 4. 冗余元数据区块（旧格式遗留）
    if "## 基本信息" in content:
        issues.append("包含旧格式 '## 基本信息' 区块（新入库文件不应有此区块）")
        score -= 5
    if "## 附注" in content:
        issues.append("包含旧格式 '## 附注' 区块")
        score -= 5

    # 5. 本地路径暴露在正文中
    if "D:\\" in body or "D:/" in body:
        issues.append("正文中包含本地文件路径")
        score -= 5

    score = max(0, score)
    return {
        "file": md_path.name,
        "score": score,
        "issues": issues,
        "passed": score >= 70,
        "body_len": len(body),
    }


def main():
    parser = argparse.ArgumentParser(description="批量检查笔记文件质量")
    parser.add_argument("--notes-dir", default="knowledge-vault/notes", help="笔记目录")
    parser.add_argument("--min-score", type=int, default=70, help="通过分数线")
    args = parser.parse_args()

    notes_dir = Path(args.notes_dir)
    if not notes_dir.is_absolute():
        notes_dir = Path(__file__).parent / notes_dir

    md_files = sorted(notes_dir.rglob("*.md"))
    if not md_files:
        print(f"未找到 Markdown 文件: {notes_dir}")
        return

    results = [check_file(f) for f in md_files]
    results.sort(key=lambda x: x["score"])

    print("=" * 65)
    print("笔记质量检查报告")
    print("=" * 65)

    for r in results:
        status = "✓" if r["passed"] else "✗"
        print(f"\n[{status}] {r['file'][:55]:55s} 得分: {r['score']}")
        if r.get("body_len") is not None:
            print(f"    正文长度: {r['body_len']} 字符")
        for issue in r["issues"]:
            print(f"    ! {issue}")

    passed = sum(1 for r in results if r["passed"])
    failed = len(results) - passed
    print(f"\n{'=' * 65}")
    print(f"共 {len(results)} 个文件  通过: {passed}  需关注: {failed}")


if __name__ == "__main__":
    main()
