"""
Chainlit data layer setup for HAYO AI Agent.

Enables:
  • Sidebar conversation history (past threads visible in left panel)
  • Thread resumption via @cl.on_chat_resume
  • Simple local authentication (no external DB needed)

Uses Chainlit's built-in SQLAlchemyDataLayer with SQLite backend.
The DB file lives alongside the agent at ./chainlit_data.db.
"""

from __future__ import annotations

import os
import sqlite3
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Database path ────────────────────────────────────────────────────────────
_DB_PATH = Path(__file__).resolve().parent.parent / "chainlit_data.db"


# ── SQLite schema (adapted from Chainlit's PostgreSQL schema) ────────────────
# SQLite does not support UUID, JSONB, TEXT[], or BOOLEAN natively.
# We use TEXT for UUID/JSONB/TEXT[] and INTEGER for BOOLEAN.
_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    "id" TEXT PRIMARY KEY,
    "identifier" TEXT NOT NULL UNIQUE,
    "metadata" TEXT NOT NULL DEFAULT '{}',
    "createdAt" TEXT
);

CREATE TABLE IF NOT EXISTS threads (
    "id" TEXT PRIMARY KEY,
    "createdAt" TEXT,
    "name" TEXT,
    "userId" TEXT,
    "userIdentifier" TEXT,
    "tags" TEXT,
    "metadata" TEXT,
    FOREIGN KEY ("userId") REFERENCES users("id") ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS steps (
    "id" TEXT PRIMARY KEY,
    "name" TEXT NOT NULL,
    "type" TEXT NOT NULL,
    "threadId" TEXT NOT NULL,
    "parentId" TEXT,
    "streaming" INTEGER NOT NULL DEFAULT 0,
    "waitForAnswer" INTEGER,
    "isError" INTEGER,
    "metadata" TEXT,
    "tags" TEXT,
    "input" TEXT,
    "output" TEXT,
    "createdAt" TEXT,
    "command" TEXT,
    "start" TEXT,
    "end" TEXT,
    "generation" TEXT,
    "showInput" TEXT,
    "language" TEXT,
    "indent" INTEGER,
    "defaultOpen" INTEGER,
    "autoCollapse" INTEGER,
    "modes" TEXT,
    FOREIGN KEY ("threadId") REFERENCES threads("id") ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS elements (
    "id" TEXT PRIMARY KEY,
    "threadId" TEXT,
    "type" TEXT,
    "url" TEXT,
    "chainlitKey" TEXT,
    "name" TEXT NOT NULL,
    "display" TEXT,
    "objectKey" TEXT,
    "size" TEXT,
    "page" INTEGER,
    "language" TEXT,
    "forId" TEXT,
    "mime" TEXT,
    "props" TEXT,
    FOREIGN KEY ("threadId") REFERENCES threads("id") ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS feedbacks (
    "id" TEXT PRIMARY KEY,
    "forId" TEXT NOT NULL,
    "threadId" TEXT NOT NULL,
    "value" INTEGER NOT NULL,
    "comment" TEXT,
    FOREIGN KEY ("threadId") REFERENCES threads("id") ON DELETE CASCADE
);
"""


_REQUIRED_STEPS_COLUMNS = [
    "autoCollapse",
    "icon",
]


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Migrate existing database by adding any missing columns."""
    try:
        cursor = conn.execute("PRAGMA table_info(steps)")
        existing = {row[1] for row in cursor.fetchall()}
        for col in _REQUIRED_STEPS_COLUMNS:
            if col not in existing:
                conn.execute(f'ALTER TABLE steps ADD COLUMN "{col}" TEXT')
                logger.info("Added missing column '%s' to steps table", col)
    except Exception as exc:
        logger.warning("Schema migration failed (non-fatal): %s", exc)


def ensure_schema() -> None:
    """Create the Chainlit data tables if they don't exist."""
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        conn = sqlite3.connect(str(_DB_PATH))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SQLITE_SCHEMA)
        _migrate_schema(conn)
        conn.close()
        logger.info("Chainlit data layer schema ready at %s", _DB_PATH)
    except Exception as exc:
        logger.warning("Failed to create Chainlit data schema: %s", exc)


def get_conninfo() -> str:
    """Return the SQLAlchemy connection string for the SQLite DB."""
    return f"sqlite+aiosqlite:///{_DB_PATH}"


# ── Authentication credentials ───────────────────────────────────────────────
# Default credentials for local single-user setup.
# Override via environment variables for security.
DEFAULT_USERNAME = os.getenv("HAYO_USERNAME", "admin")
DEFAULT_PASSWORD = os.getenv("HAYO_PASSWORD", "admin")


