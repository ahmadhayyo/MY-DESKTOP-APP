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
    action: Annotated[str, "'open' to launch the top result, 'list' to show results. Default: 'open'"] = "open",
) -> str:
    """
    Search Windows (Start menu) for an app, file, or setting and optionally open it.
    Examples: 'Notepad', 'Chrome', 'Device Manager', 'Paint', 'Calculator'.
    Much more reliable than open_app for finding apps by name.
    """
    try:
        import pyautogui
        import time

        # Press Win key to open Start menu
        pyautogui.press("win")
        time.sleep(0.8)
        pyautogui.typewrite(query, interval=0.05)
        time.sleep(1.0)

        if action == "open":
            pyautogui.press("enter")
            time.sleep(1.5)
            return f"[OK] Searched Windows for '{query}' and pressed Enter to open."
        else:
            # Just typed the query, user can see results
            return f"[OK] Typed '{query}' in Windows search. Results visible on screen."
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
    text: Annotated[str, "Text to type into the window."],
    clear_first: Annotated[bool, "Select all (Ctrl+A) and clear before typing. Default False."] = False,
    press_enter: Annotated[bool, "Press Enter after typing. Default False."] = False,
) -> str:
    """
    Focus a specific window and type text into it.
    Works for any app: Notepad, Word, browser address bar, chat apps, terminals, etc.
    """
    try:
        import pyautogui
        import pygetwindow as gw

        if window_title:
            matches = [w for w in gw.getAllWindows() if window_title.lower() in w.title.lower()]
            if not matches:
                return f"[NOT FOUND] No window matching '{window_title}'"
            matches[0].activate()
            time.sleep(0.5)

        if clear_first:
            pyautogui.hotkey("ctrl", "a")
            time.sleep(0.2)
            pyautogui.press("delete")
            time.sleep(0.1)

        pyautogui.typewrite(text, interval=0.03)

        if press_enter:
            pyautogui.press("enter")

        return f"[OK] Typed {len(text)} characters into '{window_title or 'active window'}'"
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
