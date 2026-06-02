"""
ConversationStore — persistent memory of past conversations.

LangGraph's SqliteSaver already persists the message history of each
thread_id. This module adds a SECOND layer: a lightweight index over those
threads with title + summary + timestamps so we can:

  • List the user's recent conversations on chat start
  • Search past conversations by topic
  • Let the agent recall context from prior sessions

Storage is a single SQLite DB (default: ./conversations.db) — separate from
agent_memory.db so neither file can corrupt the other.
"""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Optional


_DEFAULT_DB = Path(__file__).resolve().parent.parent / "conversations.db"


# ── Schema ───────────────────────────────────────────────────────────────────
_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    thread_id     TEXT PRIMARY KEY,
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL,
    title         TEXT NOT NULL DEFAULT '',
    summary       TEXT NOT NULL DEFAULT '',
    message_count INTEGER NOT NULL DEFAULT 0,
    provider      TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_conv_updated ON conversations(updated_at DESC);

-- FTS index for full-text search across titles + summaries
CREATE VIRTUAL TABLE IF NOT EXISTS conv_fts USING fts5(
    thread_id UNINDEXED,
    title,
    summary,
    content='conversations',
    content_rowid='rowid',
    tokenize='unicode61'
);

CREATE TRIGGER IF NOT EXISTS conv_ai AFTER INSERT ON conversations BEGIN
    INSERT INTO conv_fts(rowid, thread_id, title, summary)
    VALUES (new.rowid, new.thread_id, new.title, new.summary);
END;

CREATE TRIGGER IF NOT EXISTS conv_au AFTER UPDATE ON conversations BEGIN
    INSERT INTO conv_fts(conv_fts, rowid, thread_id, title, summary)
    VALUES ('delete', old.rowid, old.thread_id, old.title, old.summary);
    INSERT INTO conv_fts(rowid, thread_id, title, summary)
    VALUES (new.rowid, new.thread_id, new.title, new.summary);
END;

CREATE TRIGGER IF NOT EXISTS conv_ad AFTER DELETE ON conversations BEGIN
    INSERT INTO conv_fts(conv_fts, rowid, thread_id, title, summary)
    VALUES ('delete', old.rowid, old.thread_id, old.title, old.summary);
