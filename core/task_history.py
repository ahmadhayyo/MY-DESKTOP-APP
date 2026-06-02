"""
Task History — track executed tasks and their results.

Uses a SQLite database (task_history.db) to persist task records across sessions.

Usage from app.py:
    /tasks           — list recent tasks
    /tasks clear     — clear task history
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_DB_PATH = _ROOT / "task_history.db"

# Reusable connection (avoids opening/closing on every operation)
_conn: sqlite3.Connection | None = None


def _get_db() -> sqlite3.Connection:
    """Open (and create if needed) the task history database. Reuses connection."""
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id   TEXT NOT NULL,
                description TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'running',
                provider    TEXT DEFAULT '',
                model       TEXT DEFAULT '',
                steps_total INTEGER DEFAULT 0,
                steps_done  INTEGER DEFAULT 0,
                error       TEXT DEFAULT '',
                started_at  REAL NOT NULL,
                finished_at REAL DEFAULT 0,
                duration_s  REAL DEFAULT 0
            )
        """)
        _conn.commit()
    else:
        try:
            _conn.execute("SELECT 1")
        except sqlite3.ProgrammingError:
            _conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA journal_mode=WAL")
    return _conn


def start_task(
    thread_id: str,
    description: str,
    provider: str = "",
    model: str = "",
    steps_total: int = 0,
) -> int:
    """Record a new task as 'running'. Returns the task ID."""
    conn = _get_db()
    try:
        cur = conn.execute(
            """INSERT INTO tasks (thread_id, description, status, provider, model, steps_total, started_at)
               VALUES (?, ?, 'running', ?, ?, ?, ?)""",
            (thread_id, description[:500], provider, model, steps_total, time.time()),
        )
        conn.commit()
        return cur.lastrowid or 0
    finally:
        pass  # connection stays open, _get_db() handles reconnection


def finish_task(
    task_id: int,
    status: str = "completed",
    steps_done: int = 0,
    error: str = "",
) -> None:
    """Mark a task as completed or failed."""
    now = time.time()
    conn = _get_db()
    try:
        conn.execute(
            """UPDATE tasks
               SET status = ?, steps_done = ?, error = ?,
                   finished_at = ?, duration_s = (? - started_at)
               WHERE id = ?""",
            (status, steps_done, error[:500], now, now, task_id),
        )
        conn.commit()
    finally:
        pass  # connection stays open


def list_tasks(limit: int = 15) -> list[dict[str, Any]]:
    """Return the most recent tasks."""
    conn = _get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM tasks ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        pass  # connection stays open


def clear_tasks() -> int:
    """Delete all task history. Returns count of deleted rows."""
    conn = _get_db()
    try:
        cur = conn.execute("DELETE FROM tasks")
        conn.commit()
        return cur.rowcount
    finally:
        pass  # connection stays open


def format_tasks_display(limit: int = 15) -> str:
    """Return a formatted string showing recent tasks."""
    tasks = list_tasks(limit)

    lines = ["# 📋 سجل المهام — Task History\n"]

    if not tasks:
        lines.append("📭 لا توجد مهام مسجلة بعد.")
        lines.append("\nالمهام تُسجَّل تلقائياً عند تنفيذ أي طلب.")
        return "\n".join(lines)

    # Stats
    total = len(tasks)
    completed = sum(1 for t in tasks if t["status"] == "completed")
    failed = sum(1 for t in tasks if t["status"] == "failed")
    running = sum(1 for t in tasks if t["status"] == "running")

    lines.append(
        f"**{total}** مهمة"
        + (f" · ✅ {completed} مكتملة" if completed else "")
        + (f" · ❌ {failed} فاشلة" if failed else "")
        + (f" · ⏳ {running} قيد التنفيذ" if running else "")
        + "\n"
    )

    import datetime as _dt

    for i, t in enumerate(tasks, 1):
        # Status icon
        status_icon = {
            "completed": "✅",
            "failed": "❌",
            "running": "⏳",
        }.get(t["status"], "❓")

        # Time
        ts = _dt.datetime.fromtimestamp(t["started_at"]).strftime("%Y-%m-%d %H:%M")

        # Duration
        dur = t.get("duration_s", 0)
        if dur > 0:
            if dur < 60:
                dur_str = f"{dur:.0f}ث"
            elif dur < 3600:
                dur_str = f"{dur / 60:.1f}د"
            else:
                dur_str = f"{dur / 3600:.1f}س"
        elif t["status"] == "running":
            elapsed = time.time() - t["started_at"]
            dur_str = f"⏱️ {elapsed:.0f}ث"
        else:
            dur_str = "—"

        # Steps
        steps = ""
        if t["steps_total"] > 0:
            steps = f" · {t['steps_done']}/{t['steps_total']} خطوة"

        # Provider
        provider = f" · {t['provider']}" if t.get("provider") else ""

        desc = t["description"][:100]
        lines.append(f"**{i}.** {status_icon} {desc}")
        lines.append(f"   📅 {ts} · ⏱️ {dur_str}{steps}{provider}")

        if t.get("error"):
            lines.append(f"   ⚠️ {t['error'][:100]}")
        lines.append("")

    lines.append("---")
    lines.append("**الأوامر:**")
    lines.append("  • `/tasks` — عرض سجل المهام")
    lines.append("  • `/tasks clear` — مسح السجل")

    return "\n".join(lines)
