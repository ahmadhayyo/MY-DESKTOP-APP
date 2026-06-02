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
    return header + combined


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
