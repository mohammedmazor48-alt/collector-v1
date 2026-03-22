import argparse
import json
import shutil
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict


# 项目根目录
PROJECT_ROOT = Path(__file__).parent


def load_config():
    """加载配置文件"""
    import yaml
    config_path = PROJECT_ROOT / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def collect_meta_files(base_dir: Path) -> list[Path]:
    """收集所有 meta JSON 文件"""
    meta_dir = base_dir / "meta"
    if not meta_dir.exists():
        return []
    return sorted(meta_dir.rglob("*.json"))


def load_meta(meta_path: Path) -> dict | None:
    """加载单个 meta 文件"""
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[!] 无法读取 meta 文件: {meta_path} - {e}")
        return None


def load_markdown(note_path: str | Path) -> tuple[str | None, bool]:
    """加载 Markdown 文件内容，返回 (内容, 是否缺失)"""
    try:
        path = Path(note_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if not path.exists():
            return None, True
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), False
    except Exception as e:
        print(f"[!] 无法读取 Markdown 文件: {note_path} - {e}")
        return None, True


def should_export(meta: dict, include_blocked: bool = False) -> bool:
    """判断是否应该导出该记录"""
    status = meta.get("status", "")

    if include_blocked:
        return True

    # 默认只导出 processed 或 partial
    return status in ("processed", "partial")


def build_index_record(meta: dict) -> dict:
    """构建 index.json 的单条记录（轻量级）"""
    doc_id = meta.get("id", "")
    return {
        "id": doc_id,
        "title": meta.get("title", ""),
        "type": meta.get("type", ""),
        "summary": meta.get("summary", ""),
        "tags": meta.get("tags", []),
        "status": meta.get("status", ""),
        "created_at": meta.get("created_at", ""),
        "updated_at": meta.get("updated_at", ""),
        "source": meta.get("source", ""),
        "detail_path": f"/docs/{doc_id}"
    }


def build_detail_record(meta: dict, markdown: str | None, markdown_missing: bool) -> dict:
    """构建 docs/<id>.json 的详情记录（完整）"""
    record = {
        "id": meta.get("id", ""),
        "title": meta.get("title", ""),
        "type": meta.get("type", ""),
        "summary": meta.get("summary", ""),
        "tags": meta.get("tags", []),
        "status": meta.get("status", ""),
        "source": meta.get("source", ""),
        "created_at": meta.get("created_at", ""),
        "updated_at": meta.get("updated_at", ""),
        "note_path": meta.get("note_path", ""),
        "meta_path": meta.get("meta_path", ""),
        "markdown": markdown,
        "content_html": meta.get("content_html"),
        "content_text": meta.get("content_text", ""),
        "summary_data": meta.get("summary_data"),
        "duration": meta.get("duration"),
        "language": meta.get("language", ""),
        "author": meta.get("author"),
        "published_at": meta.get("published_at"),
        "captured_at": meta.get("captured_at", "")
    }
    if markdown_missing:
        record["markdown_missing"] = True
    return record


def build_stats(index_records: list[dict]) -> dict:
    """构建统计信息"""
    by_type = defaultdict(int)
    for record in index_records:
        doc_type = record.get("type", "unknown")
        by_type[doc_type] += 1

    return {
        "total_docs": len(index_records),
        "by_type": dict(by_type),
        "updated_at": datetime.now(timezone.utc).astimezone().isoformat()
    }


