import argparse
import json
from collections import defaultdict
from pathlib import Path

from processors.db import get_conn


def load_meta(meta_path: str) -> dict | None:
    if not meta_path:
        return None
    p = Path(meta_path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def fetch_documents(doc_type: str = "", limit: int = 0):
    conn = get_conn(); cur = conn.cursor(); sql = "SELECT id, type, title, source, note_path, meta_path, captured_at FROM documents"; params = []; conditions = []
    if doc_type:
        conditions.append("type = ?"); params.append(doc_type)
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY captured_at DESC"
    if limit and limit > 0:
        sql += " LIMIT ?"; params.append(limit)
    cur.execute(sql, params); rows = [dict(row) for row in cur.fetchall()]; conn.close(); return rows


def collect_duplicate_records(doc_type: str = "", limit: int = 0, existing_id: str = "", reason: str = ""):
    rows = fetch_documents(doc_type=doc_type, limit=limit); duplicate_records = []
    for row in rows:
        meta = load_meta(row.get("meta_path"))
        if not meta or not meta.get("duplicate_warning"):
            continue
        dw = meta["duplicate_warning"]
        if existing_id and dw.get("existing_id", "") != existing_id:
            continue
        if reason and dw.get("reason", "") != reason:
            continue
        duplicate_records.append({**row, "duplicate_warning": dw})
    return duplicate_records


def group_records(records: list[dict]):
    groups = defaultdict(list)
    for item in records:
        groups[item["duplicate_warning"].get("existing_id") or "UNKNOWN"].append(item)
    return groups


def build_grouped_payload(records: list[dict], sort_by_count: bool = True):
    groups = group_records(records); grouped_items = list(groups.items())
    grouped_items.sort(key=(lambda x: len(x[1])) if sort_by_count else (lambda x: x[0]), reverse=sort_by_count)
    payload = []
    for existing_id, items in grouped_items:
        sample_dw = items[0]["duplicate_warning"]
        items_sorted = sorted(items, key=lambda x: x["captured_at"], reverse=True)
        payload.append({"existing_id": existing_id, "existing_title": sample_dw.get("existing_title"), "existing_note": sample_dw.get("existing_note"), "duplicates_count": len(items_sorted), "duplicates": items_sorted})
    return payload


def print_flat(records: list[dict]):
    if not records:
        print("No duplicate relations found."); return
    for item in records:
        dw = item["duplicate_warning"]
        print("=" * 72)
        print(f"id: {item['id']}\ntype: {item['type']}\ntitle: {item['title']}\ncaptured_at: {item['captured_at']}\nsource: {item['source']}\nnote: {item['note_path']}")
        print("duplicate_warning:")
        for k in ["type", "existing_id", "existing_title", "existing_note", "reason"]:
            print(f"  {k}: {dw.get(k)}")


def print_grouped(records: list[dict], sort_by_count: bool = True):
    if not records:
        print("No duplicate relations found."); return
    for group in build_grouped_payload(records, sort_by_count=sort_by_count):
        print("#" * 72)
        print(f"existing_id: {group['existing_id']}\nexisting_title: {group['existing_title']}\nexisting_note: {group['existing_note']}\nduplicates_count: {group['duplicates_count']}\nduplicates:")
        for item in group["duplicates"]:
            print(f"  - id: {item['id']}\n    type: {item['type']}\n    title: {item['title']}\n    captured_at: {item['captured_at']}\n    source: {item['source']}\n    note: {item['note_path']}\n    reason: {item['duplicate_warning'].get('reason')}")


def main():
    parser = argparse.ArgumentParser(description="List duplicate relations from duplicate_warning in meta files")
    parser.add_argument("--mode", choices=["flat", "grouped"], default="grouped")
    parser.add_argument("--type", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--sort", choices=["count", "id"], default="count")
    parser.add_argument("--existing-id", default="")
    parser.add_argument("--reason", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    records = collect_duplicate_records(doc_type=args.type, limit=args.limit, existing_id=args.existing_id, reason=args.reason)
    if args.json:
        payload = {"mode": args.mode}
        if args.mode == "flat": payload.update({"count": len(records), "records": records})
        else: payload.update({"groups_count": len(group_records(records)), "groups": build_grouped_payload(records, sort_by_count=(args.sort == "count"))})
        print(json.dumps(payload, ensure_ascii=False, indent=2)); return
    if args.mode == "flat": print_flat(records)
    else: print_grouped(records, sort_by_count=(args.sort == "count"))


if __name__ == "__main__":
    main()