END;
"""


class ConversationStore:
    """Persistent index of past conversations with connection reuse."""

    def __init__(self, db_path: Optional[Path | str] = None):
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        """Reuse a single connection per store instance."""
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self.db_path), timeout=10.0, check_same_thread=False,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
        return self._conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    # ── Write operations ────────────────────────────────────────────────────
    def upsert(
        self,
        thread_id: str,
        title: str = "",
        summary: str = "",
        message_count: int = 0,
        provider: str = "",
    ) -> None:
        """
        Insert or update a conversation row. Existing rows keep their original
        created_at but get updated_at refreshed.
        """
        now = time.time()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT created_at, title, summary, message_count FROM conversations WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
            if existing:
                # Keep title/summary if caller didn't provide new ones
                final_title = title or existing["title"]
                final_summary = summary or existing["summary"]
                final_count = message_count if message_count > 0 else existing["message_count"]
                conn.execute(
                    "UPDATE conversations SET updated_at = ?, title = ?, summary = ?, "
                    "message_count = ?, provider = COALESCE(NULLIF(?, ''), provider) "
                    "WHERE thread_id = ?",
                    (now, final_title, final_summary, final_count, provider, thread_id),
                )
            else:
                conn.execute(
                    "INSERT INTO conversations (thread_id, created_at, updated_at, title, "
                    "summary, message_count, provider) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (thread_id, now, now, title, summary, message_count, provider),
                )
            conn.commit()

    def touch(self, thread_id: str) -> None:
        """Mark a conversation as recently active without changing its metadata."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE thread_id = ?",
                (time.time(), thread_id),
            )
            conn.commit()

    def delete(self, thread_id: str) -> None:
        """Remove a conversation from the index (does NOT remove its LangGraph state)."""
        with self._connect() as conn:
            conn.execute("DELETE FROM conversations WHERE thread_id = ?", (thread_id,))
            conn.commit()

    # ── Read operations ─────────────────────────────────────────────────────
    def get(self, thread_id: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM conversations WHERE thread_id = ?", (thread_id,)
            ).fetchone()
            return dict(row) if row else None

    def list_recent(self, limit: int = 10) -> list[dict]:
        """Return the N most-recently-updated conversations."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def search(self, query: str, limit: int = 5) -> list[dict]:
        """Full-text search across titles and summaries."""
        if not query.strip():
            return []
        # FTS5 special chars need escaping; quote to be safe
        safe = query.replace('"', '""')
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT c.* FROM conv_fts f "
                    "JOIN conversations c ON c.thread_id = f.thread_id "
                    "WHERE conv_fts MATCH ? "
                    "ORDER BY c.updated_at DESC "
                    "LIMIT ?",
                    (f'"{safe}"', limit),
                ).fetchall()
                return [dict(r) for r in rows]
        except sqlite3.OperationalError:
            # FTS query syntax issue — fall back to LIKE
            with self._connect() as conn:
                like = f"%{query}%"
                rows = conn.execute(
                    "SELECT * FROM conversations "
                    "WHERE title LIKE ? OR summary LIKE ? "
                    "ORDER BY updated_at DESC LIMIT ?",
                    (like, like, limit),
                ).fetchall()
                return [dict(r) for r in rows]

    def count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM conversations").fetchone()
            return int(row["n"]) if row else 0


# ── Module-level singleton ───────────────────────────────────────────────────
_store: Optional[ConversationStore] = None


def get_conversation_store() -> ConversationStore:
    """Return the shared ConversationStore instance."""
    global _store
    if _store is None:
        _store = ConversationStore()
    return _store


# ── Title + summary helpers ──────────────────────────────────────────────────
def derive_title(first_user_message: str, max_len: int = 60) -> str:
    """
    Make a short title from the first user message. Strip whitespace, collapse
    newlines, and truncate to max_len characters.
    """
    if not first_user_message:
        return "محادثة"
    text = " ".join(first_user_message.split())
    if len(text) <= max_len:
        return text
    # Try to cut at a word boundary
    cut = text[:max_len]
    last_space = cut.rfind(" ")
    if last_space > max_len * 0.5:
        cut = cut[:last_space]
    return cut + "…"


def derive_summary(messages: list, max_chars: int = 400) -> str:
    """
    Build a short plain-text summary of a conversation from its messages.

    Strategy (no LLM call needed — fast and deterministic):
      - First user message describes the goal
      - Last assistant TASK_COMPLETE/FAILED/CONVERSATIONAL line describes outcome
      - Truncate to max_chars
    """
    from langchain_core.messages import AIMessage, HumanMessage

    first_user = ""
    last_verdict = ""
    for m in messages:
        if isinstance(m, HumanMessage) and not first_user:
            content = m.content if isinstance(m.content, str) else str(m.content)
            first_user = content.strip()
        if isinstance(m, AIMessage):
            content = m.content if isinstance(m.content, str) else str(m.content)
            if not content:
                continue
            # Look for verdict markers
            for marker in ("TASK_COMPLETE:", "FAILED:", "CONTINUE:"):
                if marker in content:
                    # Take everything after the marker, first line only
                    after = content.split(marker, 1)[1].strip()
                    first_line = after.splitlines()[0] if after else ""
                    if first_line:
                        last_verdict = first_line[:250]
                        break

    parts = []
    if first_user:
        parts.append(f"Goal: {first_user[:200]}")
    if last_verdict:
        parts.append(f"Outcome: {last_verdict}")
    summary = " · ".join(parts) or first_user[:max_chars]
    if len(summary) > max_chars:
        summary = summary[:max_chars - 1] + "…"
    return summary


__all__ = [
    "ConversationStore",
    "get_conversation_store",
    "derive_title",
    "derive_summary",
]
