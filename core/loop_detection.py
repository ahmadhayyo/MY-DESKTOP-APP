"""
core/loop_detection.py — Doom-loop detection for the agent worker loop.

Ported and adapted from HackerAI's `lib/chat/doom-loop-detection.ts`
(inspired by OpenCode PR #3445), tailored to this project's LangGraph
`tool_call_history` structure (a list of {"name", "args", ...} dicts kept by
`core.deduplication.record_tool_call`).

Why this is stronger than the existing `is_duplicate_tool_call` check:
  - `is_duplicate_tool_call` only looks at the *last 2* calls and only prevents
    the immediate re-execution of one tool. It does not measure how *long* the
    agent has been stuck, and cannot escalate.
  - This module measures the *trailing run* of functionally-identical tool calls
    and returns a graded severity:
        • warning  (>= LOOP_WARNING_THRESHOLD): inject a "try a different
          approach" nudge into the worker's next LLM call.
        • halt     (>= LOOP_HALT_THRESHOLD):    end the run cleanly instead of
          burning the remaining MAX_ITERATIONS on a hopeless loop.

Fingerprint design:
  - Cosmetic fields that change every call even when the functional arguments are
    identical (``brief``/``explanation``/``thought``/``reasoning``) are stripped
    before fingerprinting, so a re-worded one-line summary never hides a loop.
  - The fingerprint includes the *arguments*, so legitimately-repeated
    exploration (``read_file('a')`` then ``read_file('b')``) has different
    fingerprints and correctly does NOT count as a loop. Only identical
    name+args repeats accumulate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

try:  # Tunables live in config; fall back to sane defaults if unavailable.
    from config import LOOP_WARNING_THRESHOLD, LOOP_HALT_THRESHOLD
except Exception:  # pragma: no cover - config import guard
    LOOP_WARNING_THRESHOLD = 3
    LOOP_HALT_THRESHOLD = 5


# Fields that are purely cosmetic / user-facing and change per call even when the
# functional arguments are identical. Stripped before fingerprinting.
_COSMETIC_FIELDS = frozenset({"brief", "explanation", "thought", "reasoning", "_note"})

# Read-only exploration tools legitimately repeat (with different args) during
# project discovery, so they are excluded from the error-thrash signal.
_EXPLORATION_TOOLS = frozenset(
    {"read_file", "list_dir", "recall_facts", "search_files", "list_memory", "recall"}
)

# Substrings in a tool result that indicate the call failed. Used only by the
# WARNING-tier error-thrash detector — never by the halt path.
_ERROR_MARKERS = (
    "❌", "error", "failed", "not found", "text not found", "traceback",
    "exception", "cannot access", "denied", "no such", "does not exist",
    "[tool result missing", "invalid",
)

LoopSeverity = Literal["none", "warning", "halt"]


@dataclass
class LoopResult:
    """Outcome of a doom-loop check over the recent tool-call history."""

    severity: LoopSeverity = "none"
    tool_names: list[str] = field(default_factory=list)
    count: int = 0
    reason: str = ""

    @property
    def is_halt(self) -> bool:
        return self.severity == "halt"

    @property
    def is_warning(self) -> bool:
        return self.severity == "warning"


def _strip_cosmetic(args: Any) -> Any:
    """Remove cosmetic fields from a tool-args mapping before fingerprinting."""
    if not isinstance(args, dict):
        return args
    return {k: v for k, v in args.items() if k not in _COSMETIC_FIELDS}


def _fingerprint(entry: dict) -> str:
    """Deterministic fingerprint of a single tool-call history entry.

    Entries with no usable tool name return a sentinel that breaks any run.
    """
    name = entry.get("name") if isinstance(entry, dict) else None
    if not name:
        return "__no_tool__"
    args = _strip_cosmetic(entry.get("args", {}) if isinstance(entry, dict) else {})
    try:
        args_repr = json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        args_repr = repr(args)
    return f"{name}::{args_repr}"


def detect_loop(
    tool_history: list[dict] | None,
    *,
    warning_threshold: int = LOOP_WARNING_THRESHOLD,
    halt_threshold: int = LOOP_HALT_THRESHOLD,
) -> LoopResult:
    """Detect a doom loop by counting trailing identical tool-call fingerprints.

    Args:
        tool_history: The state's ``tool_call_history`` (newest last).
        warning_threshold: Trailing-identical count that triggers a warning.
        halt_threshold: Trailing-identical count that triggers a halt.

    Returns:
        A :class:`LoopResult`. ``severity == "none"`` when no loop is detected.
    """
    if not tool_history:
        return LoopResult()

    last_fp = _fingerprint(tool_history[-1])
    if last_fp == "__no_tool__":
        return LoopResult()

    count = 1
    for entry in reversed(tool_history[:-1]):
        if _fingerprint(entry) == last_fp:
            count += 1
        else:
            break

    if count < warning_threshold:
        return LoopResult(count=count)

    tool_name = tool_history[-1].get("name", "") if isinstance(tool_history[-1], dict) else ""
    severity: LoopSeverity = "halt" if count >= halt_threshold else "warning"
    return LoopResult(
        severity=severity,
        tool_names=[tool_name] if tool_name else [],
        count=count,
        reason="repeated_tool_call",
    )


def _is_error_result(result: object) -> bool:
    """True if a tool result string looks like a failure."""
    if not result:
        return False
    text = str(result).lower()
    return any(marker in text for marker in _ERROR_MARKERS)


def detect_error_thrash(
    tool_history: list[dict] | None,
    *,
    window: int = 4,
    min_errors: int = 2,
) -> LoopResult:
    """Detect the model retrying ONE non-exploration tool with varying args while
    its results keep failing (e.g. edit_file_replace missing its target text).

    This is a WARNING-only signal — it never halts. The point is to inject a
    "read the error and change approach" nudge, not to stop a legitimate task.
    Requires the trailing ``window`` calls to target the same non-exploration
    tool with at least ``min_errors`` failing results among them, and the args
    to NOT be all identical (that case is already covered by :func:`detect_loop`).
    """
    if not tool_history or len(tool_history) < window:
        return LoopResult()

    tail = tool_history[-window:]
    names = {e.get("name") for e in tail if isinstance(e, dict)}
    if len(names) != 1:
        return LoopResult()
    (name,) = tuple(names)
    if not name or name in _EXPLORATION_TOOLS:
        return LoopResult()

    fingerprints = {_fingerprint(e) for e in tail}
    if len(fingerprints) == 1:
        # All identical — detect_loop already owns this case.
        return LoopResult()

    error_count = sum(1 for e in tail if _is_error_result(e.get("result")))
    if error_count < min_errors:
        return LoopResult()

    return LoopResult(
        severity="warning",
        tool_names=[name],
        count=window,
        reason="error_thrash",
    )


def generate_loop_nudge(result: LoopResult, last_error: str | None = None) -> str:
    """Build a guidance message to steer the model out of a detected loop.

    Written in Arabic (the agent's primary working language) with an English
    bracket tag so it is unmistakable in logs and to the model. When
    ``last_error`` is provided, it is surfaced so the model can react to the
    concrete failure instead of guessing.
    """
    tools = "، ".join(result.tool_names) if result.tool_names else "نفس الأداة"
    error_line = (
        f"\nآخر خطأ مسجّل:\n{str(last_error)[:400]}\n" if last_error else ""
    )

    if result.reason == "error_thrash":
        return (
            f"[REPEATED FAILURE] استدعيت ({tools}) {result.count} مرات بوسائط مختلفة "
            f"لكنها تفشل تكراراً.{error_line}"
            f"توقّف عن التخمين وغيّر النهج جذرياً:\n"
            f"- إن كنت تعدّل ملفاً وتفشل مطابقة النص، أعد قراءة الملف بالكامل "
            f"(read_file) وانسخ النص المستهدف حرفياً قبل التعديل.\n"
            f"- تحقّق من المسار والصلاحيات وصياغة الأمر.\n"
            f"- إن استمر الفشل، لخّص السبب واطلب توجيهاً من المستخدم بدل التكرار."
        )

    return (
        f"[LOOP DETECTED] لقد استدعيت ({tools}) {result.count} مرات متتالية بنفس "
        f"الوسائط تماماً دون تقدّم حقيقي. أنت عالق في حلقة.{error_line}"
        f"يجب أن تُغيّر النهج الآن:\n"
        f"- إن كان أمرٌ أو أداةٌ تفشل تكراراً، اقرأ رسالة الخطأ بدقّة وعدّل استراتيجيتك.\n"
        f"- جرّب وسائط مختلفة، أو أداة مختلفة، أو طريقة مختلفة كلياً لتحقيق الهدف.\n"
        f"- إن لم تستطع التقدّم، لخّص ما جرّبته واطلب توجيهاً من المستخدم.\n"
        f"لا تُكرّر نفس الاستدعاء مرة أخرى."
    )


if __name__ == "__main__":  # Lightweight smoke test (no pytest dependency).
    h = [{"name": "run_powershell", "args": {"command": "ls"}} for _ in range(5)]
    r = detect_loop(h)
    assert r.severity == "halt" and r.count == 5, r
    h2 = [
        {"name": "read_file", "args": {"path": "a"}},
        {"name": "read_file", "args": {"path": "b"}},
        {"name": "read_file", "args": {"path": "c"}},
    ]
    assert detect_loop(h2).severity == "none", "distinct args must not loop"
    print("loop_detection smoke test OK")
