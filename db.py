"""
db.py
-----
SQLite-based persistent conversation memory.
Replaces the in-memory Python dict — survives server restarts.
"""

from __future__ import annotations
import sqlite3
import threading
import logging
from datetime import datetime
from config import get_settings

logger = logging.getLogger(__name__)
_settings = get_settings()

MAX_HISTORY = 20   # messages per user to keep in context

# Thread-local connections for SQLite thread safety
_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn"):
        _local.conn = sqlite3.connect(_settings.db_path, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        # Enable WAL mode for better concurrent reads
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA synchronous=NORMAL")
    return _local.conn


def init_db() -> None:
    """Create tables if they don't exist. Call on startup."""
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     TEXT    NOT NULL,
            role        TEXT    NOT NULL,
            content     TEXT    NOT NULL,
            tool_name   TEXT,
            created_at  TEXT    DEFAULT (datetime('now'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON conversations(user_id)")
    conn.commit()
    logger.info("Database initialised at %s", _settings.db_path)


def get_history(user_id: str) -> list[dict]:
    """Return the last MAX_HISTORY messages for a user."""
    conn = _get_conn()
    rows = conn.execute(
        """
        SELECT role, content, tool_name
        FROM (
            SELECT role, content, tool_name, created_at
            FROM conversations
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        ) ORDER BY created_at ASC
        """,
        (user_id, MAX_HISTORY),
    ).fetchall()
    return [dict(r) for r in rows]


def append_message(user_id: str, role: str, content: str, tool_name: str | None = None) -> None:
    """Persist a single message to the conversation history."""
    conn = _get_conn()
    conn.execute(
        "INSERT INTO conversations (user_id, role, content, tool_name) VALUES (?, ?, ?, ?)",
        (user_id, role, content, tool_name),
    )
    conn.commit()


def clear_history(user_id: str) -> int:
    """Delete all messages for a user. Returns number of rows deleted."""
    conn = _get_conn()
    cur = conn.execute("DELETE FROM conversations WHERE user_id = ?", (user_id,))
    conn.commit()
    return cur.rowcount


def list_users() -> list[str]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT DISTINCT user_id FROM conversations ORDER BY user_id"
    ).fetchall()
    return [r["user_id"] for r in rows]
