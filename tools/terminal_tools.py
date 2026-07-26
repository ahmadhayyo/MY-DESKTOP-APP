"""
Terminal Session Tools — persistent, stateful shell for the HAYO agent.

Unlike the one-shot run_cmd/run_powershell tools, a terminal session keeps the
SAME shell alive across calls, so working directory, environment variables, and
an activated virtualenv all persist. Ideal for fixing a real project:
  terminal_run("cd C:\\proj")                → stay there
  terminal_run("venv\\Scripts\\activate")    → venv stays active
  terminal_run("pip install -r requirements.txt")
  terminal_run("python app.py")              → same env every time
"""

from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool

from core import terminal_session as _ts


@tool
def terminal_run(
    command: Annotated[str, "The shell command to run in the persistent session."],
    session_id: Annotated[str, "Session name. Reuse the same name to keep state (cwd/env/venv)."] = "main",
    timeout: Annotated[int, "Seconds to wait for the command to finish (default 60)."] = 60,
) -> str:
    """Run a command in a PERSISTENT shell session (state survives between calls).

    Use this instead of run_cmd when you need cwd/env/venv to persist across
    steps. For a long-running/blocking process (a server, a GUI app) launch it
    detached with `start ...` so it does not block the session.
    """
    try:
        res = _ts.run_in_session(command, session_id=session_id, timeout=int(timeout))
        out = res.get("output", "")
        code = res.get("exit_code", 0)
        if res.get("error"):
            return f"❌ terminal_run: {res['error']} (session '{session_id}')"
        header = f"[session:{session_id} exit:{code}]"
        if res.get("timed_out"):
            header = (f"[session:{session_id} ⏱️ TIMEOUT after {timeout}s — "
                      f"command may still be running; use terminal_reset if stuck]")
        body = out if out else "(لا مخرجات)"
        return f"{header}\n{body}"
    except Exception as exc:
        return f"❌ terminal_run: {exc}"


@tool
def terminal_reset(
    session_id: Annotated[str, "Session name to kill and restart fresh."] = "main",
) -> str:
    """Kill and restart a persistent terminal session (use if it got stuck)."""
    try:
        existed = _ts.reset_session(session_id)
        return (f"[OK] أُعيد ضبط الجلسة '{session_id}'."
                if existed else f"[OK] لا توجد جلسة '{session_id}' نشطة (ستُنشأ عند أول أمر).")
    except Exception as exc:
        return f"❌ terminal_reset: {exc}"
