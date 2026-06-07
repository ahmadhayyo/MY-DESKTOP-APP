"""
memory_facts_tools.py — Long-term memory tools (the agent's notebook).

These let the agent durably remember facts across sessions: user preferences,
recurring details, project paths, "always do X", people, credentials hints, etc.
Unlike conversation history (which gets summarized away), these persist forever
in a human-readable JSON file the user can inspect or edit.

Tools:
  • remember_fact(key, value, category, tags)  — save/update a fact
  • recall_facts(query, category)              — search remembered facts
  • forget_fact(key)                           — delete a fact
  • list_memory(category)                      — list everything remembered
"""
from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool

from core import long_term_memory as ltm


@tool
def remember_fact(
    key: Annotated[str, "Short label for the fact, e.g. 'user's main project path' or 'preferred download folder'."],
    value: Annotated[str, "The information to remember, e.g. 'C:/Projects/Shop' or 'always save songs to Desktop'."],
    category: Annotated[str, "Group: 'preference', 'project', 'person', 'credential', 'path', 'general'."] = "general",
    tags: Annotated[str, "Optional comma-separated tags to aid later search, e.g. 'work,urgent'."] = "",
) -> str:
    """
    Durably remember a fact ACROSS sessions (survives restarts and history pruning).

    Use this whenever the user tells you something worth keeping: a preference,
    a recurring path, a person's details, how they like things done, project
    context, etc. Recall it later with recall_facts().

    Examples:
      remember_fact(key='preferred music folder', value='C:/Users/PT/Music', category='path')
      remember_fact(key='always reply in Arabic', value='yes', category='preference')
      remember_fact(key="mother's medication reminder", value='9am and 9pm daily', category='general', tags='health')
    """
    try:
        tag_list = [t for t in (tags or "").split(",") if t.strip()]
        fact = ltm.remember(key=key, value=value, category=category, tags=tag_list)
        return (
            f"🧠 تم الحفظ في الذاكرة الدائمة:\n"
            f"   • {fact['display_key']} = {fact['value']}\n"
            f"   • التصنيف: {fact['category']}"
            + (f" | الوسوم: {', '.join(fact['tags'])}" if fact['tags'] else "")
        )
    except Exception as exc:
        return f"❌ تعذر حفظ الفكرة: {exc}"


@tool
def recall_facts(
    query: Annotated[str, "What to look for, e.g. 'music folder' or 'mother'. Leave empty to list recent facts."] = "",
    category: Annotated[str, "Optional: limit to one category (preference/project/person/path/...)."] = "",
) -> str:
    """
    Recall facts you remembered earlier (across all past sessions).

    Call this at the START of a task when you might already know something useful
    — the user's preferences, a path, how they like things done — instead of asking
    them again. Searches keys, values, tags and categories.

    Examples:
      recall_facts(query='download folder')
      recall_facts(category='preference')
      recall_facts()                       # most recent facts
    """
    try:
        results = ltm.recall(query=query, category=category, limit=12)
        if not results:
            scope = f"«{query}»" if query else (f"التصنيف «{category}»" if category else "الذاكرة")
            return f"🧠 لا توجد معلومات محفوظة عن {scope}."
        lines = [f"🧠 ما أتذكره ({len(results)} عنصر):"]
        for f in results:
            tagstr = f" [{', '.join(f['tags'])}]" if f.get("tags") else ""
            lines.append(f"  • ({f['category']}) {f['display_key']} = {f['value']}{tagstr}")
        return "\n".join(lines)
    except Exception as exc:
        return f"❌ تعذر استرجاع الذاكرة: {exc}"


@tool
def forget_fact(
    key: Annotated[str, "The label of the fact to delete (as it was remembered)."],
) -> str:
    """
    Forget (delete) a previously remembered fact. Use when info becomes outdated
    or the user asks you to forget something.

    Example: forget_fact(key='old project path')
    """
    try:
        ok = ltm.forget(key)
        return f"🗑️ تم نسيان «{key}»." if ok else f"ℹ️ لا يوجد فكرة محفوظة باسم «{key}»."
    except Exception as exc:
        return f"❌ تعذر النسيان: {exc}"


@tool
def list_memory(
    category: Annotated[str, "Optional: show only one category. Empty = everything."] = "",
) -> str:
    """
    List everything in long-term memory (optionally filtered by category).
    Useful to review what the agent knows about the user.

    Example: list_memory()  or  list_memory(category='preference')
    """
    try:
        facts = ltm.all_facts(category=category)
        st = ltm.stats()
        if not facts:
            return f"🧠 الذاكرة الدائمة فارغة.\n   الملف: {st['path']}"
        lines = [f"🧠 الذاكرة الدائمة ({st['total']} عنصر) — {st['path']}"]
        cur_cat = None
        for f in facts:
            if f["category"] != cur_cat:
                cur_cat = f["category"]
                lines.append(f"\n📂 {cur_cat}:")
            tagstr = f" [{', '.join(f['tags'])}]" if f.get("tags") else ""
            lines.append(f"  • {f['display_key']} = {f['value']}{tagstr}")
        return "\n".join(lines)
    except Exception as exc:
        return f"❌ تعذر عرض الذاكرة: {exc}"
