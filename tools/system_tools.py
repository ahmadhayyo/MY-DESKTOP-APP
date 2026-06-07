"""
System-level tools: shell command execution.

Every shell call goes through `run_powershell` which:
  1. Runs the safety guard (DESTRUCTIVE_PATTERNS).
  2. Returns a structured dict (stdout, stderr, returncode, truncated).
  3. Caps output to MAX_OUTPUT_CHARS so the LLM doesn't drown.

Tools are exposed via @tool so LangGraph can bind them to the model.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Annotated

from langchain_core.tools import tool

from config import PS_TIMEOUT, DESKTOP_DIR, DEFAULT_WORKSPACE
from core.safety import needs_human_approval, redact_secrets

logger = logging.getLogger("hayo.tools.system")

MAX_OUTPUT_CHARS = 8000  # truncation budget per call


def _truncate(text: str) -> tuple[str, bool]:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text, False
    half = MAX_OUTPUT_CHARS // 2
    head = text[:half]
    tail = text[-half:]
    return f"{head}\n\n...[TRUNCATED {len(text) - MAX_OUTPUT_CHARS} chars]...\n\n{tail}", True


def _resolve_workdir(workdir: str) -> str:
    """Resolve working directory with support for shortcuts like 'desktop:' and '~'."""
    w = workdir.strip()
    if not w or w == ".":
        return str(DEFAULT_WORKSPACE)
    if w.lower() in ("desktop", "desktop:"):
        return str(DESKTOP_DIR)
    expanded = os.path.expandvars(os.path.expanduser(w))
    return os.path.abspath(expanded)


@tool
def run_powershell(
    command: Annotated[str, "The exact PowerShell command to execute on the user's Windows machine."],
    workdir: Annotated[str, "Working directory. Use '.' for current, 'desktop:' for Desktop."] = ".",
) -> str:
    """
    Run a PowerShell command and return combined stdout+stderr.

    Use this for: file listings, git operations, package installs, system info,
    creating folders, copying files, running Python scripts, npm/pip commands, etc.

    For destructive commands (rm -rf, format, shutdown, registry deletes) the
    request will be flagged for human approval before execution.

    Examples:
      run_powershell('Get-ChildItem') → list current directory
      run_powershell('python script.py', workdir='C:/Projects/myapp')
      run_powershell('npm install', workdir='C:/Projects/myapp')
      run_powershell('git status', workdir='desktop:MyProject')
    """
    needs_approval, pattern = needs_human_approval(command)
    if needs_approval:
        return (
            f"__HITL_REQUIRED__\nMatched destructive pattern: '{pattern}'\n"
            f"Command: {command}\n"
            f"Workdir: {workdir}\n"
            f"Awaiting human approval before execution."
        )

    resolved_dir = _resolve_workdir(workdir)
    if not os.path.isdir(resolved_dir):
        return f"[ERROR] Working directory does not exist: {resolved_dir}"

    logger.info("PS> %s (cwd=%s)", command[:200], resolved_dir)

    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            cwd=resolved_dir,
            capture_output=True,
            text=True,
            timeout=PS_TIMEOUT,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return f"[TIMEOUT after {PS_TIMEOUT}s] Command: {command}"
    except FileNotFoundError:
        return "[ERROR] powershell.exe not found. Is this Windows?"
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"

    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    combined = stdout
    if stderr:
        combined += f"\n[STDERR]\n{stderr}"

    combined, truncated = _truncate(combined)
    combined = redact_secrets(combined)

    header = f"[exit={completed.returncode}{' truncated' if truncated else ''}]\n"
    result = header + combined

    # ── Auto screen-check after app launch commands ───────────────────────────
    # If the command launched an app (Start-Process or explorer.exe shell:AppsFolder),
    # automatically wait and describe the screen so the agent always sees what opened.
    _is_launch_cmd = any(kw in command for kw in [
        "Start-Process", "shell:AppsFolder", "start-process",
    ])
    if _is_launch_cmd and completed.returncode == 0:
        try:
            import time as _time
            import pyautogui as _pag
            import pygetwindow as _gw

            _time.sleep(3.5)   # let the app window appear

            # Take screenshot + native OCR
            shot = _pag.screenshot()
            active = _gw.getActiveWindowTitle() or "(غير معروف)"
            screen_text = ""
            try:
                from tools.ocr_engine import ocr_text as _ocr_text_fn
                screen_text = _ocr_text_fn(shot)
                clean = "\n".join(l for l in screen_text.splitlines() if l.strip())[:500]
                if not clean.strip():
                    clean = "(لم يُقرأ نص)"
            except Exception:
                clean = "(OCR غير متاح)"

            # CAPTCHA detection — high-precision phrases only (no false positives
            # from ordinary words like "verify"/"robot"). Informational, never a
            # HITL trigger: this auto-screenshot fires after EVERY launch command,
            # so it must not hijack unrelated tasks because a stale window is open.
            captcha_kws = ['recaptcha', 'hcaptcha', 'i am not a robot',
                           "i'm not a robot", 'verify you are human', 'لست روبوت']
            captcha_hit = next((k for k in captcha_kws if k in screen_text.lower()), None)

            # Title-based Cloudflare detection (reliable even if OCR empty)
            _cf_title_kws = ['لحظة', 'just a moment', 'checking your browser',
                             'moment...', 'cloudflare', 'verifying']
            cf_title_hit = next((k for k in _cf_title_kws if k in active.lower()), None)

            screen_section = (
                f"\n\n📸 [تحقق تلقائي بعد الإطلاق]\n"
                f"النافذة النشطة: «{active}»\n"
                f"الشاشة تُظهر:\n{clean}"
            )
            if cf_title_hit:
                screen_section += (
                    f"\n\n🛡️ شاشة تحقق Cloudflare مكتشفة من العنوان («{cf_title_hit}»)."
                    f"\n   إن كانت مهمتك الحالية تتطلب هذا التطبيق: "
                    f"handle_verification_screen(timeout_seconds=90)"
                )
            elif captcha_hit:
                screen_section += (
                    f"\n\nℹ️ ملاحظة: يبدو وجود CAPTCHA على الشاشة (عبارة: «{captcha_hit}»)."
                    f"\n   إن كانت مهمتك تتطلب تجاوزه: handle_verification_screen(timeout_seconds=90)."
                )
            result += screen_section
        except Exception as _e:
            result += f"\n\n📸 [تحقق تلقائي]: تعذر ({_e})"

    return result


@tool
def run_cmd(
    command: Annotated[str, "The exact CMD command to run."],
    workdir: Annotated[str, "Working directory. Use '.' for current, 'desktop:' for Desktop."] = ".",
) -> str:
    """
    Run a classic Windows CMD command. Prefer run_powershell for most things.
    Use this only when a tool truly needs cmd.exe (e.g. legacy .bat files).

    Examples:
      run_cmd('dir', workdir='C:/Projects')
      run_cmd('npm run build', workdir='C:/Projects/myapp')
    """
    needs_approval, pattern = needs_human_approval(command)
    if needs_approval:
        return (
            f"__HITL_REQUIRED__\nMatched destructive pattern: '{pattern}'\n"
            f"Command: {command}\n"
        )

    resolved_dir = _resolve_workdir(workdir)
    if not os.path.isdir(resolved_dir):
        return f"[ERROR] Working directory does not exist: {resolved_dir}"

    logger.info("CMD> %s (cwd=%s)", command[:200], resolved_dir)

    try:
        completed = subprocess.run(
            ["cmd.exe", "/C", command],
            cwd=resolved_dir,
            capture_output=True,
            text=True,
            timeout=PS_TIMEOUT,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return f"[TIMEOUT after {PS_TIMEOUT}s]"
    except FileNotFoundError:
        return "[ERROR] cmd.exe not found. Is this Windows?"
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"

    out = (completed.stdout or "") + (
        f"\n[STDERR]\n{completed.stderr}" if completed.stderr else ""
    )
    out, _ = _truncate(out)
    return f"[exit={completed.returncode}]\n{redact_secrets(out)}"


@tool
def get_env(name: Annotated[str, "Environment variable name."]) -> str:
    """Read a single Windows environment variable. Returns empty string if missing."""
    return os.environ.get(name, "")
