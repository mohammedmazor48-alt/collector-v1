import sqlite3
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_db_path():
    cfg = load_config()
    return Path(cfg["database"]["path"])


def get_conn():
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def ensure_column_exists(cur, table_name: str, column_name: str, column_def: str):
    cur.execute(f"PRAGMA table_info({table_name})")
    columns = [row["name"] for row in cur.fetchall()]
    if column_name not in columns:
        cur.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}")


def init_storage_dirs():
    cfg = load_config()
    storage = cfg.get("storage", {})
    base_dir = Path(storage.get("base_dir", "./knowledge-vault"))
    raw_dir = base_dir / storage.get("raw_dir", "raw")
    notes_dir = base_dir / storage.get("notes_dir", "notes")
    meta_dir = base_dir / storage.get("meta_dir", "meta")
    assets_dir = base_dir / storage.get("assets_dir", "assets")
    logs_dir = base_dir / storage.get("logs_dir", "logs")
    for path in [base_dir, raw_dir, notes_dir, meta_dir, assets_dir, logs_dir]:
        path.mkdir(parents=True, exist_ok=True)
    return {
        "base_dir": str(base_dir),
        "raw_dir": str(raw_dir),
        "notes_dir": str(notes_dir),
        "meta_dir": str(meta_dir),
        "assets_dir": str(assets_dir),
        "logs_dir": str(logs_dir),
    }


def init_db():
    storage_info = init_storage_dirs()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS documents (
        id TEXT PRIMARY KEY,
        type TEXT NOT NULL,
        title TEXT,
        source TEXT,
        source_type TEXT,
        captured_at TEXT NOT NULL,
        published_at TEXT,
        author TEXT,
        language TEXT,
        summary TEXT,
        content_hash TEXT,
        source_file_hash TEXT,
        raw_path TEXT,
        note_path TEXT NOT NULL,
        meta_path TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """)
    ensure_column_exists(cur, "documents", "source_file_hash", "TEXT")
    cur.execute("""CREATE TABLE IF NOT EXISTS tags (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL);""")
    cur.execute("""CREATE TABLE IF NOT EXISTS document_tags (document_id TEXT NOT NULL, tag_id INTEGER NOT NULL, PRIMARY KEY (document_id, tag_id), FOREIGN KEY (document_id) REFERENCES documents(id), FOREIGN KEY (tag_id) REFERENCES tags(id));""")
    cur.execute("""CREATE INDEX IF NOT EXISTS idx_documents_source ON documents(source);""")
    cur.execute("""CREATE INDEX IF NOT EXISTS idx_documents_content_hash ON documents(content_hash);""")
    cur.execute("""CREATE INDEX IF NOT EXISTS idx_documents_source_file_hash ON documents(source_file_hash);""")
    cur.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(id, title, summary, content);""")
    conn.commit()
    conn.close()
    return {"storage": storage_info, "db_path": str(get_db_path())}


def find_by_source(source: str):
    if not source:
        return None
    conn = get_conn(); cur = conn.cursor(); cur.execute("SELECT * FROM documents WHERE source = ? LIMIT 1", (source,)); row = cur.fetchone(); conn.close(); return dict(row) if row else None


def find_by_content_hash(content_hash: str):
    if not content_hash:
        return None
    conn = get_conn(); cur = conn.cursor(); cur.execute("SELECT * FROM documents WHERE content_hash = ? LIMIT 1", (content_hash,)); row = cur.fetchone(); conn.close(); return dict(row) if row else None


def find_by_source_file_hash(source_file_hash: str):
    if not source_file_hash:
        return None
    conn = get_conn(); cur = conn.cursor(); cur.execute("SELECT * FROM documents WHERE source_file_hash = ? LIMIT 1", (source_file_hash,)); row = cur.fetchone(); conn.close(); return dict(row) if row else None


def ensure_tag(cur, tag_name: str) -> int:
    cur.execute("INSERT OR IGNORE INTO tags(name) VALUES (?)", (tag_name,))
    cur.execute("SELECT id FROM tags WHERE name = ?", (tag_name,))
    return cur.fetchone()["id"]


def replace_document_tags(cur, document_id: str, tags: list[str]):
    cur.execute("DELETE FROM document_tags WHERE document_id = ?", (document_id,))
    for tag in tags:
        if not tag:
            continue
        tag_id = ensure_tag(cur, tag)
        cur.execute("INSERT OR IGNORE INTO document_tags(document_id, tag_id) VALUES (?, ?)", (document_id, tag_id))


def upsert_document(doc: dict):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("""
    INSERT INTO documents (id, type, title, source, source_type, captured_at, published_at, author, language, summary, content_hash, source_file_hash, raw_path, note_path, meta_path, status, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(id) DO UPDATE SET
        type=excluded.type, title=excluded.title, source=excluded.source, source_type=excluded.source_type,
        captured_at=excluded.captured_at, published_at=excluded.published_at, author=excluded.author,
        language=excluded.language, summary=excluded.summary, content_hash=excluded.content_hash,
        source_file_hash=excluded.source_file_hash, raw_path=excluded.raw_path, note_path=excluded.note_path,
        meta_path=excluded.meta_path, status=excluded.status, updated_at=excluded.updated_at;
    """, (doc["id"], doc["type"], doc.get("title"), doc.get("source"), doc.get("source_type"), doc["captured_at"], doc.get("published_at"), doc.get("author"), doc.get("language"), doc.get("summary"), doc.get("content_hash"), doc.get("source_file_hash"), doc.get("raw_path"), doc["note_path"], doc["meta_path"], doc["status"], doc["created_at"], doc["updated_at"]))
    replace_document_tags(cur, doc["id"], doc.get("tags", []))
    cur.execute("DELETE FROM documents_fts WHERE id = ?", (doc["id"],))
    cur.execute("INSERT INTO documents_fts (id, title, summary, content) VALUES (?, ?, ?, ?)", (doc["id"], doc.get("title", ""), doc.get("summary", ""), doc.get("content_text", "")))
    conn.commit(); conn.close()
