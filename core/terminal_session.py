"""
core/terminal_session.py — persistent, stateful shell sessions.

HAYO's normal run tools are one-shot: each command starts a fresh process, so a
`cd`, a venv activation, or an exported variable is lost on the next call. The
HackerAI reference keeps an interactive terminal alive across steps; this brings
the same to HAYO, which matters a lot when fixing a real project (activate the
venv once, stay in the project dir, keep environment across commands).

Design (Windows-safe, no hangs)
-------------------------------
Each session wraps a long-lived ``cmd.exe`` process with piped stdin/stdout. A
background reader thread drains stdout into a queue so we never block on a pipe.
To run a command and know when it finished, we append an ``echo <SENTINEL>`` that
prints a unique marker plus the exit code; we read until that marker appears (or a
per-command timeout elapses). State (cwd, env, activated venv) persists because
it's the same shell process the whole time.

Safety
------
* Every command has a timeout (default 60s). On timeout we return the partial
  output with ``timed_out=True`` instead of hanging forever.
* A command that never returns (e.g. a blocking server) would stall its session;
  callers should launch those detached (``start ...``). ``reset`` kills and
  respawns a wedged session.
"""

from __future__ import annotations

import os
import queue
import subprocess
import threading
import time
import uuid

_lock = threading.RLock()
_SESSIONS: dict[str, "_Session"] = {}

_DEFAULT_TIMEOUT = 60
_MAX_SESSIONS = 12

# Unique prompt marker so we can strip the shell prompt from captured output.
# cmd prints the prompt with no trailing newline, so it prefixes the next line.
_PROMPT_MARK = "HAYORDY"
_PROMPT_PREFIX = _PROMPT_MARK + ">"


class _Session:
    def __init__(self, session_id: str, cwd: str | None = None):
        self.id = session_id
        self.cwd = cwd or os.getcwd()
        self._q: "queue.Queue[str]" = queue.Queue()
        # Launch with the prompt marker + echo-off applied by /K itself, so it is
        # guaranteed active before any user command (writing it to stdin after
        # start proved unreliable). The unique prompt marker prefixes every output
        # line (cmd prints the prompt with no trailing newline) and we strip it.
        self._proc = subprocess.Popen(
            ["cmd.exe", "/Q", "/K", f"@echo off & prompt {_PROMPT_MARK}$G"],
            cwd=self.cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self._alive = True
        self._reader = threading.Thread(target=self._drain, daemon=True)
        self._reader.start()
        # Consume the startup banner.
        self._settle(0.4)

    def _drain(self):
        try:
            for line in self._proc.stdout:  # blocks in this thread only
                self._q.put(line)
        except Exception:
            pass
        finally:
            self._alive = False

    def _settle(self, seconds: float):
        end = time.time() + seconds
        while time.time() < end:
            try:
                self._q.get(timeout=max(0.0, end - time.time()))
            except queue.Empty:
                break

    def is_alive(self) -> bool:
        return self._alive and self._proc.poll() is None

    def run(self, command: str, timeout: int = _DEFAULT_TIMEOUT) -> dict:
        if not self.is_alive():
            return {"output": "", "exit_code": -1, "timed_out": False,
                    "error": "session not alive"}

        sentinel = f"__HAYO_END_{uuid.uuid4().hex}__"
        # Chain the sentinel with & so it runs regardless of the command's exit,
        # and capture the command's errorlevel.
        payload = f"{command}\r\n echo {sentinel}:%ERRORLEVEL%\r\n"
        try:
            self._proc.stdin.write(payload)
            self._proc.stdin.flush()
        except Exception as exc:
            self._alive = False
            return {"output": "", "exit_code": -1, "timed_out": False,
                    "error": f"write failed: {exc}"}

        lines: list[str] = []
        exit_code = 0
        timed_out = True
        deadline = time.time() + max(1, timeout)
        while time.time() < deadline:
            try:
                line = self._q.get(timeout=min(0.5, max(0.0, deadline - time.time())))
            except queue.Empty:
                continue
            # Strip the shell prompt marker that prefixes lines (no trailing NL).
            clean = line.replace(_PROMPT_PREFIX, "").rstrip("\r\n")
            if sentinel in clean:
                # marker line looks like "__HAYO_END_xxx__:0"
                try:
                    exit_code = int(clean.strip().split(":")[-1])
                except (ValueError, IndexError):
                    exit_code = 0
                timed_out = False
                break
            lines.append(clean)

        return {
            "output": "\n".join(lines).strip(),
            "exit_code": exit_code,
            "timed_out": timed_out,
            "error": "",
        }

    def close(self):
        self._alive = False
        try:
            if self._proc.poll() is None:
                self._proc.stdin.write("exit\r\n")
                self._proc.stdin.flush()
        except Exception:
            pass
        try:
            self._proc.terminate()
        except Exception:
            pass


# ── registry ──────────────────────────────────────────────────────────────────

def get_or_create(session_id: str = "default", cwd: str | None = None) -> _Session:
    with _lock:
        s = _SESSIONS.get(session_id)
        if s is not None and s.is_alive():
            return s
        if s is not None:
            s.close()
        if len(_SESSIONS) >= _MAX_SESSIONS:
            # evict the oldest dead-or-any session
            old_id = next(iter(_SESSIONS))
            _SESSIONS.pop(old_id).close()
        s = _Session(session_id, cwd=cwd)
        _SESSIONS[session_id] = s
        return s


def run_in_session(command: str, session_id: str = "default",
                   cwd: str | None = None, timeout: int = _DEFAULT_TIMEOUT) -> dict:
    s = get_or_create(session_id, cwd=cwd)
    return s.run(command, timeout=timeout)


def reset_session(session_id: str = "default") -> bool:
    with _lock:
        s = _SESSIONS.pop(session_id, None)
        if s is not None:
            s.close()
            return True
        return False


def list_sessions() -> list[str]:
    with _lock:
        return [sid for sid, s in _SESSIONS.items() if s.is_alive()]


def close_all():
    with _lock:
        for s in list(_SESSIONS.values()):
            s.close()
        _SESSIONS.clear()


if __name__ == "__main__":  # smoke test (no external deps, bounded)
    r1 = run_in_session("cd", session_id="t")          # print cwd
    print("cwd:", r1["output"], "| exit:", r1["exit_code"])
    run_in_session("set HAYO_TEST=hello", session_id="t")
    r2 = run_in_session("echo %HAYO_TEST%", session_id="t")   # state persists!
    print("persisted var:", repr(r2["output"]))
    assert r2["output"] == "hello", r2
    r3 = run_in_session("cmd /c exit 3", session_id="t")  # set errorlevel, keep session
    print("exit code capture:", r3["exit_code"])
    assert r3["exit_code"] == 3, r3
    r4 = run_in_session("echo still-alive", session_id="t")  # session survived
    assert r4["output"] == "still-alive", r4
    reset_session("t")
    print("terminal_session smoke OK")
