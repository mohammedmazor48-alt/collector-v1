import argparse
import json
from pathlib import Path

from processors.db import get_conn


def load_duplicate_warning(meta_path: str):
    if not meta_path:
        return None
    p = Path(meta_path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("duplicate_warning")
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser(description="List ingested documents")
    parser.add_argument("--type", default="")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--duplicates-only", action="store_true")
    args = parser.parse_args()
    conn = get_conn(); cur = conn.cursor()
    sql = "SELECT id, type, title, source, note_path, meta_path, captured_at FROM documents"; params = []; conditions = []
    if args.type:
        conditions.append("type = ?"); params.append(args.type)
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY captured_at DESC LIMIT ?"; params.append(args.limit)
    cur.execute(sql, params); rows = cur.fetchall(); conn.close()
    shown = 0
    for row in rows:
        duplicate_warning = load_duplicate_warning(row["meta_path"])
        if args.duplicates_only and not duplicate_warning:
            continue
        print("-" * 60)
        print(f"id: {row['id']}\ntype: {row['type']}\ntitle: {row['title']}\ncaptured_at: {row['captured_at']}\nsource: {row['source']}\nnote: {row['note_path']}")
        if duplicate_warning:
            print("duplicate_warning:")
            print(f"  type: {duplicate_warning.get('type')}")
            print(f"  existing_id: {duplicate_warning.get('existing_id')}")
            print(f"  existing_title: {duplicate_warning.get('existing_title')}")
        shown += 1
    if shown == 0:
        print("No documents found.")


if __name__ == "__main__":
    main()
