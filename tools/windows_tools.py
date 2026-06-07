"""
Windows Advanced Tools — Deep Windows OS control for the HAYO agent.

Gives the agent full control over the Windows environment:
  • windows_search          — Search and launch anything via Windows search
  • window_manager          — List, focus, move, resize, minimize, maximize windows
  • set_volume              — Set system volume precisely
  • open_settings_page      — Jump directly to any Windows Settings page
  • manage_startup_apps     — Enable/disable startup programs
  • power_action            — Sleep, restart, shutdown, lock, hibernate
  • set_wallpaper           — Change desktop wallpaper
  • get_system_details      — RAM, CPU, disk, uptime, Windows version
  • manage_clipboard_history— Access Windows clipboard history
  • run_as_admin            — Run any command as Administrator
  • type_in_window          — Focus a window and type into it
  • drag_and_drop           — Drag from one location and drop at another
  • scroll_in_window        — Scroll within a specific app window
  • windows_toast           — Send a Windows toast notification
  • get_active_window       — Get info about the currently focused window
  • app_exists              — Check if an application is installed/running
"""

from __future__ import annotations

import os
import subprocess
import time
from typing import Annotated

from langchain_core.tools import tool

# Unified OCR engine (native Windows OCR primary; tesseract fallback).
try:
    from tools.ocr_engine import (
        ocr_text as _ocr_text,
        ocr_words as _ocr_words_engine,
    )
except Exception:
    _ocr_text = None
    _ocr_words_engine = None


def _ocr(image) -> str:
    """Module-level OCR text helper. Returns '' if no engine."""
    if _ocr_text is None:
        return ""
    try:
        return _ocr_text(image)
    except Exception:
        return ""


def _ocr_word_boxes(image) -> list:
    """Module-level OCR word-box helper. Returns [] if no engine."""
    if _ocr_words_engine is None:
        return []
    try:
        return _ocr_words_engine(image)
    except Exception:
        return []


# ── helpers ──────────────────────────────────────────────────────────────────

def _run_ps(command: str, timeout: int = 30) -> str:
    """Run a PowerShell command and return output."""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True, text=True, timeout=timeout
    )
    out = result.stdout.strip()
    err = result.stderr.strip()
    if err and not out:
        return f"[STDERR] {err}"
    return out or "(no output)"


# ── tools ─────────────────────────────────────────────────────────────────────

@tool
def windows_search(
    query: Annotated[str, "What to search for: app name, file name, setting, or command."],
    action: Annotated[str, "'open' to launch the top result, 'list' to show results only. Default: 'open'"] = "open",
    timeout_seconds: Annotated[int, "Seconds to wait for the app window to open. Default 8."] = 8,
) -> str:
    """
    Search Windows taskbar (Win+S) for an app and open it.
    Uses clipboard paste for reliability (supports any language/character).
    Takes screenshots to verify the app actually opened.

    Examples: 'Replit', 'Notepad', 'Chrome', 'Discord', 'Calculator'
    This is THE most reliable way to open any installed app by name.
    """
    try:
        import pyautogui
        import pyperclip

        # ── 0. Record windows before opening ──────────────────────────────
        try:
            import pygetwindow as gw
            windows_before = set(t for t in gw.getAllTitles() if t.strip())
        except Exception:
            windows_before = set()

        # ── 1. Close any open Start/Search overlay first ───────────────────
        pyautogui.press('escape')
        time.sleep(0.3)

        # ── 2. Open Windows Search (Win+S is focused immediately) ──────────
        pyautogui.hotkey('win', 's')
        time.sleep(1.0)   # wait for search box to appear

        # ── 3. Clear any previous text and paste query via clipboard ───────
        pyautogui.hotkey('ctrl', 'a')
        time.sleep(0.1)
        pyperclip.copy(query)
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(1.5)   # wait for search results to populate

        # ── 4. Take screenshot — see what appeared ─────────────────────────
        shot = pyautogui.screenshot()
        screen_w, screen_h = pyautogui.size()

        # ── 5. If only listing — return what we see ────────────────────────
        if action == "list":
            text = _ocr(shot)
            clean = "\n".join(l for l in text.splitlines() if l.strip())[:600] or "(لا نص)"
            pyautogui.press('escape')
            return f"🔍 نتائج بحث Windows عن '{query}':\n{clean}"

        # ── 6. Try to click the best matching result via OCR ───────────────
        clicked_by_ocr = False
        try:
            needle = query.lower().strip()
            # Search for the app name in the LEFT side of the screen
            # (Windows search shows app results on the left ~40% of screen)
            for wd in _ocr_word_boxes(shot):
                word = str(wd.get('t', ''))
                if not word.strip():
                    continue
                if needle in word.lower():
                    x = int(wd['x']) + int(wd['w']) // 2
                    y = int(wd['y']) + int(wd['h']) // 2
                    # Only click if result is in the upper-left (search panel area)
                    if x < screen_w * 0.65 and y < screen_h * 0.85:
                        pyautogui.click(x, y)
                        clicked_by_ocr = True
                        break
        except Exception:
            pass

        if not clicked_by_ocr:
            # Fallback: press Enter (opens top result)
            pyautogui.press('enter')

        # ── 7. Wait for the app window to appear ───────────────────────────
        deadline = time.time() + timeout_seconds
        new_window_title = ""
        while time.time() < deadline:
            time.sleep(0.8)
            try:
                import pygetwindow as gw
                current = set(t for t in gw.getAllTitles() if t.strip())
                new_ones = current - windows_before
                if new_ones:
                    # Filter out Start Menu / Search overlays
                    real_new = [t for t in new_ones if not any(
                        skip in t.lower() for skip in ['search', 'start', 'cortana', '']
                    ) and t.strip()]
                    if real_new:
                        new_window_title = real_new[0]
                        break
                # Check active window changed
                active = gw.getActiveWindowTitle() or ""
                if active and query.lower() in active.lower():
                    new_window_title = active
                    break
            except Exception:
                pass

        # ── 8. Take verification screenshot ───────────────────────────────
        time.sleep(0.5)
        shot2 = pyautogui.screenshot()
        screen_text = _ocr(shot2)
        clean_screen = "\n".join(l for l in screen_text.splitlines() if l.strip())[:400] or "(لا نص)"

        try:
            import pygetwindow as gw
            active_title = gw.getActiveWindowTitle() or ""
        except Exception:
            active_title = ""

        if new_window_title:
            return (
                f"✅ تم فتح '{query}' بنجاح!\n"
                f"النافذة الجديدة: «{new_window_title}»\n"
                f"الشاشة تُظهر:\n{clean_screen}"
            )
        elif active_title and query.lower() in active_title.lower():
            return (
                f"✅ التطبيق '{query}' مفتوح!\n"
                f"النافذة النشطة: «{active_title}»\n"
                f"الشاشة تُظهر:\n{clean_screen}"
            )
        else:
            return (
                f"⚠️ تم البحث عن '{query}' وضغط Enter.\n"
                f"النافذة النشطة الآن: «{active_title}»\n"
                f"الشاشة تُظهر:\n{clean_screen}\n"
                f"💡 إذا لم يفتح التطبيق — استخدم screen_describe() للتحقق"
            )

    except Exception as exc:
        return f"[ERROR] windows_search: {exc}"


