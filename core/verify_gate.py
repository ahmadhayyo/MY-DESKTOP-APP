"""
core/verify_gate.py — Enforce the "verify" leg of explore → edit → verify.

Problem this solves
-------------------
The worker can edit a code file and the reviewer can then declare TASK_COMPLETE
without the change ever being *run*. That ships unverified edits — the exact
failure mode a Claude-Code-style loop avoids by always testing after editing.

Strategy
--------
Derive a "verification pending" signal purely from the existing
``tool_call_history`` (list of ``{"name", "args", "result", ...}`` dicts kept by
``core.deduplication.record_tool_call``) — no AgentState schema change:

  pending == the most recent *successful* code edit is NOT followed by any
             verification tool call.

Crucially the gate clears as soon as ANY verification tool fires after the edit,
whether it passed or failed. Its job is to guarantee the agent *runs* what it
edited — not to force a green result (a failing run is a real result the
reviewer/worker then acts on normally). This bounds the cost to at most one
forced verify step per edit and makes an infinite loop impossible.

Non-runnable edits (.html/.css/.json/.md/.txt/config) do NOT arm the gate —
verification only makes sense for runnable code.

Toggle: set env ``HAYO_VERIFY_GATE=0`` to disable entirely.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Tools that mutate runnable code and therefore should be verified afterwards.
CODE_EDIT_TOOLS = frozenset(
    {"edit_file_replace", "edit_file_lines", "write_file", "create_project"}
)

# Tools that count as "running / testing" the edited code. A conservative but
# practical set: the explicit run/test tools plus the shells (the worker prompt
# itself tells the model to verify via run_script/run_python).
VERIFY_TOOLS = frozenset(
    {
        "run_python",
        "run_script",
        "run_executable",
        "lint_python",
        "run_cmd",
        "run_powershell",
        "build_exe",
        "build_desktop_app",
    }
)

# Only runnable source files arm the gate. Markup/config/docs are excluded —
# there is nothing to "run" after editing them.
RUNNABLE_CODE_EXTS = frozenset(
    {
        ".py", ".pyw", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
        ".sh", ".bash", ".ps1", ".bat", ".cmd",
        ".rb", ".php", ".pl", ".lua",
        ".go", ".rs", ".java", ".kt", ".c", ".cpp", ".cc", ".h", ".hpp", ".cs",
    }
)


@dataclass
class VerifyGate:
    """Result of a verification-pending check over recent tool history."""

    pending: bool = False
    file: str = ""

    def __bool__(self) -> bool:  # allow `if gate:`
        return self.pending


def is_enabled() -> bool:
    """Gate honours HAYO_VERIFY_GATE (default on)."""
    return os.getenv("HAYO_VERIFY_GATE", "1").strip().lower() not in ("0", "false", "no", "off")


def _edit_path(entry: dict) -> str:
    args = entry.get("args", {}) if isinstance(entry, dict) else {}
    if not isinstance(args, dict):
        return ""
    for key in ("path", "file", "filepath", "file_path", "target"):
        val = args.get(key)
        if val:
            return str(val)
    return ""


def _ext(path: str) -> str:
    return os.path.splitext(str(path))[1].lower()


def _is_code_edit(entry: dict) -> bool:
    """True if this history entry is a successful edit of a runnable code file.

    Blocked/redirected/unknown attempts are recorded with prefixed names
    (``BLOCKED:edit_file_replace`` etc.) so an exact-name check excludes them.
    """
    if not isinstance(entry, dict):
        return False
    name = entry.get("name", "")
    if name not in CODE_EDIT_TOOLS:
        return False
    # create_project scaffolds a runnable project regardless of a single path.
    if name == "create_project":
        return True
    return _ext(_edit_path(entry)) in RUNNABLE_CODE_EXTS


def _edit_succeeded(entry: dict) -> bool:
    """A failed edit doesn't need verification — it needs re-editing.

    ``result`` is only the first ~100 chars (see record_tool_call); a failed edit
    is ❌-prefixed by convention, so this check is reliable on the truncated text.
    """
    res = entry.get("result")
    if not res:
        return True  # nothing recorded → assume the edit ran
    text = str(res).lstrip()
    low = text.lower()
    return not (text.startswith("❌") or "[error]" in low or "traceback" in low)


def _is_verify(entry: dict) -> bool:
    return isinstance(entry, dict) and entry.get("name", "") in VERIFY_TOOLS


def verification_pending(tool_history: list[dict] | None) -> VerifyGate:
    """Return whether the latest successful code edit still needs a run/test.

    pending is True iff a successful code edit exists and NO verification tool
    was called after it. Returns the edited file path for use in nudges.
    """
    if not is_enabled() or not tool_history:
        return VerifyGate()

    last_edit_idx = -1
    last_path = ""
    for i, entry in enumerate(tool_history):
        if _is_code_edit(entry) and _edit_succeeded(entry):
            last_edit_idx = i
            last_path = _edit_path(entry) or entry.get("name", "")

    if last_edit_idx == -1:
        return VerifyGate()

    for entry in tool_history[last_edit_idx + 1:]:
        if _is_verify(entry):
            return VerifyGate(pending=False, file=last_path)

    return VerifyGate(pending=True, file=last_path)


def generate_verify_nudge(gate: VerifyGate) -> str:
    """Guidance telling the model to run/test the file it just edited."""
    target = gate.file or "الملف الذي عدّلته"
    return (
        f"[VERIFY REQUIRED] عدّلت ملف كود ({target}) لكنك لم تُشغّله/تختبره بعد.\n"
        f"الخطوة الإلزامية التالية قبل إنهاء المهمة = تشغيله للتأكد أنه يعمل:\n"
        f"- بايثون: run_python(code='...') أو run_script(path='{target}')\n"
        f"- إن كان سكربت/تطبيق آخر: run_script / run_executable المناسب.\n"
        f"إن ظهر خطأ عند التشغيل، اقرأه وأصلح الملف ثم أعد التشغيل. "
        f"لا تُعلن اكتمال المهمة قبل تشغيل واحد ناجح على الأقل."
    )


# ══════════════════════════════════════════════════════════════════════════════
# VISUAL VERIFICATION GATE — the "look at it" leg of build → run → SEE → fix.
#
# verify_gate above forces a *run* after an edit. But a GUI/web app that runs
# without a crash can still be visually broken (blank window, misaligned layout,
# wrong colours, an error rendered on the page). A Claude-Code-style loop looks
# at the result. This gate forces exactly one visual analysis (analyze_screen /
# analyze_image) after a VISUAL artifact was run, then clears — bounded, no loop.
# ══════════════════════════════════════════════════════════════════════════════

# Tools that constitute a real visual inspection of the result.
VISUAL_ANALYZE_TOOLS = frozenset({"analyze_screen", "analyze_image"})

# Building/launching a desktop app is inherently visual.
VISUAL_BUILD_TOOLS = frozenset({"build_desktop_app"})

# Substrings that betray a GUI / web / rendered artifact in a run's args
# (the `code` of run_python, the `path`/`command` of run_script/shells, etc.).
_VISUAL_SIGNALS = (
    # python GUI toolkits
    "tkinter", "customtkinter", "pyqt", "pyside", "pygame", "kivy", "wx",
    "flet", "dearpygui", "pysimplegui", "toga",
    # web / server frameworks that render a page
    "streamlit", "gradio", "flask", "fastapi", "uvicorn", "dash",
    "http.server", "webview", "pywebview",
    # node / front-end launchers
    "npm run", "npm start", "yarn dev", "vite", "next dev",
    # a rendered page/file itself
    ".html", "index.html", "localhost:", "127.0.0.1:",
)


def visual_is_enabled() -> bool:
    """Honour HAYO_VISUAL_GATE (default on) AND require a vision provider.

    No point forcing a visual analysis the agent has no model to perform. If no
    vision key is configured, the gate stays dormant.
    """
    if os.getenv("HAYO_VISUAL_GATE", "1").strip().lower() in ("0", "false", "no", "off"):
        return False
    try:
        from core.vision_analyze import available_vision_providers
        return bool(available_vision_providers())
    except Exception:
        return False


def _run_args_blob(entry: dict) -> str:
    args = entry.get("args", {}) if isinstance(entry, dict) else {}
    if not isinstance(args, dict):
        return ""
    parts = []
    for key in ("code", "path", "file", "file_path", "command", "cmd", "script", "target"):
        val = args.get(key)
        if val:
            parts.append(str(val))
    return " ".join(parts).lower()


def _is_visual_run(entry: dict) -> bool:
    """True if this history entry is a SUCCESSFUL run of a visual artifact."""
    if not isinstance(entry, dict):
        return False
    name = entry.get("name", "")
    if name in VISUAL_BUILD_TOOLS:
        return _edit_succeeded(entry)  # reuse the ❌/error convention
    if name not in VERIFY_TOOLS:
        return False
    if not _edit_succeeded(entry):
        return False
    blob = _run_args_blob(entry)
    return any(sig in blob for sig in _VISUAL_SIGNALS)


def _is_visual_analyze(entry: dict) -> bool:
    return isinstance(entry, dict) and entry.get("name", "") in VISUAL_ANALYZE_TOOLS


def visual_verification_pending(tool_history: list[dict] | None) -> VerifyGate:
    """Return whether a run GUI/web artifact still needs a visual look.

    pending is True iff the latest successful *visual* run is NOT followed by any
    analyze_screen/analyze_image call. `file` carries a short hint of what ran.
    """
    if not visual_is_enabled() or not tool_history:
        return VerifyGate()

    last_run_idx = -1
    last_hint = ""
    for i, entry in enumerate(tool_history):
        if _is_visual_run(entry):
            last_run_idx = i
            last_hint = _run_args_blob(entry)[:80] or entry.get("name", "")

    if last_run_idx == -1:
        return VerifyGate()

    for entry in tool_history[last_run_idx + 1:]:
        if _is_visual_analyze(entry):
            return VerifyGate(pending=False, file=last_hint)

    return VerifyGate(pending=True, file=last_hint)


def generate_visual_nudge(gate: VerifyGate) -> str:
    """Guidance telling the model to VISUALLY inspect what it just launched."""
    target = gate.file or "التطبيق/الصفحة التي شغّلتها"
    return (
        f"[LOOK REQUIRED] شغّلت واجهة رسومية/صفحة ({target}) لكنك لم تنظر إليها بصرياً بعد.\n"
        "تشغيلها بلا خطأ لا يكفي — قد تكون فارغة أو مشوّهة أو بها خطأ ظاهر على الشاشة.\n"
        "الخطوة الإلزامية التالية قبل الإنهاء = رؤيتها فعلياً:\n"
        "- تأكد أن النافذة/المتصفح ظاهر (افتحه إن لزم) ثم استدعِ analyze_screen"
        "(question='هل ظهرت الواجهة صحيحة؟ هل توجد أخطاء بصرية أو عناصر ناقصة؟').\n"
        "- أو إن كانت لديك صورة محفوظة استخدم analyze_image(path=...).\n"
        "إن رأى النموذج خللاً، أصلح الكود ثم أعد التشغيل والنظر. "
        "لا تُعلن الاكتمال قبل فحص بصري واحد على الأقل."
    )


if __name__ == "__main__":  # Lightweight smoke test (no pytest dependency).
    # Edit with no following run → pending.
    h1 = [{"name": "read_file", "args": {"path": "main.py"}, "result": "..."},
          {"name": "edit_file_replace", "args": {"path": "main.py"}, "result": "[OK] edited"}]
    g1 = verification_pending(h1)
    assert g1.pending and g1.file == "main.py", g1

    # Edit then a run → cleared, even though we don't inspect the run's result.
    h2 = h1 + [{"name": "run_python", "args": {"code": "import main"}, "result": "❌ boom"}]
    assert not verification_pending(h2).pending, "any run after edit clears the gate"

    # Failed edit → not pending (needs re-edit, not a run).
    h3 = [{"name": "edit_file_replace", "args": {"path": "a.py"}, "result": "❌ Text not found"}]
    assert not verification_pending(h3).pending, "failed edit must not arm the gate"

    # Non-runnable file → not pending.
    h4 = [{"name": "write_file", "args": {"path": "notes.md"}, "result": "[OK] wrote"}]
    assert not verification_pending(h4).pending, "markdown edit must not arm the gate"

    # Blocked edit (prefixed name) → not pending.
    h5 = [{"name": "BLOCKED:edit_file_replace", "args": {"path": "a.py"}, "result": "⛔"}]
    assert not verification_pending(h5).pending, "blocked edit must not arm the gate"

    # Latest edit is what matters: edit A, run A, edit B (no run) → pending on B.
    h6 = [
        {"name": "edit_file_replace", "args": {"path": "a.py"}, "result": "[OK]"},
        {"name": "run_script", "args": {"path": "a.py"}, "result": "ok"},
        {"name": "edit_file_replace", "args": {"path": "b.py"}, "result": "[OK]"},
    ]
    g6 = verification_pending(h6)
    assert g6.pending and g6.file == "b.py", g6

    print("verify_gate smoke test OK")
