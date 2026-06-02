"""
Desktop control: mouse, keyboard, screenshot of the entire screen.

These are the *last resort* — prefer browser_tools for web work and app_tools
for launching applications. Pixel-clicking native apps is fragile, but
necessary for things like Notepad++ menus, custom installers, etc.

Safety notes:
  - pyautogui.FAILSAFE = True: slamming the mouse to (0,0) aborts the script.
  - All coordinates are screen-absolute. No multi-monitor offset handling yet.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Annotated

from langchain_core.tools import tool

from config import DESKTOP_DIR

# Lazy import — pyautogui imports tkinter at module load on some setups
_pyautogui = None
_pygetwindow = None


def _gui():
    global _pyautogui
    if _pyautogui is None:
        import pyautogui

        pyautogui.FAILSAFE = True  # mouse to (0,0) → abort
        pyautogui.PAUSE = 0.1
        _pyautogui = pyautogui
    return _pyautogui


def _gw():
    global _pygetwindow
    if _pygetwindow is None:
        import pygetwindow as gw

        _pygetwindow = gw
    return _pygetwindow


@tool
def screen_screenshot(
    path: Annotated[
        str,
        "Save path. Defaults to <Desktop>/desktop_screenshot.png. Pass '' for default.",
    ] = "",
    region_x: Annotated[int, "Optional region top-left X. Use 0 with 0,0,0,0 for full."] = 0,
    region_y: Annotated[int, "Optional region top-left Y."] = 0,
    region_w: Annotated[int, "Region width. 0 = full screen width."] = 0,
    region_h: Annotated[int, "Region height. 0 = full screen height."] = 0,
) -> str:
    """Capture a full-screen or region screenshot of the entire desktop."""
    pg = _gui()
    target = Path(path) if path else DESKTOP_DIR / "desktop_screenshot.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        if region_w > 0 and region_h > 0:
            img = pg.screenshot(region=(region_x, region_y, region_w, region_h))
        else:
            img = pg.screenshot()
        img.save(str(target))
        return f"[OK] Saved screenshot -> {target}  size={img.size}"
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def screen_size() -> str:
    """Return the primary screen dimensions as 'WxH'."""
    pg = _gui()
    w, h = pg.size()
    return f"{w}x{h}"


@tool
def mouse_click(
    x: Annotated[int, "Screen X coordinate."],
    y: Annotated[int, "Screen Y coordinate."],
    button: Annotated[str, "left | right | middle"] = "left",
    clicks: Annotated[int, "Number of clicks (e.g. 2 for double-click)."] = 1,
) -> str:
    """Click at an absolute screen coordinate."""
    pg = _gui()
    if button not in ("left", "right", "middle"):
        return f"[ERROR] Invalid button: {button}"
    try:
        pg.click(x=x, y=y, clicks=clicks, button=button, interval=0.05)
        return f"[OK] {button}-clicked ({x},{y}) x{clicks}"
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def mouse_move(
    x: Annotated[int, "Screen X."],
    y: Annotated[int, "Screen Y."],
    duration: Annotated[float, "Seconds for the cursor glide."] = 0.2,
) -> str:
    """Move the cursor to (x, y)."""
    pg = _gui()
    try:
        pg.moveTo(x, y, duration=duration)
        return f"[OK] Moved to ({x},{y})"
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def mouse_scroll(
    amount: Annotated[int, "Positive = up, negative = down. ~3 ticks per notch."],
) -> str:
    """Scroll the mouse wheel at the current cursor position."""
    pg = _gui()
    try:
        pg.scroll(amount)
        return f"[OK] Scrolled {amount}"
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def keyboard_type(
    text: Annotated[str, "Text to type into the focused window."],
    interval: Annotated[float, "Seconds between keystrokes (use 0 for instant)."] = 0.0,
) -> str:
    """
    Type text into whatever window is currently focused.
    Supports Unicode/Arabic text via clipboard paste fallback.
    ASCII-only text uses direct keystroke injection for finer control.
    """
    pg = _gui()
    try:
        is_ascii = all(ord(c) < 128 for c in text)
        if is_ascii and interval > 0:
            pg.write(text, interval=interval)
        else:
            import subprocess
            # Use PowerShell to set clipboard (works on Windows without extra deps)
            subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command",
                 f"Set-Clipboard -Value '{text.replace(chr(39), chr(39)+chr(39))}'"],
                capture_output=True, timeout=5, shell=False,
            )
            pg.hotkey("ctrl", "v")
            time.sleep(0.1)
        return f"[OK] Typed {len(text)} chars"
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def keyboard_hotkey(
    keys: Annotated[
        str, "Hotkey combo, e.g. 'ctrl,c' or 'win,r' or 'alt,tab' (comma-separated)."
    ],
) -> str:
    """Press a key combination."""
    pg = _gui()
    parts = [k.strip() for k in keys.split(",") if k.strip()]
    if not parts:
        return "[ERROR] No keys provided."
    try:
        pg.hotkey(*parts)
        return f"[OK] Pressed {'+'.join(parts)}"
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def list_windows() -> str:
    """List visible window titles on the desktop."""
    gw = _gw()
    try:
        titles = [w.title for w in gw.getAllWindows() if w.title]
        if not titles:
            return "(no titled windows)"
        if len(titles) > 80:
            titles = titles[:80] + [f"...(+{len(titles) - 80} more)"]
        return "\n".join(titles)
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def wait(seconds: Annotated[float, "How long to sleep."] = 1.0) -> str:
    """Pause execution. Useful between UI actions."""
    seconds = max(0.0, min(seconds, 60.0))
    time.sleep(seconds)
    return f"[OK] Waited {seconds}s"