@tool
def window_manager(
    action: Annotated[str, "Action: 'list', 'focus', 'minimize', 'maximize', 'restore', 'close', 'move', 'resize'"],
    window_title: Annotated[str, "Part of the window title to target. Empty = active window."] = "",
    x: Annotated[int, "For 'move': new left edge X position."] = 0,
    y: Annotated[int, "For 'move': new top edge Y position."] = 0,
    width: Annotated[int, "For 'resize': new width in pixels."] = 0,
    height: Annotated[int, "For 'resize': new height in pixels."] = 0,
) -> str:
    """
    Manage application windows: list all open windows, focus, minimize, maximize,
    move, or resize them. Use 'list' first to see available windows and their titles.
    """
    try:
        import pygetwindow as gw

        if action == "list":
            wins = gw.getAllTitles()
            visible = [t for t in wins if t.strip()]
            if not visible:
                return "(No windows found)"
            return "Open windows:\n" + "\n".join(f"  • {t}" for t in visible[:30])

        # Find target window
        if window_title:
            matches = gw.getWindowsWithTitle(window_title)
            if not matches:
                # Try partial match
                all_wins = [w for w in gw.getAllWindows() if window_title.lower() in w.title.lower()]
                if not all_wins:
                    return f"[NOT FOUND] No window with title containing '{window_title}'"
                win = all_wins[0]
            else:
                win = matches[0]
        else:
            win = gw.getActiveWindow()
            if not win:
                return "[ERROR] No active window found."

        title = win.title

        if action == "focus":
            win.activate()
            time.sleep(0.3)
            return f"[OK] Focused: '{title}'"

        elif action == "minimize":
            win.minimize()
            return f"[OK] Minimized: '{title}'"

        elif action == "maximize":
            win.maximize()
            return f"[OK] Maximized: '{title}'"

        elif action == "restore":
            win.restore()
            return f"[OK] Restored: '{title}'"

        elif action == "close":
            win.close()
            return f"[OK] Closed: '{title}'"

        elif action == "move":
            win.moveTo(x, y)
            return f"[OK] Moved '{title}' to ({x}, {y})"

        elif action == "resize":
            win.resizeTo(width, height)
            return f"[OK] Resized '{title}' to {width}x{height}"

        else:
            return f"[ERROR] Unknown action '{action}'. Use: list, focus, minimize, maximize, restore, close, move, resize"

    except Exception as exc:
        return f"[ERROR] window_manager: {exc}"


@tool
def get_active_window() -> str:
    """
    Get information about the currently focused (active) window.
    Returns title, position, and size. Useful before typing or clicking.
    """
    try:
        import pygetwindow as gw
        win = gw.getActiveWindow()
        if not win:
            return "(No active window detected)"
        return (
            f"Active window:\n"
            f"  Title:    {win.title}\n"
            f"  Position: ({win.left}, {win.top})\n"
            f"  Size:     {win.width} x {win.height} pixels\n"
            f"  Center:   ({win.centerx}, {win.centery})"
        )
    except Exception as exc:
        return f"[ERROR] get_active_window: {exc}"


