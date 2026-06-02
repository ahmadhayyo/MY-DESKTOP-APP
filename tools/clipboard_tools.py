"""
Clipboard tools: copy, paste, get, set clipboard content on Windows.

Uses win32clipboard (from pywin32) for reliable clipboard access.
Falls back to PowerShell if pywin32 is unavailable.
"""

from __future__ import annotations

import subprocess
from typing import Annotated

from langchain_core.tools import tool


def _try_win32_get() -> tuple[bool, str]:
    """Try to get clipboard text via win32clipboard."""
    try:
        import win32clipboard
        win32clipboard.OpenClipboard()
        try:
            data = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
            return True, data
        except TypeError:
            return True, "(clipboard is empty or contains non-text data)"
        finally:
            win32clipboard.CloseClipboard()
    except ImportError:
        return False, ""
    except Exception as exc:
        return False, str(exc)


def _try_win32_set(text: str) -> tuple[bool, str]:
    """Try to set clipboard text via win32clipboard."""
    try:
        import win32clipboard
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
            return True, "[OK] Clipboard set"
        finally:
            win32clipboard.CloseClipboard()
    except ImportError:
        return False, ""
    except Exception as exc:
        return False, str(exc)


@tool
def clipboard_get() -> str:
    """
    Read the current text content from the Windows clipboard.

    Returns the clipboard text, or a message if empty/non-text.
    """
    # Try win32clipboard first
    ok, result = _try_win32_get()
    if ok:
        return result

    # Fallback: PowerShell
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", "Get-Clipboard"],
            capture_output=True, text=True, timeout=10,
        )
        text = proc.stdout.strip()
        return text if text else "(clipboard is empty)"
    except FileNotFoundError:
        return "[ERROR] PowerShell not found and win32clipboard not available."
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def clipboard_set(
    text: Annotated[str, "Text to copy to the clipboard."],
) -> str:
    """
    Set the Windows clipboard to the given text.

    This is equivalent to pressing Ctrl+C with the text selected.
    """
    # Try win32clipboard first
    ok, result = _try_win32_set(text)
    if ok:
        return result

    # Fallback: PowerShell
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", f"Set-Clipboard -Value '{text}'"],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode == 0:
            return f"[OK] Clipboard set ({len(text)} chars)"
        return f"[ERROR] {proc.stderr.strip()}"
    except FileNotFoundError:
        return "[ERROR] PowerShell not found and win32clipboard not available."
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def clipboard_append(
    text: Annotated[str, "Text to append to the clipboard content."],
) -> str:
    """
    Append text to whatever is already in the clipboard.

    Useful for accumulating data from multiple sources before pasting.
    """
    current = clipboard_get.invoke({})
    if current.startswith("[ERROR]"):
        return current
    if current == "(clipboard is empty)":
        current = ""
    new_text = current + text
    return clipboard_set.invoke({"text": new_text})
