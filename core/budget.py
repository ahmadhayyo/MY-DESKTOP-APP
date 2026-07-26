"""
core/budget.py — a per-task token budget guard (spend cap).

The HackerAI reference caps how much a single agent run may spend so a stuck or
runaway task can't drain the account. HAYO's user is cost-constrained, so this is
a direct money protection: accumulate an estimate of the tokens consumed during a
task and, once a configurable ceiling is crossed, halt the loop cleanly with a
clear message instead of burning credit indefinitely.

This is intentionally provider-agnostic — it bounds *tokens*, not dollars, so it
needs no per-model price table. MAX_ITERATIONS already bounds turns; this bounds
the far more variable cost of large contexts / tool outputs within those turns.

Env:
  HAYO_TASK_TOKEN_BUDGET   total estimated tokens allowed per task.
                           Default 800000. Set 0 (or negative) to disable.
"""

from __future__ import annotations

import os
import threading

_lock = threading.RLock()
_USED: dict[str, int] = {}

_DEFAULT_BUDGET = 800_000


def budget_limit() -> int:
    """Configured per-task token ceiling (0/negative ⇒ disabled)."""
    try:
        return int(os.getenv("HAYO_TASK_TOKEN_BUDGET", str(_DEFAULT_BUDGET)))
    except (TypeError, ValueError):
        return _DEFAULT_BUDGET


def is_enabled() -> bool:
    return budget_limit() > 0


def reset(task_id: str) -> None:
    with _lock:
        _USED.pop(task_id or "default", None)


def add_tokens(task_id: str, tokens: int) -> int:
    """Add `tokens` to a task's running total. Returns the new total."""
    task_id = task_id or "default"
    if tokens < 0:
        tokens = 0
    with _lock:
        _USED[task_id] = _USED.get(task_id, 0) + int(tokens)
        return _USED[task_id]


def add_text(task_id: str, text: str) -> int:
    """Estimate the tokens in `text` and add them. Returns the new total."""
    try:
        from core.compaction import estimate_tokens
        toks = estimate_tokens(text or "")
    except Exception:
        toks = len(text or "") // 4
    return add_tokens(task_id, toks)


def used(task_id: str) -> int:
    with _lock:
        return _USED.get(task_id or "default", 0)


def remaining(task_id: str) -> int:
    lim = budget_limit()
    if lim <= 0:
        return -1  # unlimited
    return max(0, lim - used(task_id))


def over_budget(task_id: str) -> bool:
    lim = budget_limit()
    if lim <= 0:
        return False
    return used(task_id) >= lim


def pressure(task_id: str) -> float:
    """Fraction of the budget consumed (0..1+). 0 when disabled."""
    lim = budget_limit()
    if lim <= 0:
        return 0.0
    return used(task_id) / lim


def status(task_id: str) -> str:
    lim = budget_limit()
    if lim <= 0:
        return "budget: disabled"
    return f"budget: {used(task_id):,}/{lim:,} tokens ({pressure(task_id) * 100:.0f}%)"


if __name__ == "__main__":  # smoke test
    os.environ["HAYO_TASK_TOKEN_BUDGET"] = "1000"
    reset("j")
    add_tokens("j", 400)
    assert not over_budget("j")
    assert remaining("j") == 600, remaining("j")
    add_tokens("j", 700)
    assert over_budget("j"), status("j")
    os.environ["HAYO_TASK_TOKEN_BUDGET"] = "0"
    assert not over_budget("j") and not is_enabled()
    print("budget smoke OK")
