"""
Todo Tools — the agent's live task checklist (Claude-Code style).

todo_write lets the agent maintain its own plan during a run: create the list,
then tick items in_progress / completed as it works. The agent should call it:
  • right after planning a multi-step task (seed the list),
  • whenever it starts an item (mark in_progress),
  • as soon as an item is finished (mark completed).
"""

from __future__ import annotations

from typing import Annotated, Optional

from langchain_core.tools import tool

from core import todo as _todo


@tool
def todo_write(
    todos: Annotated[
        list,
        "The task list: a list of objects, each {\"id\": \"1\", \"content\": \"...\", "
        "\"status\": \"pending|in_progress|completed|cancelled\"}. Keep ids stable "
        "across calls so updates land on the right item.",
    ],
    merge: Annotated[
        bool,
        "False = this is the full plan (replace). True = update/add only the given "
        "items, keep the rest. A status-only update auto-merges.",
    ] = False,
) -> str:
    """Create or update the live task checklist for the current task.

    Use it to plan and TRACK multi-step work: seed the list after planning, then
    keep exactly ONE item in_progress and mark items completed the moment they are
    done. This keeps long tasks on-track and makes progress visible.
    """
    try:
        task_id = _todo.get_current_task() or "default"
        if not isinstance(todos, list):
            return "❌ todo_write: 'todos' يجب أن تكون قائمة من العناصر."
        items = _todo.write_todos(task_id, todos, merge=merge)
        done, total = _todo.progress(task_id)
        board = _todo.render(task_id)
        return f"[OK] تم تحديث قائمة المهام ({done}/{total}).\n{board}"
    except Exception as exc:
        return f"❌ todo_write: {exc}"


@tool
def todo_read() -> str:
    """Read the current live task checklist (ids, contents, statuses)."""
    try:
        board = _todo.render(_todo.get_current_task() or "default")
        return board or "📋 لا توجد مهام في القائمة بعد. استخدم todo_write لإنشائها."
    except Exception as exc:
        return f"❌ todo_read: {exc}"