@tool
def type_in_window(
    window_title: Annotated[str, "Part of the window title to focus. Empty = current active window."],
    text: Annotated[str, "Text to type into the window. Supports Arabic, Unicode, any language."],
    clear_first: Annotated[bool, "Select all (Ctrl+A) and clear existing text before typing. Default False."] = False,
    press_enter: Annotated[bool, "Press Enter after typing. Default False."] = False,
    click_center: Annotated[bool, "Click the center of the window before typing. Default False."] = False,
) -> str:
    """
    Focus a specific window and type text into it.
    Uses clipboard paste (Ctrl+V) for reliable Arabic/Unicode input.
    Works for any app: Notepad, Word, browser, Replit, Discord, etc.
    """
    try:
        import pyautogui
        import pygetwindow as gw
        import pyperclip

        if window_title:
            matches = [w for w in gw.getAllWindows() if window_title.lower() in w.title.lower()]
            if not matches:
                # Try to find any window that's close
                all_titles = [w.title for w in gw.getAllWindows() if w.title.strip()]
                return (
                    f"[NOT FOUND] No window matching '{window_title}'.\n"
                    f"Open windows: {', '.join(all_titles[:10])}"
                )
            win = matches[0]
            win.activate()
            time.sleep(0.5)

            if click_center:
                pyautogui.click(win.centerx, win.centery)
                time.sleep(0.3)

        if clear_first:
            pyautogui.hotkey("ctrl", "a")
            time.sleep(0.2)

        # Use clipboard for reliable Unicode/Arabic input
        pyperclip.copy(text)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.2)

        if press_enter:
            pyautogui.press("enter")

        return f"✅ كتابة {len(text)} حرف في '{window_title or 'النافذة النشطة'}'"
    except ImportError:
        # Fallback without pyperclip
        try:
            import pyautogui
            import pygetwindow as gw
            if window_title:
                matches = [w for w in gw.getAllWindows() if window_title.lower() in w.title.lower()]
                if matches:
                    matches[0].activate()
                    time.sleep(0.5)
            if clear_first:
                pyautogui.hotkey("ctrl", "a")
                time.sleep(0.2)
            # ASCII-only fallback
            ascii_text = text.encode('ascii', errors='replace').decode('ascii')
            pyautogui.write(ascii_text, interval=0.03)
            if press_enter:
                pyautogui.press("enter")
            return f"[OK-ASCII] Typed {len(text)} chars (ASCII fallback)"
        except Exception as e2:
            return f"[ERROR] type_in_window fallback: {e2}"
    except Exception as exc:
        return f"[ERROR] type_in_window: {exc}"


@tool
def drag_and_drop(
    from_x: Annotated[int, "Starting X coordinate."],
    from_y: Annotated[int, "Starting Y coordinate."],
    to_x: Annotated[int, "Destination X coordinate."],
    to_y: Annotated[int, "Destination Y coordinate."],
    duration: Annotated[float, "How long the drag takes in seconds. Default 0.5."] = 0.5,
) -> str:
    """
    Drag from one screen location to another (drag-and-drop).
    Useful for moving files, resizing elements, or interacting with drag-enabled UIs.
    """
    try:
        import pyautogui
        pyautogui.moveTo(from_x, from_y)
        time.sleep(0.2)
        pyautogui.dragTo(to_x, to_y, duration=duration, button="left")
        return f"[OK] Dragged from ({from_x},{from_y}) to ({to_x},{to_y})"
    except Exception as exc:
        return f"[ERROR] drag_and_drop: {exc}"


@tool
def open_settings_page(
    page: Annotated[str, "Settings page to open. Examples: 'display', 'sound', 'wifi', 'bluetooth', 'apps', 'updates', 'privacy', 'accounts', 'power', 'storage', 'notifications', 'language', 'time', 'region'"],
) -> str:
    """
    Open a specific Windows Settings page directly.
    Much faster than navigating through the Settings UI manually.
    """
    page_map = {
        "display":       "ms-settings:display",
        "sound":         "ms-settings:sound",
        "audio":         "ms-settings:sound",
        "wifi":          "ms-settings:network-wifi",
        "network":       "ms-settings:network",
        "bluetooth":     "ms-settings:bluetooth",
        "apps":          "ms-settings:appsfeatures",
        "programs":      "ms-settings:appsfeatures",
        "updates":       "ms-settings:windowsupdate",
        "update":        "ms-settings:windowsupdate",
        "privacy":       "ms-settings:privacy",
        "accounts":      "ms-settings:accounts",
        "power":         "ms-settings:powersleep",
        "sleep":         "ms-settings:powersleep",
        "storage":       "ms-settings:storagesense",
        "disk":          "ms-settings:storagesense",
        "notifications": "ms-settings:notifications",
        "language":      "ms-settings:regionlanguage",
        "region":        "ms-settings:regionlanguage",
        "time":          "ms-settings:dateandtime",
        "date":          "ms-settings:dateandtime",
        "taskbar":       "ms-settings:taskbar",
        "theme":         "ms-settings:themes",
        "personalize":   "ms-settings:personalization",
        "startup":       "ms-settings:startupapps",
        "default_apps":  "ms-settings:defaultapps",
        "mouse":         "ms-settings:mousetouchpad",
        "keyboard":      "ms-settings:easeofaccess-keyboard",
        "camera":        "ms-settings:camera",
        "microphone":    "ms-settings:privacy-microphone",
        "battery":       "ms-settings:batterysaver",
        "about":         "ms-settings:about",
    }
    key = page.lower().strip()
    uri = page_map.get(key)
    if not uri:
        # Try to guess
        for k, v in page_map.items():
            if key in k or k in key:
                uri = v
                break

    if not uri:
        uri = f"ms-settings:{key}"

    try:
        subprocess.Popen(["start", uri], shell=True)
        time.sleep(1.5)
        return f"[OK] Opened Windows Settings: '{page}' ({uri})"
    except Exception as exc:
        return f"[ERROR] open_settings_page: {exc}"


