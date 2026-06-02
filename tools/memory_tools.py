"""
Memory tools — let the agent recall past conversations.

These give the agent the same access to its conversation history that the
user has via /history. Useful when the user says things like:
  • "what did we discuss yesterday about X?"
  • "ما الذي طلبته منك في المحادثة السابقة؟"
  • "remember that file I asked you to download last week?"
"""

from __future__ import annotations

import datetime as _dt
from typing import Annotated

from langchain_core.tools import tool

from core.conversation_store import get_conversation_store


def _format_conv(c: dict) -> str:
    """Render a conversation record into a compact human-readable block."""
    ts = _dt.datetime.fromtimestamp(c["updated_at"]).strftime("%Y-%m-%d %H:%M")
    tid_short = c["thread_id"][:8]
    title = c["title"] or "(بدون عنوان)"
    summary = c["summary"] or "(لا يوجد ملخص)"
    return (
        f"  [{tid_short}] {ts}\n"
        f"  Title: {title}\n"
        f"  Summary: {summary}\n"
        f"  Messages: {c['message_count']}"
    )


@tool
def list_past_conversations(
    limit: Annotated[int, "How many recent conversations to return (default 10, max 50)"] = 10,
) -> str:
    """
    List the user's recent past conversations with this agent (most recent first).
    Use when the user asks 'what did we talk about' or wants to recall past sessions.
    """
    limit = max(1, min(limit, 50))
    store = get_conversation_store()
    items = store.list_recent(limit=limit)
    if not items:
        return "[OK] No past conversations recorded yet."

    lines = [f"[OK] Found {len(items)} recent conversation(s):", ""]
    for i, c in enumerate(items, 1):
        lines.append(f"#{i}")
        lines.append(_format_conv(c))
        lines.append("")
    return "\n".join(lines)


@tool
def search_past_conversations(
    query: Annotated[str, "Keywords or topic to search for, e.g. 'song download' or 'تحميل اغنية'"],
    limit: Annotated[int, "Max results to return (default 5, max 20)"] = 5,
) -> str:
    """
    Search the user's past conversations by title + summary content.
    Useful for recalling specific past tasks: 'find the conversation where I
    asked you to download X' or 'ما الذي اقترحته عن Y سابقاً؟'.
    """
    limit = max(1, min(limit, 20))
    if not query.strip():
        return "[ERROR] Query is empty."
    store = get_conversation_store()
    items = store.search(query, limit=limit)
    if not items:
        return f"[OK] No past conversations match '{query}'."

    lines = [f"[OK] Found {len(items)} match(es) for '{query}':", ""]
    for i, c in enumerate(items, 1):
        lines.append(f"#{i}")
        lines.append(_format_conv(c))
        lines.append("")
    return "\n".join(lines)


@tool
def recall_conversation_details(
    thread_id_prefix: Annotated[str, "The first 8+ characters of the conversation ID (from list_past_conversations)"],
) -> str:
    """
    Fetch the full title + summary of a specific past conversation. Use this
    after list_past_conversations or search_past_conversations to drill into
    one specific session.
    """
    prefix = thread_id_prefix.strip().lower()
    if not prefix:
        return "[ERROR] thread_id_prefix is empty."

    store = get_conversation_store()
    candidates = [c for c in store.list_recent(limit=500) if c["thread_id"].startswith(prefix)]
    if not candidates:
        return f"[ERROR] No conversation found starting with '{prefix}'."
    if len(candidates) > 1:
        ids = ", ".join(c["thread_id"][:8] for c in candidates[:5])
        return f"[ERROR] {len(candidates)} matches — be more specific. Some IDs: {ids}"

    c = candidates[0]
    return f"[OK]\n{_format_conv(c)}"


__all__ = [
    "list_past_conversations",
    "search_past_conversations",
    "recall_conversation_details",
]
