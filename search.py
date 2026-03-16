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
    parser = argparse.ArgumentParser(description="Search ingested documents")
    parser.add_argument("query")
    args = parser.parse_args()
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT d.id, d.type, d.title, d.source, d.note_path, d.meta_path FROM documents_fts f JOIN documents d ON d.id = f.id WHERE documents_fts MATCH ? LIMIT 20", (args.query,))
    rows = cur.fetchall()
    if not rows:
        print("No results."); conn.close(); return
    for row in rows:
        cur.execute("SELECT t.name FROM tags t JOIN document_tags dt ON dt.tag_id = t.id WHERE dt.document_id = ? ORDER BY t.name", (row["id"],))
        tags = [t["name"] for t in cur.fetchall()]
        duplicate_warning = load_duplicate_warning(row["meta_path"])
        print("-" * 60)
        print(f"id: {row['id']}\ntype: {row['type']}\ntitle: {row['title']}\nsource: {row['source']}\ntags: {', '.join(tags) if tags else '-'}\nnote: {row['note_path']}")
        if duplicate_warning:
            print("duplicate_warning:")
            print(f"  type: {duplicate_warning.get('type')}")
            print(f"  existing_id: {duplicate_warning.get('existing_id')}")
    conn.close()


if __name__ == "__main__":
    main()