@tool
def power_action(
    action: Annotated[str, "Action to perform: 'lock', 'sleep', 'hibernate', 'restart', 'shutdown', 'logoff'"],
    delay_seconds: Annotated[int, "Delay before action (0 = immediate). Default 0."] = 0,
) -> str:
    """
    Perform a system power action: lock screen, sleep, restart, shutdown, etc.
    Use 'lock' to lock the screen. Use 'restart' to reboot Windows.
    WARNING: 'shutdown' and 'restart' will close all open apps.
    """
    commands = {
        "lock":      ["rundll32.exe", "user32.dll,LockWorkStation"],
        "sleep":     ["powercfg", "-h", "off"],  # will use different method
        "hibernate": ["shutdown", "/h"],
        "restart":   ["shutdown", "/r", "/t", str(delay_seconds)],
        "shutdown":  ["shutdown", "/s", "/t", str(delay_seconds)],
        "logoff":    ["shutdown", "/l"],
    }

    action = action.lower().strip()

    if action == "lock":
        subprocess.Popen(commands["lock"])
        return "[OK] Screen locked."

    elif action == "sleep":
        # Use PowerShell to sleep
        _run_ps("Add-Type -Assembly System.Windows.Forms; [System.Windows.Forms.Application]::SetSuspendState('Suspend', $false, $false)")
        return "[OK] Sent sleep command."

    elif action in commands:
        subprocess.Popen(commands[action])
        return f"[OK] {action.capitalize()} initiated (delay: {delay_seconds}s)."

    else:
        return f"[ERROR] Unknown action '{action}'. Use: lock, sleep, hibernate, restart, shutdown, logoff"


@tool
def manage_startup_apps(
    action: Annotated[str, "'list' to show startup apps, 'enable' or 'disable' to change them."],
    app_name: Annotated[str, "App name to enable/disable (partial match). Required for enable/disable."] = "",
) -> str:
    """
    View and control which programs start automatically with Windows.
    Use 'list' to see all startup apps, then 'enable' or 'disable' specific ones.
    """
    if action == "list":
        result = _run_ps(
            "Get-CimInstance Win32_StartupCommand | "
            "Select-Object Name, Command, Location | "
            "Format-Table -AutoSize"
        )
        return f"[Startup apps]\n{result}"

    elif action in ("enable", "disable"):
        if not app_name:
            return "[ERROR] Please provide an app_name to enable/disable."
        # Use Task Manager startup registry
        state = "1" if action == "enable" else "0"
        result = _run_ps(
            f"$apps = Get-CimInstance Win32_StartupCommand | Where-Object {{$_.Name -like '*{app_name}*'}}; "
            f"if ($apps) {{ $apps | ForEach-Object {{ Write-Output \"Found: $($_.Name)\" }} }} "
            f"else {{ Write-Output 'Not found in startup list' }}"
        )
        return f"[{action.upper()}] {result}\nNote: To fully enable/disable, use Task Manager > Startup tab for reliability."

    else:
        return "[ERROR] action must be 'list', 'enable', or 'disable'."


@tool
def set_wallpaper(
    image_path: Annotated[str, "Absolute path to the image file (JPG, PNG, BMP)."],
    style: Annotated[str, "Display style: 'fill', 'fit', 'stretch', 'tile', 'center', 'span'. Default: 'fill'"] = "fill",
) -> str:
    """
    Change the Windows desktop wallpaper to any image file.
    """
    from pathlib import Path
    import ctypes

    style_map = {"fill": 10, "fit": 6, "stretch": 2, "tile": 0, "center": 0, "span": 22}
    style_val = style_map.get(style.lower(), 10)

    img = Path(image_path)
    if not img.exists():
        return f"[ERROR] File not found: {image_path}"

    try:
        ctypes.windll.user32.SystemParametersInfoW(20, 0, str(img.resolve()), 3)
        return f"[OK] Wallpaper set to: {img.name} (style: {style})"
    except Exception as exc:
        return f"[ERROR] set_wallpaper: {exc}"


@tool
def get_system_details() -> str:
    """
    Get detailed system information: Windows version, CPU, RAM, disk space,
    uptime, screen resolution, and running process count.
    """
    try:
        import psutil
        from datetime import datetime, timedelta

        # OS info
        os_info = _run_ps("[System.Environment]::OSVersion.VersionString")

        # RAM
        mem = psutil.virtual_memory()
        ram_total = f"{mem.total / (1024**3):.1f} GB"
        ram_used  = f"{mem.used / (1024**3):.1f} GB"
        ram_pct   = f"{mem.percent}%"

        # CPU
        cpu_pct   = psutil.cpu_percent(interval=1)
        cpu_count = psutil.cpu_count()

        # Disk
        disk = psutil.disk_usage("C:\\")
        disk_total = f"{disk.total / (1024**3):.1f} GB"
        disk_free  = f"{disk.free  / (1024**3):.1f} GB"
        disk_pct   = f"{disk.percent}%"

        # Uptime
        boot_time  = datetime.fromtimestamp(psutil.boot_time())
        uptime     = datetime.now() - boot_time
        uptime_str = str(timedelta(seconds=int(uptime.total_seconds())))

        # Screen
        import pyautogui
        sw, sh = pyautogui.size()

        # Processes
        proc_count = len(list(psutil.process_iter()))

        return (
            f"System Details\n"
            f"  OS:          {os_info}\n"
            f"  Screen:      {sw}x{sh}\n"
            f"  Uptime:      {uptime_str}\n"
            f"  CPU:         {cpu_count} cores, {cpu_pct}% used\n"
            f"  RAM:         {ram_total} total, {ram_used} used ({ram_pct})\n"
            f"  Disk C\\:     {disk_total} total, {disk_free} free ({disk_pct} used)\n"
            f"  Processes:   {proc_count} running"
        )
    except Exception as exc:
        return f"[ERROR] get_system_details: {exc}"


