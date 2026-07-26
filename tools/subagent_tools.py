"""
Sub-agent tool — delegate a focused subtask to an isolated mini-agent.

Use spawn_subagent when a subtask is self-contained and would clutter the main
plan: a focused search, generating + running a batch of tests, gathering facts,
etc. The sub-agent runs its own short tool-loop and returns just a summary, so
the main agent's context stays clean.
"""

from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool

from core import subagent as _subagent


@tool
def spawn_subagent(
    task: Annotated[str, "The self-contained subtask for the sub-agent to do, described clearly."],
    max_steps: Annotated[int, "Max tool steps the sub-agent may take (default 6, max 15)."] = 6,
    context: Annotated[str, "Optional context the sub-agent needs (paths, prior findings)."] = "",
) -> str:
    """Delegate a focused subtask to an isolated sub-agent; returns its summary.

    Good for work that is self-contained and shouldn't clutter the main plan.
    The sub-agent has the full toolset (except spawning further sub-agents) and
    is bounded by max_steps so it can't run away.
    """
    try:
        return _subagent.run_subagent(task, max_steps=max_steps, context=context)
    except Exception as exc:
        return f"❌ spawn_subagent: {exc}"
