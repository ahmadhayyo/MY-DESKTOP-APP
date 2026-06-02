"""
Application tools: open / close / list / focus Windows apps.

Strategy for `open_app`:
  1. Try `os.startfile(name)` — handles Start-menu shortcuts and registered apps.
  2. Try plain `name` via subprocess (works for things on PATH like notepad, code).
  3. Try common-name → exe map below as fallback.
  4. Last resort: PowerShell `Start-Process` which handles UWP apps via shell:AppsFolder.

`focus_window` uses pygetwindow to bring an existing window forward.
"""

from __future__ import annotations

import os
import subprocess
import time
from typing import Annotated

from langchain_core.tools import tool

# Friendly aliases — extend freely. Lowercase keys, executable or shell: command as value.
APP_ALIASES: dict[str, str] = {
    "chrome": "chrome.exe",
    "edge": "msedge.exe",
    "firefox": "firefox.exe",
    "brave": "brave.exe",
    "notepad": "notepad.exe",
    "wordpad": "wordpad.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "explorer": "explorer.exe",
    "file explorer": "explorer.exe",
    "cmd": "cmd.exe",
    "powershell": "powershell.exe",
    "terminal": "wt.exe",  # Windows Terminal
    "vscode": "code",
    "code": "code",
    "vs code": "code",
    "word": "winword.exe",
    "excel": "excel.exe",
    "powerpoint": "powerpnt.exe",
    "outlook": "outlook.exe",
    "paint": "mspaint.exe",
    "snipping tool": "snippingtool.exe",
    "task manager": "taskmgr.exe",
    "control panel": "control.exe",
    "settings": "ms-settings:",
    "store": "ms-windows-store:",
    "spotify": "spotify.exe",
    "discord": "discord.exe",
    "slack": "slack.exe",
    "teams": "ms-teams.exe",
    "zoom": "zoom.exe",
    "telegram": "telegram.exe",
    "whatsapp": "whatsapp:",
    "vlc": "vlc.exe",
    "obs": "obs64.exe",
}


def _try_startfile(target: str) -> tuple[bool, str]:
    try:
        os.startfile(target)  # type: ignore[attr-defined]
        return True, f"os.startfile('{target}')"
    except Exception as exc:
        return False, f"os.startfile failed: {exc}"


def _try_popen(target: str) -> tuple[bool, str]:
    try:
        subprocess.Popen(target, shell=True)
        return True, f"subprocess('{target}')"
    except Exception as exc:
        return False, f"subprocess failed: {exc}"


@tool
def open_app(
    name: Annotated[
        str,
        "App name. Accepts friendly names (chrome, vscode, word, settings) or exe paths.",
    ],
    app_args: Annotated[str, "Optional arguments passed to the app."] = "",
) -> str:
    """
    Launch a desktop application on Windows.

    Examples:
      open_app('chrome')
      open_app('notepad', 'C:/notes.txt')
      open_app('vscode', 'C:/HAYO AI AGENT')
      open_app('settings')                  # opens Windows Settings UWP
      open_app('C:/Tools/MyApp/app.exe')
    """
    key = name.strip().lower()
    target = APP_ALIASES.get(key, name.strip())
    full = f'{target} {app_args}'.strip() if app_args else target

    # 1) os.startfile is the most permissive — it accepts paths, urls,
    #    Start-Menu names, and ms-* protocol URIs.
    if not app_args:
        ok, info = _try_startfile(target)
        if ok:
            return f"[OK] Launched '{name}' via {info}"

    # 2) Popen via shell handles things on PATH and quoted command lines.
    ok, info = _try_popen(full)
    if ok:
        return f"[OK] Launched '{name}' via {info}"

    # 3) Last resort: powershell Start-Process
    try:
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-Command", f"Start-Process '{target}' '{app_args}'"],
            shell=False,
        )
        return f"[OK] Launched '{name}' via Start-Process"
    except Exception as exc:
        return f"[ERROR] Could not launch '{name}': {exc}"


@tool
def close_app(
    name: Annotated[str, "Process name without .exe (e.g. 'chrome', 'notepad')."],
    force: Annotated[bool, "Force kill if normal close fails."] = True,
) -> str:
    """Close a running application by process name."""
    proc = name.strip()
    if not proc.lower().endswith(".exe"):
        proc = proc + ".exe"
    flag = "/F" if force else ""
    cmd = f'taskkill {flag} /IM "{proc}" /T'
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15, shell=True
        )
        out = (result.stdout or "") + (result.stderr or "")
        return f"[exit={result.returncode}] {out.strip() or 'no output'}"
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def list_running_apps(
    filter_name: Annotated[str, "Optional substring filter on process name."] = "",
) -> str:
    """List currently running processes with PID and memory usage."""
    try:
        import psutil
    except ImportError:
        return "[ERROR] psutil not installed. pip install psutil"
    rows = []
    for p in psutil.process_iter(["pid", "name", "memory_info"]):
        info = p.info
        name = info.get("name") or ""
        if filter_name and filter_name.lower() not in name.lower():
            continue
        mem_mb = (info["memory_info"].rss / (1024 * 1024)) if info.get("memory_info") else 0
        rows.append(f"PID {info['pid']:>6}  {mem_mb:>7.1f} MB  {name}")
    if not rows:
        return f"No processes match '{filter_name}'." if filter_name else "No processes."
    rows.sort()
    if len(rows) > 200:
        rows = rows[:200] + [f"...(+{len(rows) - 200} more)"]
    return "\n".join(rows)


@tool
def focus_window(
    title_substring: Annotated[str, "Substring of the window title to bring forward."],
) -> str:
    """Find a window by title substring and bring it to the foreground."""
    try:
        import pygetwindow as gw
    except ImportError:
        return "[ERROR] pygetwindow not installed."
    matches = [w for w in gw.getAllWindows() if title_substring.lower() in (w.title or "").lower()]
    matches = [w for w in matches if w.title]  # drop blanks
    if not matches:
        return f"No window matches '{title_substring}'."
    win = matches[0]
    try:
        if win.isMinimized:
            win.restore()
        win.activate()
        time.sleep(0.2)
        return f"[OK] Focused: {win.title}"
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"