@tool
def run_as_admin(
    command: Annotated[str, "The command or executable to run with administrator privileges."],
    wait: Annotated[bool, "Wait for the process to complete. Default False."] = False,
) -> str:
    """
    Run any command or application with Administrator (elevated) privileges.
    Use this for installing software, modifying system settings, or any operation
    that requires admin rights.
    """
    try:
        import ctypes
        result = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", "cmd.exe",
            f"/c {command}", None, 1
        )
        if result <= 32:
            return f"[ERROR] ShellExecute failed with code {result}. User may have denied the UAC prompt."
        if wait:
            time.sleep(3)
        return f"[OK] Launched with admin privileges: {command}"
    except Exception as exc:
        return f"[ERROR] run_as_admin: {exc}"


@tool
def windows_toast_notification(
    title: Annotated[str, "Notification title."],
    message: Annotated[str, "Notification body text."],
    duration: Annotated[int, "How long to show (seconds). Default 5."] = 5,
) -> str:
    """
    Show a Windows toast notification (popup in the bottom-right corner).
    Great for alerting the user when a long task completes.
    """
    try:
        from plyer import notification
        notification.notify(
            title=title,
            message=message,
            timeout=duration,
            app_name="HAYO AI Agent",
        )
        return f"[OK] Toast notification sent: '{title}'"
    except Exception as exc:
        # Fallback: PowerShell toast
        ps_cmd = (
            f"[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null; "
            f"$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02); "
            f"$template.GetElementsByTagName('text')[0].AppendChild($template.CreateTextNode('{title}')) | Out-Null; "
            f"$template.GetElementsByTagName('text')[1].AppendChild($template.CreateTextNode('{message}')) | Out-Null; "
            f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('HAYO').Show([Windows.UI.Notifications.ToastNotification]::new($template))"
        )
        try:
            _run_ps(ps_cmd, timeout=5)
            return f"[OK] Toast notification sent via PowerShell: '{title}'"
        except Exception:
            return f"[PARTIAL] Notification libraries unavailable: {exc}"


@tool
def scroll_in_window(
    window_title: Annotated[str, "Part of the window title. Empty = active window."] = "",
    direction: Annotated[str, "'up', 'down', 'left', 'right'. Default: 'down'"] = "down",
    amount: Annotated[int, "Number of scroll clicks. Default 5."] = 5,
) -> str:
    """
    Scroll within a specific application window.
    Works for any app: browsers, file explorers, documents, lists, etc.
    """
    try:
        import pyautogui
        import pygetwindow as gw

        if window_title:
            matches = [w for w in gw.getAllWindows() if window_title.lower() in w.title.lower()]
            if matches:
                matches[0].activate()
                time.sleep(0.4)
                cx, cy = matches[0].centerx, matches[0].centery
                pyautogui.moveTo(cx, cy)

        scroll_map = {"up": amount, "down": -amount, "left": amount, "right": -amount}
        scroll_val = scroll_map.get(direction.lower(), -amount)

        if direction in ("left", "right"):
            pyautogui.hscroll(scroll_val)
        else:
            pyautogui.scroll(scroll_val)

        return f"[OK] Scrolled {direction} by {amount} in '{window_title or 'active window'}'"
    except Exception as exc:
        return f"[ERROR] scroll_in_window: {exc}"


@tool
def app_exists(
    name: Annotated[str, "App name to check (e.g., 'Chrome', 'Notepad', 'VLC')."],
) -> str:
    """
    Check if an application is installed on this Windows machine and/or currently running.
    Returns installation status and process info if running.
    """
    try:
        import psutil

        # Check if currently running
        running = []
        for proc in psutil.process_iter(["name", "pid"]):
            if name.lower() in proc.info["name"].lower():
                running.append(f"PID {proc.info['pid']}: {proc.info['name']}")

        # Check if installed via registry
        result = _run_ps(
            f"Get-ItemProperty HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\* "
            f"| Where-Object {{$_.DisplayName -like '*{name}*'}} "
            f"| Select-Object -First 1 DisplayName, DisplayVersion | Format-List"
        )

        lines = []
        if running:
            lines.append(f"✅ RUNNING: {', '.join(running)}")
        else:
            lines.append("❌ Not currently running")

        if result and "DisplayName" in result:
            lines.append(f"✅ INSTALLED: {result.strip()}")
        else:
            lines.append("❌ Not found in installed programs registry")

        return "\n".join(lines)
    except Exception as exc:
        return f"[ERROR] app_exists: {exc}"


