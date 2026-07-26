"""
core/todo.py — a live, self-updating task list for the HAYO agent.

This is the "todo_write" methodology from Claude-Code / the HackerAI reference:
the agent maintains its OWN checklist during a run, marking items in_progress and
completed as it works, instead of relying only on the static up-front plan. It
makes the agent's thinking legible ("what am I doing, what's next") and keeps a
long task on-track across many tool calls.

Design for the HAYO architecture
--------------------------------
Tools here are plain LangChain functions bound to the LLM; they do not receive
AgentState. So the current task id is carried in a ``contextvars.ContextVar`` that
``worker_node`` sets at the start of each invocation. The todo list itself lives
in a process-local store keyed by task id (ephemeral working memory — the durable
record is still the LangGraph message history / checkpointer).

Statuses: ``pending`` → ``in_progress`` → ``completed`` (plus ``cancelled``).
"""

from __future__ import annotations

import threading
from contextvars import ContextVar

VALID_STATUSES = ("pending", "in_progress", "completed", "cancelled")

_STATUS_ICON = {
    "pending": "☐",
    "in_progress": "🔄",
    "completed": "✅",
    "cancelled": "✖️",
}

# Current task id for the executing node (set by worker_node each turn).
_current_task: ContextVar[str] = ContextVar("hayo_current_task", default="")

_lock = threading.RLock()
_STORES: dict[str, list[dict]] = {}

# Most-recently-active task id, tracked at module level so the UI thread (which
# does not share the worker's contextvar) can render the live board. contextvars
# do not cross threads, so the UI relies on this instead.
_last_task: str = ""


# ── task context ──────────────────────────────────────────────────────────────

def set_current_task(task_id: str) -> None:
    global _last_task
    _current_task.set(task_id or "")
    if task_id:
        _last_task = task_id


def active_task() -> str:
    """Best-effort current task id for UI rendering (module-level, thread-safe)."""
    return _current_task.get() or _last_task


def get_current_task() -> str:
    return _current_task.get()


# ── normalisation ─────────────────────────────────────────────────────────────

def _norm_status(status: object) -> str:
    s = str(status or "pending").strip().lower()
    # tolerate common variants the model may emit
    if s in ("in-progress", "inprogress", "doing", "active", "working"):
        s = "in_progress"
    elif s in ("done", "complete", "finished"):
        s = "completed"
    elif s in ("todo", "not_started", "new", ""):
        s = "pending"
    elif s in ("cancel", "canceled", "skip", "skipped"):
        s = "cancelled"
    return s if s in VALID_STATUSES else "pending"


def _norm_todo(raw: dict, index: int) -> dict | None:
    if not isinstance(raw, dict):
        return None
    tid = str(raw.get("id") or raw.get("ID") or "").strip()
    content = raw.get("content")
    if content is None:
        content = raw.get("task") or raw.get("title") or raw.get("text")
    content = str(content).strip() if content is not None else ""
    if not tid:
        # derive a stable-ish id from position if the model omitted one
        tid = f"t{index + 1}"
    status = _norm_status(raw.get("status"))
    return {"id": tid, "content": content, "status": status}


# ── core operations ───────────────────────────────────────────────────────────

def write_todos(task_id: str, todos: list, merge: bool = False) -> list[dict]:
    """Replace (or merge) the todo list for ``task_id``. Returns the new list.

    merge=False → the list is the authoritative full plan (replace).
    merge=True  → update existing items by id and append new ones; items not
                  mentioned are kept. Auto-enabled when incoming items look like
                  partial updates (missing content), so a status-only tick does
                  not wipe the plan.
    """
    global _last_task
    task_id = task_id or get_current_task() or "default"
    _last_task = task_id
    incoming: list[dict] = []
    looks_partial = False
    for i, raw in enumerate(todos or []):
        n = _norm_todo(raw, i)
        if n is None:
            continue
        if not n["content"]:
            looks_partial = True
        incoming.append(n)

    with _lock:
        if merge or looks_partial:
            existing = {t["id"]: dict(t) for t in _STORES.get(task_id, [])}
            order = [t["id"] for t in _STORES.get(task_id, [])]
            for n in incoming:
                if n["id"] in existing:
                    # keep old content if the update omitted it
                    if not n["content"]:
                        n["content"] = existing[n["id"]]["content"]
                    existing[n["id"]] = n
                else:
                    existing[n["id"]] = n
                    order.append(n["id"])
            merged = [existing[i] for i in order if i in existing]
            _STORES[task_id] = merged
        else:
            _STORES[task_id] = incoming
        return list(_STORES[task_id])


def get_todos(task_id: str = "") -> list[dict]:
    task_id = task_id or get_current_task() or "default"
    with _lock:
        return list(_STORES.get(task_id, []))


def clear_todos(task_id: str = "") -> None:
    task_id = task_id or get_current_task() or "default"
    with _lock:
        _STORES.pop(task_id, None)


def progress(task_id: str = "") -> tuple[int, int]:
    """(#completed, #total-excluding-cancelled)."""
    items = get_todos(task_id)
    total = sum(1 for t in items if t["status"] != "cancelled")
    done = sum(1 for t in items if t["status"] == "completed")
    return done, total


def render(task_id: str = "") -> str:
    """Markdown checklist for injection into the model's context / the UI."""
    items = get_todos(task_id)
    if not items:
        return ""
    done, total = progress(task_id)
    lines = [f"📋 قائمة المهام ({done}/{total}):"]
    for t in items:
        icon = _STATUS_ICON.get(t["status"], "☐")
        lines.append(f"  {icon} {t['content']}")
    return "\n".join(lines)


def render_markdown(task_id: str = "") -> str:
    """Rich markdown for the UI 'Task progress' panel.

    Completed items are struck through (~~...~~), in-progress items are bold with
    a spinner, pending items plain — mirroring the reference platform's dropdown.
    Returns "" when there are no todos so the UI can hide the panel.
    """
    tid = task_id or active_task()
    items = get_todos(tid)
    if not items:
        return ""
    done, total = progress(tid)
    lines = [f"**📋 Task progress — {done}/{total}**", ""]
    for t in items:
        content = t["content"].replace("\n", " ").strip()
        status = t["status"]
        if status == "completed":
            lines.append(f"- ✅ ~~{content}~~")
        elif status == "in_progress":
            lines.append(f"- 🔄 **{content}**")
        elif status == "cancelled":
            lines.append(f"- ✖️ ~~{content}~~ _(ملغى)_")
        else:
            lines.append(f"- ☐ {content}")
    return "\n".join(lines)


def all_complete(task_id: str = "") -> bool:
    """True iff there is at least one todo and every non-cancelled item is done."""
    items = get_todos(task_id)
    active = [t for t in items if t["status"] != "cancelled"]
    return bool(active) and all(t["status"] == "completed" for t in active)


if __name__ == "__main__":  # smoke test
    set_current_task("job1")
    write_todos("job1", [
        {"id": "1", "content": "استكشاف المشروع", "status": "completed"},
        {"id": "2", "content": "إصلاح الخطأ", "status": "in_progress"},
        {"id": "3", "content": "تشغيل الاختبار", "status": "pending"},
    ])
    print(render("job1"))
    # partial status tick must not wipe content
    write_todos("job1", [{"id": "2", "status": "completed"}])
    assert get_todos("job1")[1]["content"] == "إصلاح الخطأ"
    assert progress("job1") == (2, 3), progress("job1")
    write_todos("job1", [{"id": "3", "status": "completed"}])
    assert all_complete("job1")
    print("todo smoke OK")
