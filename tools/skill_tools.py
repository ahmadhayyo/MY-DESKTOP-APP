"""
Skill Tools — load reusable methodology packages (Claude-Code-style skills).

When facing a class of task (fix a project, build a desktop app, research the web),
the agent can load a proven recipe instead of improvising. list_skills shows what's
available; load_skill pulls the full methodology into context.
"""

from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool

from core import skills as _skills


@tool
def list_skills() -> str:
    """List the available skills (reusable task methodologies) by name + description."""
    try:
        return _skills.render_index()
    except Exception as exc:
        return f"❌ list_skills: {exc}"


@tool
def load_skill(
    name: Annotated[str, "The skill name to load, e.g. 'fix-project' or 'build-desktop-app'."],
) -> str:
    """Load a skill's full step-by-step methodology to follow for the current task."""
    try:
        s = _skills.get_skill(name)
        if not s:
            avail = ", ".join(sk.name for sk in _skills.load_all()) or "(لا توجد)"
            return f"❌ لا توجد مهارة باسم '{name}'. المتاح: {avail}"
        return f"🧩 مهارة: {s.name}\n{s.description}\n\n{s.body}"
    except Exception as exc:
        return f"❌ load_skill: {exc}"