@tool
def launch_app_smart(
    app_name: Annotated[str, "App name to open. E.g. 'Replit', 'Discord', 'Chrome', 'VS Code', 'Notepad'"],
    wait_for_title: Annotated[str, "Part of the window title to confirm it opened. Empty = auto-detect."] = "",
    timeout_seconds: Annotated[int, "Max seconds to wait for the app. Default 20."] = 20,
) -> str:
    """
    The ONLY correct way to open any installed app. Tries 3 methods in order:

    METHOD A — Windows Store/MSIX apps (shell:AppsFolder):
      Runs Get-StartApps to find the App ID, then launches via
      explorer.exe "shell:AppsFolder\\AppID". Works for: Replit, Discord,
      Spotify, any Microsoft Store app.

    METHOD B — Win+S keyboard search:
      Opens Windows Search, pastes app name via clipboard, presses Enter.
      Works for all apps including classic Win32.

    METHOD C — Direct exe launch:
      Searches common install locations for AppName.exe and launches directly.

    After each method: waits for a new window + takes a screenshot to verify.

    Parameters:
    - app_name: The app to open (any name, any language)
    - wait_for_title: Text to look for in window title to confirm success
    - timeout_seconds: Max wait per method

    Returns: Detailed log of what happened + final screen state.
    """
    try:
        import pyautogui
        import pygetwindow as gw

        log = []
        windows_before = set(t for t in gw.getAllTitles() if t.strip())
        log.append(f"🚀 محاولة فتح '{app_name}' (النوافذ الحالية: {len(windows_before)})")

        # ─────────────────────────────────────────────────────────────────
        def _wait_for_new_window(secs: int) -> str:
            """Poll until a new window appears. Returns its title or ''."""
            deadline = time.time() + secs
            while time.time() < deadline:
                time.sleep(0.8)
                try:
                    current = set(t for t in gw.getAllTitles() if t.strip())
                    new_ones = [
                        t for t in (current - windows_before)
                        if not any(skip in t.lower() for skip in
                                   ['search', 'cortana', 'task switching',
                                    'windows input', 'start menu'])
                    ]
                    if wait_for_title:
                        match = next((t for t in current
                                      if wait_for_title.lower() in t.lower()), None)
                        if match:
                            return match
                    if new_ones:
                        return new_ones[0]
                    active = gw.getActiveWindowTitle() or ""
                    if app_name.lower() in active.lower():
                        return active
                except Exception:
                    pass
            return ""

        def _verify_screen() -> str:
            """Take screenshot + native OCR, return readable summary."""
            try:
                shot = pyautogui.screenshot()
                active = gw.getActiveWindowTitle() or "(غير معروف)"
                txt = _ocr(shot)
                if txt.strip():
                    clean = "\n".join(l for l in txt.splitlines() if l.strip())[:450]
                    return f"النافذة: «{active}»\nالشاشة:\n{clean}"
                return f"النافذة: «{active}»\n(لم يُقرأ نص من الشاشة)"
            except Exception as e:
                return f"(خطأ في التحقق: {e})"

        def _force_focus_window(hwnd: int) -> bool:
            """
            Use Win32 API (ctypes) to reliably force a window to the foreground.
            pygetwindow.activate() alone is unreliable on Windows 10/11.
            """
            try:
                import ctypes
                user32 = ctypes.windll.user32
                # Allow this process to set foreground window
                user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
                # Restore if minimized
                user32.ShowWindow(hwnd, 9)   # SW_RESTORE
                # Attach thread input to target (required on Windows 10)
                tid_target = user32.GetWindowThreadProcessId(hwnd, None)
                tid_current = ctypes.windll.kernel32.GetCurrentThreadId()
                if tid_target != tid_current:
                    user32.AttachThreadInput(tid_current, tid_target, True)
                user32.BringWindowToTop(hwnd)
                user32.SetForegroundWindow(hwnd)
                if tid_target != tid_current:
                    user32.AttachThreadInput(tid_current, tid_target, False)
                return True
            except Exception:
                return False

        def _find_app_window_hwnd() -> tuple[int, str]:
            """
            Find the Replit/app window handle using Win32 EnumWindows.
            Returns (hwnd, title) or (0, '').
            """
            try:
                import ctypes
                user32 = ctypes.windll.user32
                _CF_KW = ['لحظة', 'just a moment', 'checking', app_name.lower()]
                found = [0, ""]

                def _cb(hwnd, _):
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length == 0:
                        return True
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value
                    if user32.IsWindowVisible(hwnd) and any(kw in title.lower() for kw in _CF_KW):
                        found[0] = hwnd
                        found[1] = title
                        return False   # stop enumeration
                    return True

                EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int))
                user32.EnumWindows(EnumWindowsProc(_cb), 0)
                return found[0], found[1]
            except Exception:
                return 0, ""

        def _get_window_title_by_hwnd(hwnd: int) -> str:
            """Get current title of a specific window by handle."""
            try:
                import ctypes
                user32 = ctypes.windll.user32
                length = user32.GetWindowTextLengthW(hwnd)
                if length == 0:
                    return ""
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                return buf.value
            except Exception:
                return ""

        def _resolve_cloudflare_and_describe(window_title: str) -> list[str]:
            """
            1. Always takes a final screenshot (even if no Cloudflare).
            2. If Cloudflare detected: focuses window via Win32 API + waits up to 90s.
            3. Every 8s: re-focuses + re-clicks to keep Cloudflare JS alive.
            4. Tracks the SPECIFIC window by HWND, not "active window" (avoids false positives).
            """
            cf_lines = []
            _CF_KEYWORDS = ['لحظة', 'just a moment', 'checking your browser',
                            'please wait', 'moment...']

            # Wait 2s for page to fully load before detecting CF
            time.sleep(2)

            # Get current title from the actual window (not just the passed param)
            hwnd, current_title = _find_app_window_hwnd()
            check_title = current_title if current_title else window_title

            is_cf = any(kw in check_title.lower() for kw in _CF_KEYWORDS)

            if not is_cf:
                # No Cloudflare — still take a screenshot and return screen state
                cf_lines.append(_verify_screen())
                return cf_lines

            cf_lines.append(f"🛡️ Cloudflare اكتُشف: «{check_title}»")
            cf_lines.append("   الخطوة 1: تركيز النافذة عبر Win32 API...")

            # ── Step 1: Force-focus using Win32 API ──────────────────────────
            focus_ok = False
            if hwnd:
                focus_ok = _force_focus_window(hwnd)
                cf_lines.append(f"   {'✅' if focus_ok else '⚠️'} Win32 SetForegroundWindow({'نجح' if focus_ok else 'تعذر'})")
                time.sleep(0.8)
                # Click window center to activate JS context
                try:
                    import ctypes as _ct
                    _u32 = _ct.windll.user32
                    rect = _ct.wintypes.RECT()
                    _u32.GetWindowRect(hwnd, _ct.byref(rect))
                    cx = (rect.left + rect.right) // 2
                    cy = (rect.top + rect.bottom) // 2
                    pyautogui.click(cx, cy)
                    cf_lines.append(f"   🖱️ نقرة تفعيل في مركز النافذة ({cx},{cy})")
                except Exception as _ce:
                    cf_lines.append(f"   ⚠️ تعذرت نقرة المركز: {_ce}")
            else:
                # Fallback to pygetwindow
                try:
                    wins = gw.getAllWindows()
                    tgt = next((w for w in wins
                                if any(kw in w.title.lower()
                                       for kw in [app_name.lower()] + _CF_KEYWORDS)), None)
                    if tgt:
                        tgt.activate()
                        time.sleep(0.5)
                        pyautogui.click(tgt.centerx, tgt.centery)
                        cf_lines.append("   ✅ تركيز عبر pygetwindow + نقرة")
                except Exception as _we:
                    cf_lines.append(f"   ⚠️ pygetwindow fallback فشل: {_we}")

            # ── Step 2: Poll by HWND title (NOT getActiveWindowTitle!) ────────
            cf_lines.append("   الخطوة 2: انتظار تغيير العنوان (حد أقصى 90ث)...")
            deadline = time.time() + 90
            resolved = False
            checks = 0
            while time.time() < deadline:
                time.sleep(3)
                checks += 1

                # Check title of THE SPECIFIC WINDOW (hwnd), not active window
                if hwnd:
                    cur = _get_window_title_by_hwnd(hwnd)
                else:
                    # Fallback: search again
                    hwnd, cur = _find_app_window_hwnd()

                still_cf = any(kw in cur.lower() for kw in _CF_KEYWORDS) if cur else True

                if not still_cf and cur.strip():
                    cf_lines.append(f"   ✅ Cloudflare تم تجاوزه تلقائياً! العنوان: «{cur}»")
                    resolved = True
                    break

                # Every 24s (every 8 polls of 3s): re-focus + re-click
                if checks % 8 == 0:
                    remaining = int(deadline - time.time())
                    cf_lines.append(f"   ⏳ لا يزال CF... ({remaining}ث متبقية) — إعادة التفعيل")
                    if hwnd:
                        _force_focus_window(hwnd)
                        time.sleep(0.3)
                        try:
                            import ctypes as _ct2
                            _u2 = _ct2.windll.user32
                            rect2 = _ct2.wintypes.RECT()
                            _u2.GetWindowRect(hwnd, _ct2.byref(rect2))
                            cx2 = (rect2.left + rect2.right) // 2
                            cy2 = (rect2.top + rect2.bottom) // 2
                            pyautogui.click(cx2, cy2)
                        except Exception:
                            pass

            if not resolved:
                cf_lines.append("   ⚠️ لم يُحل Cloudflare خلال 90ث")
                # Try clicking visible checkbox via native OCR word boxes
                try:
                    shot = pyautogui.screenshot()
                    _clicked = False
                    for tgt_txt in ["Verify", "verify", "تحقق", "robot", "Human", "human"]:
                        for wd in _ocr_word_boxes(shot):
                            word = str(wd.get('t', ''))
                            if tgt_txt.lower() in word.lower():
                                bx = int(wd['x']) + int(wd['w']) // 2
                                by = int(wd['y']) + int(wd['h']) // 2
                                pyautogui.click(bx, by)
                                cf_lines.append(f"   🖱️ نقر على زر '{word}' في ({bx},{by})")
                                time.sleep(3)
                                _clicked = True
                                break
                        if _clicked:
                            break
                except Exception:
                    pass
                cf_lines.append("   → CAPTCHA_MANUAL_REQUIRED: يرجى حل التحقق يدوياً إذا لم يُحل")

            # Always: take final screenshot
            cf_lines.append(_verify_screen())
            return cf_lines

        # ═══════════════════════════════════════════════════════════════
        # METHOD A — Windows Store / MSIX via shell:AppsFolder
        # ═══════════════════════════════════════════════════════════════
        log.append("━━━ الطريقة A: Windows Store / MSIX (shell:AppsFolder) ━━━")
        try:
            import json as _json
            ps_result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                 f"Get-StartApps | Where-Object {{$_.Name -like '*{app_name}*'}} "
                 f"| Select-Object -First 1 | ConvertTo-Json -Compress"],
                capture_output=True, text=True, timeout=10
            )
            raw = ps_result.stdout.strip()
            if raw and raw.startswith("{"):
                data = _json.loads(raw)
                app_id = data.get("AppID") or data.get("AppId", "")
                app_real_name = data.get("Name", app_name)
                if app_id:
                    log.append(f"✅ وجدت التطبيق: «{app_real_name}» — AppID: {app_id}")
                    # Correct MSIX launch format
                    shell_uri = f"shell:AppsFolder\\{app_id}"
                    subprocess.Popen(["explorer.exe", shell_uri])
                    log.append(f"🚀 تم إطلاق: explorer.exe \"{shell_uri}\"")
                    new_title = _wait_for_new_window(timeout_seconds)
                    if new_title:
                        log.append(f"✅ الطريقة A نجحت! النافذة: «{new_title}»")
                        log.extend(_resolve_cloudflare_and_describe(new_title))
                        return "\n".join(log)
                    else:
                        log.append("⚠️ الطريقة A: لم تظهر نافذة جديدة — ننتقل للطريقة B")
                else:
                    log.append("⚠️ الطريقة A: AppID فارغ في النتيجة — ننتقل للطريقة B")
            else:
                log.append(f"⚠️ الطريقة A: لم يجد Get-StartApps '{app_name}' — ننتقل للطريقة B")
                if raw:
                    log.append(f"   النتيجة الخام: {raw[:100]}")
        except Exception as e:
            log.append(f"⚠️ الطريقة A فشلت: {e} — ننتقل للطريقة B")

        # ═══════════════════════════════════════════════════════════════
        # METHOD B — Win+S keyboard search
        # ═══════════════════════════════════════════════════════════════
        log.append("━━━ الطريقة B: Windows Search (Win+S) ━━━")
        try:
            import pyperclip

            pyautogui.press('escape')
            time.sleep(0.3)
            pyautogui.hotkey('win', 's')
            time.sleep(1.2)

            pyautogui.hotkey('ctrl', 'a')
            time.sleep(0.1)
            pyperclip.copy(app_name)
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(2.0)

            log.append(f"⌨️ كتبت '{app_name}' في Windows Search")

            # Try OCR click first (native OCR word boxes)
            shot = pyautogui.screenshot()
            sw, sh = pyautogui.size()
            clicked = False
            try:
                needle = app_name.lower()
                best_x, best_y = None, None
                for wd in _ocr_word_boxes(shot):
                    word = str(wd.get('t', ''))
                    if not word.strip():
                        continue
                    if needle in word.lower():
                        x = int(wd['x']) + int(wd['w']) // 2
                        y = int(wd['y']) + int(wd['h']) // 2
                        # Prefer first match in the left search-panel area
                        if x < sw * 0.7:
                            best_x, best_y = x, y
                            break
                if best_x:
                    pyautogui.click(best_x, best_y)
                    clicked = True
                    log.append(f"🖱️ نقر OCR على '{app_name}' في ({best_x},{best_y})")
            except Exception:
                pass

            if not clicked:
                pyautogui.press('enter')
                log.append("⌨️ ضغط Enter على أول نتيجة")

            new_title = _wait_for_new_window(timeout_seconds)
            if new_title:
                log.append(f"✅ الطريقة B نجحت! النافذة: «{new_title}»")
                log.extend(_resolve_cloudflare_and_describe(new_title))
                return "\n".join(log)
            else:
                log.append("⚠️ الطريقة B: لم تظهر نافذة — ننتقل للطريقة C")
        except Exception as e:
            log.append(f"⚠️ الطريقة B فشلت: {e} — ننتقل للطريقة C")

        # ═══════════════════════════════════════════════════════════════
        # METHOD C — Direct exe search in common locations
        # ═══════════════════════════════════════════════════════════════
        log.append("━━━ الطريقة C: بحث مباشر عن .exe ━━━")
        try:
            import glob as _glob
            search_dirs = [
                r"C:\Program Files",
                r"C:\Program Files (x86)",
                os.path.expanduser(r"~\AppData\Local\Programs"),
                os.path.expanduser(r"~\AppData\Local"),
                os.path.expanduser(r"~\AppData\Roaming"),
                r"C:\Windows\System32",
            ]
            exe_name = app_name.lower().replace(" ", "") + ".exe"
            found_exe = None
            for d in search_dirs:
                pattern = os.path.join(d, "**", exe_name)
                matches = _glob.glob(pattern, recursive=True)
                if matches:
                    found_exe = matches[0]
                    break
                # Also try with spaces
                pattern2 = os.path.join(d, "**", f"*{app_name}*.exe")
                matches2 = _glob.glob(pattern2, recursive=True)
                if matches2:
                    found_exe = matches2[0]
                    break

            if found_exe:
                log.append(f"✅ وجدت: {found_exe}")
                subprocess.Popen([found_exe])
                new_title = _wait_for_new_window(timeout_seconds)
                if new_title:
                    log.append(f"✅ الطريقة C نجحت! النافذة: «{new_title}»")
                    log.extend(_resolve_cloudflare_and_describe(new_title))
                    return "\n".join(log)
                else:
                    log.append("⚠️ الطريقة C: تم تشغيل الملف لكن لم تظهر نافذة")
            else:
                log.append(f"⚠️ الطريقة C: لم أجد {exe_name} في المجلدات الشائعة")
        except Exception as e:
            log.append(f"⚠️ الطريقة C فشلت: {e}")

        # ═══════════════════════════════════════════════════════════════
        # FINAL: Check if app opened anyway (might be loading slowly)
        # ═══════════════════════════════════════════════════════════════
        log.append("⏳ انتظار إضافي 5 ثوانٍ قبل الاستسلام...")
        time.sleep(5)
        screen_info = _verify_screen()
        active = gw.getActiveWindowTitle() or ""

        if app_name.lower() in active.lower() or (wait_for_title and wait_for_title.lower() in active.lower()):
            log.append(f"✅ التطبيق '{app_name}' يعمل الآن! النافذة: «{active}»")
            log.extend(_resolve_cloudflare_and_describe(active))
            return "\n".join(log)

        log.append(f"❌ فشلت جميع الطرق الثلاث في فتح '{app_name}'.")
        log.append(screen_info)
        log.append(
            f"💡 جرّب يدوياً أو أعطِ المسار الكامل:\n"
            f"   launch_app_smart(app_name='اسم مختلف')"
        )
        return "\n".join(log)

    except Exception as exc:
        return f"❌ خطأ كامل في launch_app_smart: {exc}"
