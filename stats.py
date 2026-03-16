import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from processors.db import get_conn


def load_meta(meta_path: str):
    if not meta_path:
        return None
    p = Path(meta_path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def fetch_documents(limit: int = 0):
    conn = get_conn(); cur = conn.cursor(); sql = "SELECT id, type, title, source, status, captured_at, meta_path FROM documents ORDER BY captured_at DESC"; params = []
    if limit and limit > 0:
        sql += " LIMIT ?"; params.append(limit)
    cur.execute(sql, params); rows = [dict(row) for row in cur.fetchall()]; conn.close(); return rows


def parse_dt(value: str):
    try: return datetime.fromisoformat(value) if value else None
    except Exception: return None


def count_recent(rows, days: int):
    cutoff = datetime.now().astimezone() - timedelta(days=days)
    return sum(1 for row in rows if (parse_dt(row.get("captured_at")) and parse_dt(row.get("captured_at")) >= cutoff))


def compute_stats(rows):
    type_counter = Counter(); status_counter = Counter(); block_reason_counter = Counter(); duplicate_reason_counter = Counter(); pdf_extract_mode_counter = Counter(); ocr_engine_counter = Counter(); summary_backend_counter = Counter(); dedupe_skipped_counter = Counter(); recent_daily = defaultdict(int); missing_meta = 0
    for row in rows:
        type_counter[row.get("type") or "unknown"] += 1; status_counter[row.get("status") or "unknown"] += 1
        dt = parse_dt(row.get("captured_at"))
        if dt: recent_daily[dt.strftime("%Y-%m-%d")] += 1
        meta = load_meta(row.get("meta_path"))
        if not meta:
            missing_meta += 1; continue
        if meta.get("block_reason"): block_reason_counter[meta["block_reason"]] += 1
        if meta.get("duplicate_warning"):
            dw = meta["duplicate_warning"]; duplicate_reason_counter[dw.get("reason") or dw.get("type") or "unknown"] += 1
        if meta.get("pdf_extract_mode"): pdf_extract_mode_counter[meta["pdf_extract_mode"]] += 1
        if meta.get("ocr_engine"): ocr_engine_counter[meta["ocr_engine"]] += 1
        if isinstance(meta.get("summary_data"), dict) and meta["summary_data"].get("backend"):
            summary_backend_counter[meta["summary_data"]["backend"]] += 1
        if isinstance(meta.get("dedupe_skipped"), dict):
            dedupe_skipped_counter[meta["dedupe_skipped"].get("reason", "unknown")] += 1
    return {"total_docs": len(rows), "type_counter": dict(type_counter), "status_counter": dict(status_counter), "block_reason_counter": dict(block_reason_counter), "duplicate_reason_counter": dict(duplicate_reason_counter), "pdf_extract_mode_counter": dict(pdf_extract_mode_counter), "ocr_engine_counter": dict(ocr_engine_counter), "summary_backend_counter": dict(summary_backend_counter), "dedupe_skipped_counter": dict(dedupe_skipped_counter), "missing_meta": missing_meta, "recent_counts": {"last_7_days": count_recent(rows, 7), "last_30_days": count_recent(rows, 30)}, "daily_counts": dict(sorted(recent_daily.items(), reverse=True))}


def print_counter(title: str, data: dict):
    print(title + "\n" + "-" * 60)
    if not data:
        print("(empty)\n"); return
    for k, v in sorted(data.items(), key=lambda x: x[1], reverse=True):
        print(f"{k}: {v}")
    print()


def print_human(stats: dict, recent_days: int = 14):
    print("Collector Stats\n" + "=" * 72)
    print(f"total_docs: {stats['total_docs']}\nmissing_meta: {stats['missing_meta']}\n")
    for title, key in [("By Type", "type_counter"), ("By Status", "status_counter"), ("Block Reasons", "block_reason_counter"), ("Duplicate Reasons", "duplicate_reason_counter"), ("PDF Extract Modes", "pdf_extract_mode_counter"), ("OCR Engines", "ocr_engine_counter"), ("Summary Backends", "summary_backend_counter"), ("Dedupe Skipped", "dedupe_skipped_counter")]:
        print_counter(title, stats[key])
    print("Recent Activity\n" + "-" * 60)
    print(f"last_7_days: {stats['recent_counts']['last_7_days']}\nlast_30_days: {stats['recent_counts']['last_30_days']}\n")
    print(f"Daily Counts (latest {recent_days} days available)\n" + "-" * 60)
    shown = 0
    for day, count in stats["daily_counts"].items():
        print(f"{day}: {count}")
        shown += 1
        if shown >= recent_days:
            break
    if shown == 0:
        print("(empty)")


def main():
    parser = argparse.ArgumentParser(description="Show collector statistics")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--recent-days", type=int, default=14)
    args = parser.parse_args()
    stats = compute_stats(fetch_documents(limit=args.limit))
    if args.json:
        print(json.dumps(stats, ensure_ascii=False, indent=2)); return
    print_human(stats, recent_days=args.recent_days)


if __name__ == "__main__":
    main()
