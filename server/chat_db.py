import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "chat.db"


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                page TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT 'New conversation',
                created_at REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                reasoning TEXT,
                created_at REAL NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            )
        """)


def create_conversation(page: str, title: str = "New conversation") -> int:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO conversations (page, title, created_at) VALUES (?, ?, ?)",
            (page, title, time.time()),
        )
        return cur.lastrowid


def list_conversations(page: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM conversations WHERE page = ? ORDER BY created_at DESC",
            (page,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_messages(conversation_id: int) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id ASC",
            (conversation_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def add_message(conversation_id: int, role: str, content: str, reasoning: str = None):
    with _connect() as conn:
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content, reasoning, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (conversation_id, role, content, reasoning, time.time()),
        )


def rename_conversation(conversation_id: int, title: str):
    with _connect() as conn:
        conn.execute("UPDATE conversations SET title = ? WHERE id = ?", (title, conversation_id))


def delete_conversation(conversation_id: int):
    with _connect() as conn:
        conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
        conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