def export_site_data(
    out_dir: Path,
    base_dir: Path,
    limit: int | None = None,
    include_blocked: bool = False
):
    """主导出逻辑"""
    print(f"[*] 开始导出数据...")
    print(f"    输入目录: {base_dir}")
    print(f"    输出目录: {out_dir}")

    # 收集所有 meta 文件
    meta_files = collect_meta_files(base_dir)
    print(f"[*] 找到 {len(meta_files)} 个 meta 文件")

    # 准备输出目录（清理旧的 docs/ 防止幽灵文件残留）
    out_dir.mkdir(parents=True, exist_ok=True)
    docs_dir = out_dir / "docs"
    if docs_dir.exists():
        shutil.rmtree(docs_dir)
        print(f"[*] 已清理旧 docs/ 目录")
    docs_dir.mkdir(parents=True, exist_ok=True)

    # 第一阶段：收集所有符合条件的记录
    all_records = []
    skipped_count = 0

    for meta_path in meta_files:
        meta = load_meta(meta_path)
        if not meta:
            skipped_count += 1
            continue

        # 检查是否应该导出
        if not should_export(meta, include_blocked):
            print(f"[-] 跳过 (status={meta.get('status')}): {meta.get('id', 'unknown')}")
            skipped_count += 1
            continue

        # 读取 Markdown 文件
        note_path = meta.get("note_path")
        markdown = None
        markdown_missing = False
        if note_path:
            markdown, markdown_missing = load_markdown(note_path)
            if markdown_missing:
                print(f"[!] Markdown 文件不存在: {note_path}")

        # 保存记录信息
        all_records.append({
            "meta": meta,
            "markdown": markdown,
            "markdown_missing": markdown_missing
        })

    # 按 updated_at 倒序排列（最新的在前）
    all_records.sort(key=lambda x: x["meta"].get("updated_at") or x["meta"].get("created_at") or "", reverse=True)

    # 如果有 limit，只取最新 N 条
    if limit and len(all_records) > limit:
        all_records = all_records[:limit]
        print(f"[!] 限制导出最新 {limit} 条记录")

    # 第��阶段：导出选中的记录
    index_records = []
    exported_count = 0

    for record in all_records:
        meta = record["meta"]
        markdown = record["markdown"]
        markdown_missing = record["markdown_missing"]

        # 构建 index 记录
        index_record = build_index_record(meta)
        index_records.append(index_record)

        # 构建详情记录
        detail_record = build_detail_record(meta, markdown, markdown_missing)

        # 写入 docs/<id>.json
        doc_id = meta.get("id", "unknown")
        detail_path = docs_dir / f"{doc_id}.json"
        with open(detail_path, "w", encoding="utf-8") as f:
            json.dump(detail_record, f, ensure_ascii=False, indent=2)

        exported_count += 1
        if exported_count % 10 == 0:
            print(f"[+] 已导出 {exported_count} 条记录...")

    # 写入 index.json
    index_path = out_dir / "index.json"
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index_records, f, ensure_ascii=False, indent=2)
    print(f"[+] 写入 index.json: {len(index_records)} 条记录")

    # 写入 stats.json
    stats = build_stats(index_records)
    stats_path = out_dir / "stats.json"
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(f"[+] 写入 stats.json")

    print(f"\n[+] 导出完成!")
    print(f"    导出记录: {exported_count}")
    print(f"    跳过记录: {skipped_count}")
    print(f"    输出目录: {out_dir}")

    # 一致性校验
    actual_docs = len(list(docs_dir.glob("*.json")))
    if actual_docs != exported_count:
        print(f"\n[!] 警告: index.json({exported_count}条) 与 docs/({actual_docs}个文件) 数量不一致!")
    else:
        print(f"[OK] 一致性校验通过: index.json 与 docs/ 均为 {exported_count} 条")


def main():
    parser = argparse.ArgumentParser(
        description="导出 collector-v1 数据为静态网站可用的 JSON 格式"
    )
    parser.add_argument(
        "--out-dir",
        default="site-data",
        help="输出目录 (默认: site-data)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="限制导出数量（最新 N 条）"
    )
    parser.add_argument(
        "--include-blocked",
        action="store_true",
        help="包含 blocked/failed 状态的记录"
    )

    args = parser.parse_args()

    # 加载配置
    cfg = load_config()
    base_dir = Path(cfg["storage"]["base_dir"])
    out_dir = Path(args.out_dir)

    # 执行导出
    export_site_data(
        out_dir=out_dir,
        base_dir=base_dir,
        limit=args.limit,
        include_blocked=args.include_blocked
    )


if __name__ == "__main__":
    main()
