"""
core/maintenance.py — Keep the LangGraph checkpoint database small and fast.

The AsyncSqliteSaver writes a full state snapshot on every super-step, so
`agent_memory.db` grows without bound (it had reached 72 MB / 11k+ write rows
in normal use). A bloated checkpoint DB slows every single graph step because
each save/load touches a larger file.

`prune_memory_db()` is called once at startup (before the checkpointer opens the
DB). It is intentionally conservative and crash-safe:

  • Keep only the most recently used N conversation threads.
  • Within each kept thread, keep only the last M checkpoints (enough to resume
    and to time-travel a little); older intermediate snapshots are dropped.
  • Delete orphaned `writes` rows whose checkpoint no longer exists.
  • VACUUM to physically reclaim space when the file is large.

It NEVER raises into the caller — maintenance must never block the app from
starting. Ordering uses each table's implicit `rowid` (monotonic insertion
order), so it does not depend on the internal format of checkpoint IDs.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import time

logger = logging.getLogger("hayo.maintenance")


def prune_memory_db(
    db_path: str,
    keep_threads: int = 20,
    keep_checkpoints_per_thread: int = 6,
    vacuum_threshold_mb: int = 30,
) -> dict:
    """
    Prune the LangGraph checkpoint DB. Returns a summary dict (never raises).

    Args:
        db_path: path to agent_memory.db
        keep_threads: how many most-recent threads to retain
        keep_checkpoints_per_thread: snapshots to keep per retained thread
        vacuum_threshold_mb: VACUUM only if the file is at least this big
    """
    summary = {
        "ran": False, "threads_before": 0, "threads_after": 0,
        "checkpoints_deleted": 0, "writes_deleted": 0,
        "mb_before": 0.0, "mb_after": 0.0, "vacuumed": False, "error": "",
    }

    if not os.path.isfile(db_path):
        return summary

    try:
        summary["mb_before"] = round(os.path.getsize(db_path) / (1024 * 1024), 1)
    except OSError:
        pass

    conn = None
    try:
        # Short busy timeout so we never hang behind another connection.
        conn = sqlite3.connect(db_path, timeout=5.0)
        conn.execute("PRAGMA busy_timeout = 5000")
        cur = conn.cursor()

        # Confirm the expected schema exists; if not, do nothing.
        tables = {r[0] for r in cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        if "checkpoints" not in tables:
            return summary

        # ── 1. Rank threads by recency (max rowid = most recent write) ────────
        rows = cur.execute(
            "SELECT thread_id, MAX(rowid) AS last_row "
            "FROM checkpoints GROUP BY thread_id ORDER BY last_row DESC"
        ).fetchall()
        all_threads = [r[0] for r in rows]
        summary["threads_before"] = len(all_threads)

        keep_set = set(all_threads[:keep_threads])
        drop_threads = [t for t in all_threads if t not in keep_set]

        deleted_ckpts = 0
        deleted_writes = 0

        # ── 2. Drop entire stale threads ──────────────────────────────────────
        for t in drop_threads:
            cur.execute("DELETE FROM checkpoints WHERE thread_id = ?", (t,))
            deleted_ckpts += cur.rowcount or 0
            if "writes" in tables:
                cur.execute("DELETE FROM writes WHERE thread_id = ?", (t,))
                deleted_writes += cur.rowcount or 0

        # ── 3. Within kept threads, keep only the last M checkpoints ──────────
        for t in keep_set:
            ckpt_rows = cur.execute(
                "SELECT checkpoint_id, rowid FROM checkpoints "
                "WHERE thread_id = ? ORDER BY rowid DESC",
                (t,),
            ).fetchall()
            if len(ckpt_rows) <= keep_checkpoints_per_thread:
                continue
            stale = ckpt_rows[keep_checkpoints_per_thread:]
            stale_ids = [r[0] for r in stale]
            # Delete in chunks to keep the SQL parameter list bounded.
            for i in range(0, len(stale_ids), 400):
                chunk = stale_ids[i:i + 400]
                ph = ",".join("?" * len(chunk))
                cur.execute(
                    f"DELETE FROM checkpoints WHERE thread_id = ? "
                    f"AND checkpoint_id IN ({ph})",
                    (t, *chunk),
                )
                deleted_ckpts += cur.rowcount or 0
                if "writes" in tables:
                    cur.execute(
                        f"DELETE FROM writes WHERE thread_id = ? "
                        f"AND checkpoint_id IN ({ph})",
                        (t, *chunk),
                    )
                    deleted_writes += cur.rowcount or 0

        # ── 4. Sweep any orphaned writes (defensive) ──────────────────────────
        if "writes" in tables:
            cur.execute(
                "DELETE FROM writes WHERE checkpoint_id NOT IN "
                "(SELECT checkpoint_id FROM checkpoints)"
            )
            deleted_writes += cur.rowcount or 0

        conn.commit()

        summary["checkpoints_deleted"] = deleted_ckpts
        summary["writes_deleted"] = deleted_writes
        summary["threads_after"] = len(keep_set)

        # ── 5. VACUUM to reclaim space when worthwhile ────────────────────────
        if summary["mb_before"] >= vacuum_threshold_mb and (
            deleted_ckpts or deleted_writes
        ):
            try:
                conn.execute("VACUUM")
                summary["vacuumed"] = True
            except sqlite3.OperationalError as ve:
                # VACUUM fails if another connection holds the DB — skip quietly.
                summary["error"] = f"vacuum skipped: {ve}"

        summary["ran"] = True
    except Exception as exc:
        summary["error"] = f"{type(exc).__name__}: {exc}"
        logger.warning("DB pruning skipped: %s", exc)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    try:
        summary["mb_after"] = round(os.path.getsize(db_path) / (1024 * 1024), 1)
    except OSError:
        pass

    if summary["ran"]:
        logger.info(
            "🧹 Memory DB pruned: %.1f→%.1f MB | threads %d→%d | "
            "-%d checkpoints, -%d writes%s",
            summary["mb_before"], summary["mb_after"],
            summary["threads_before"], summary["threads_after"],
            summary["checkpoints_deleted"], summary["writes_deleted"],
            " | VACUUMed" if summary["vacuumed"] else "",
        )
    return summary


def auto_prune_if_needed(db_path: str, size_trigger_mb: int = 25) -> dict:
    """
    Convenience wrapper: only prune when the DB has grown past `size_trigger_mb`.
    Cheap to call on every startup.
    """
    try:
        if not os.path.isfile(db_path):
            return {"ran": False}
        size_mb = os.path.getsize(db_path) / (1024 * 1024)
        if size_mb < size_trigger_mb:
            return {"ran": False, "mb_before": round(size_mb, 1), "skipped": "under threshold"}
    except OSError:
        return {"ran": False}
    return prune_memory_db(db_path)
