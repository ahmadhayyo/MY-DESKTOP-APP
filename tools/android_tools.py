"""
Android device control via ADB (Android Debug Bridge).

Lets the agent operate a connected Android phone/tablet the same way it
controls the Windows desktop: screenshots, tap/swipe, type text, launch/
install/uninstall apps, push/pull files, run shell commands.

Requirements (one-time, on the PHONE): enable Developer Options → USB
debugging, connect via USB, and tap "Allow" on the RSA-authorization prompt
that appears the first time. `adb.exe` is auto-detected (PATH, or common
install locations like Downloads/platform-tools) — no manual setup needed
on the PC side.

Scope note: this only does what ADB itself permits. Apps with screenshot/
interaction protections (banking apps, DRM content, some games) block it
by design — that is the OS protecting the user, not a tool limitation.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Annotated

from langchain_core.tools import tool

from config import DESKTOP_DIR

_ADB_TIMEOUT = 30
_ANDROID_DIR = DESKTOP_DIR / "HAYO_Android"

# Common human-friendly key names → Android keyevent codes.
_KEYCODES: dict[str, str] = {
    "back": "4", "home": "3", "power": "26", "menu": "82",
    "enter": "66", "tab": "61", "space": "62", "escape": "111",
    "volume_up": "24", "volume_down": "25", "mute": "164",
    "camera": "27", "app_switch": "187", "recents": "187",
    "delete": "67", "backspace": "67",
    "up": "19", "down": "20", "left": "21", "right": "22",
    "play_pause": "85", "next": "87", "previous": "88",
}


def _find_adb() -> str | None:
    """Locate adb.exe: PATH first, then common install locations."""
    import shutil
    found = shutil.which("adb")
    if found:
        return found
    candidates = [
        Path.home() / "Downloads" / "platform-tools" / "adb.exe",
        Path.home() / "AppData" / "Local" / "Android" / "Sdk" / "platform-tools" / "adb.exe",
        Path("C:/Android/platform-tools/adb.exe"),
        Path("C:/platform-tools/adb.exe"),
        Path(os.environ.get("ANDROID_HOME", "")) / "platform-tools" / "adb.exe"
        if os.environ.get("ANDROID_HOME") else None,
        Path(os.environ.get("ANDROID_SDK_ROOT", "")) / "platform-tools" / "adb.exe"
        if os.environ.get("ANDROID_SDK_ROOT") else None,
    ]
    for c in candidates:
        if c and c.is_file():
            return str(c)
    return None


def _run_adb(args: list[str], timeout: int = _ADB_TIMEOUT) -> tuple[int, str, str]:
    """Run `adb <args>`. Returns (returncode, stdout, stderr)."""
    adb = _find_adb()
    if not adb:
        return (
            -1, "",
            "adb.exe not found. Install Android Platform Tools "
            "(https://developer.android.com/tools/releases/platform-tools) "
            "or ensure it's in PATH / Downloads/platform-tools.",
        )
    try:
        proc = subprocess.run(
            [adb] + args, capture_output=True, text=True, timeout=timeout,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", f"adb command timed out after {timeout}s"
    except Exception as exc:
        return -1, "", f"{type(exc).__name__}: {exc}"


def _list_ready_devices() -> list[str]:
    """Serials of devices in 'device' (ready/authorized) state."""
    code, out, _ = _run_adb(["devices"])
    if code != 0:
        return []
    serials = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            serials.append(parts[0])
    return serials


def _pick_device(device: str) -> tuple[str | None, str | None]:
    """Resolve which device serial to target.

    Returns (serial, error_message). If `device` is given, use it as-is
    (adb will error out clearly if invalid). If empty, auto-pick when
    exactly one device is ready; otherwise return an actionable error.
    """
    if device.strip():
        return device.strip(), None
    ready = _list_ready_devices()
    if not ready:
        return None, (
            "❌ لا يوجد جهاز أندرويد متصل وجاهز. تأكد من:\n"
            "  1. توصيل الهاتف بكابل USB\n"
            "  2. تفعيل 'خيارات المطوّر' ← 'تصحيح USB' على الهاتف\n"
            "  3. الموافقة على نافذة تفويض RSA التي تظهر على شاشة الهاتف\n"
            "تحقّق بـ android_devices()"
        )
    if len(ready) == 1:
        return ready[0], None
    return None, (
        f"⚠️ يوجد {len(ready)} أجهزة متصلة — حدّد device: {', '.join(ready)}"
    )


def _adb_for_device(args: list[str], device: str, timeout: int = _ADB_TIMEOUT):
    """_run_adb with -s <serial> auto-resolved; returns (code, out, err, serial)."""
    serial, err = _pick_device(device)
    if err:
        return -1, "", err, None
    code, out, stderr = _run_adb(["-s", serial] + args, timeout=timeout)
    return code, out, stderr, serial


@tool
def android_devices() -> str:
    """List Android devices/emulators connected via ADB, with their state.

    States: 'device' = ready to use, 'unauthorized' = tap Allow on the phone's
    RSA prompt, 'offline' = reconnect the cable. Also reports if adb.exe itself
    is missing.
    """
    adb = _find_adb()
    if not adb:
        return (
            "❌ adb.exe غير موجود على هذا الجهاز. حمّله من:\n"
            "https://developer.android.com/tools/releases/platform-tools"
        )
    code, out, err = _run_adb(["devices", "-l"])
    if code != 0:
        return f"❌ فشل تشغيل adb: {err}"
    lines = out.splitlines()
    if len(lines) <= 1:
        return "📱 لا توجد أجهزة متصلة حالياً. وصّل الهاتف وفعّل تصحيح USB."
    result = ["📱 أجهزة أندرويد المتصلة:\n"]
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.split()
        serial = parts[0]
        state = parts[1] if len(parts) > 1 else "?"
        extra = " ".join(parts[2:])
        icon = "✅" if state == "device" else ("🔒" if state == "unauthorized" else "⚠️")
        result.append(f"  {icon} `{serial}` — {state}  {extra}")
    return "\n".join(result)


@tool
def android_device_info(
    device: Annotated[str, "Device serial from android_devices(). Empty = auto-pick if only one connected."] = "",
) -> str:
    """Get device info: model, Android version, battery, storage, screen resolution."""
    serial, err = _pick_device(device)
    if err:
        return err

    def _prop(key: str) -> str:
        c, o, _ = _run_adb(["-s", serial, "shell", "getprop", key])
        return o.strip() if c == 0 else "?"

    model = _prop("ro.product.model")
    manufacturer = _prop("ro.product.manufacturer")
    android_ver = _prop("ro.build.version.release")
    sdk = _prop("ro.build.version.sdk")

    _, battery_raw, _ = _run_adb(["-s", serial, "shell", "dumpsys", "battery"])
    m = re.search(r"level:\s*(\d+)", battery_raw)
    battery = f"{m.group(1)}%" if m else "?"

    _, wm_raw, _ = _run_adb(["-s", serial, "shell", "wm", "size"])
    m2 = re.search(r"(\d+x\d+)", wm_raw)
    resolution = m2.group(1) if m2 else "?"

    _, storage_raw, _ = _run_adb(["-s", serial, "shell", "df", "/data"])
    storage_line = storage_raw.splitlines()[-1] if storage_raw else ""

    return (
        f"📱 **{manufacturer} {model}**\n"
        f"  السيريال: `{serial}`\n"
        f"  إصدار أندرويد: {android_ver} (SDK {sdk})\n"
        f"  البطارية: {battery}\n"
        f"  دقة الشاشة: {resolution}\n"
        f"  التخزين (/data): {storage_line}"
    )


@tool
def android_screenshot(
    device: Annotated[str, "Device serial. Empty = auto-pick if only one connected."] = "",
) -> str:
    """Capture the phone's screen and save it to Desktop/HAYO_Android/.

    Use this before tap/swipe to see current screen coordinates and content.
    """
    serial, err = _pick_device(device)
    if err:
        return err

    remote = "/sdcard/hayo_screenshot.png"
    code, _, stderr = _run_adb(["-s", serial, "shell", "screencap", "-p", remote])
    if code != 0:
        return f"❌ فشل التقاط الشاشة: {stderr}"

    _ANDROID_DIR.mkdir(parents=True, exist_ok=True)
    local = _ANDROID_DIR / f"screenshot_{int(time.time())}.png"
    code2, _, stderr2 = _run_adb(["-s", serial, "pull", remote, str(local)])
    _run_adb(["-s", serial, "shell", "rm", remote])  # cleanup device copy
    if code2 != 0:
        return f"❌ فشل سحب لقطة الشاشة: {stderr2}"
    return f"✅ لقطة الشاشة محفوظة: {local}"


@tool
def android_tap(
    x: Annotated[int, "X coordinate (pixels). Get from android_screenshot()."],
    y: Annotated[int, "Y coordinate (pixels)."],
    device: Annotated[str, "Device serial. Empty = auto-pick if only one connected."] = "",
) -> str:
    """Tap the screen at (x, y). Take a android_screenshot() first to find coordinates."""
    code, _, err, serial = _adb_for_device(["shell", "input", "tap", str(x), str(y)], device)
    if code != 0:
        return err or f"❌ فشل النقر عند ({x},{y})"
    return f"✅ تم النقر عند ({x},{y}) على {serial}"


@tool
def android_swipe(
    x1: Annotated[int, "Start X."], y1: Annotated[int, "Start Y."],
    x2: Annotated[int, "End X."], y2: Annotated[int, "End Y."],
    duration_ms: Annotated[int, "Swipe duration in ms. Higher = slower drag."] = 300,
    device: Annotated[str, "Device serial. Empty = auto-pick if only one connected."] = "",
) -> str:
    """Swipe/drag from (x1,y1) to (x2,y2). Also useful for scrolling (swipe up/down)."""
    code, _, err, serial = _adb_for_device(
        ["shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms)],
        device,
    )
    if code != 0:
        return err or "❌ فشل السحب"
    return f"✅ تم السحب من ({x1},{y1}) إلى ({x2},{y2}) على {serial}"


@tool
def android_input_text(
    text: Annotated[str, "Text to type into the currently focused field."],
    device: Annotated[str, "Device serial. Empty = auto-pick if only one connected."] = "",
) -> str:
    """Type text into whatever input field is currently focused on the phone.

    Tap the field first with android_tap(). Arabic/Unicode text may not render
    correctly via ADB's `input text` — for those, prefer android_shell with
    an IME-based workaround if this fails.
    """
    # `adb shell input text` needs spaces escaped and can't handle most
    # special/Unicode chars reliably — replace spaces, keep it simple.
    escaped = text.replace(" ", "%s")
    code, _, err, serial = _adb_for_device(["shell", "input", "text", escaped], device)
    if code != 0:
        return err or "❌ فشلت الكتابة"
    return f"✅ تمت كتابة النص على {serial}"


@tool
def android_key_event(
    key: Annotated[
        str,
        "Key name: back, home, power, menu, enter, tab, volume_up, volume_down, "
        "delete, up, down, left, right, app_switch, camera, play_pause. "
        "Or a raw numeric Android keycode.",
    ],
    device: Annotated[str, "Device serial. Empty = auto-pick if only one connected."] = "",
) -> str:
    """Press a hardware/software key on the phone (back, home, power, volume, etc.)."""
    code_str = _KEYCODES.get(key.strip().lower(), key.strip())
    if not code_str.isdigit():
        return f"❌ مفتاح غير معروف: '{key}'. الأسماء المتاحة: {', '.join(_KEYCODES)}"
    code, _, err, serial = _adb_for_device(["shell", "input", "keyevent", code_str], device)
    if code != 0:
        return err or f"❌ فشل الضغط على '{key}'"
    return f"✅ تم الضغط على '{key}' على {serial}"


@tool
def android_list_apps(
    system_apps: Annotated[bool, "Include pre-installed system apps too. Default: only user-installed."] = False,
    device: Annotated[str, "Device serial. Empty = auto-pick if only one connected."] = "",
) -> str:
    """List installed apps (package names) on the phone."""
    args = ["shell", "pm", "list", "packages"]
    if not system_apps:
        args.append("-3")  # third-party (user-installed) only
    code, out, err, serial = _adb_for_device(args, device)
    if code != 0:
        return err or "❌ فشل جلب قائمة التطبيقات"
    packages = sorted(line.replace("package:", "").strip() for line in out.splitlines() if line.strip())
    if not packages:
        return "📦 لا توجد تطبيقات."
    header = f"📦 {len(packages)} تطبيق على {serial}"
    if len(packages) > 150:
        return header + "\n" + "\n".join(packages[:150]) + f"\n… (+{len(packages) - 150} أخرى)"
    return header + "\n" + "\n".join(packages)


@tool
def android_launch_app(
    package: Annotated[str, "Package name, e.g. 'com.whatsapp' or 'com.android.chrome'. Find it via android_list_apps()."],
    device: Annotated[str, "Device serial. Empty = auto-pick if only one connected."] = "",
) -> str:
    """Launch an app on the phone by its package name."""
    code, out, err, serial = _adb_for_device(
        ["shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"],
        device,
    )
    if code != 0 or "no activities found" in (out + err).lower():
        return f"❌ تعذّر فتح '{package}' — تحقّق من اسم الحزمة عبر android_list_apps(): {err or out}"
    return f"✅ تم فتح '{package}' على {serial}"


@tool
def android_install_apk(
    apk_path: Annotated[str, "Local path to the .apk file on THIS computer."],
    device: Annotated[str, "Device serial. Empty = auto-pick if only one connected."] = "",
) -> str:
    """Install an APK file from this computer onto the phone."""
    p = Path(apk_path)
    if not p.is_file():
        return f"❌ الملف غير موجود: {apk_path}"
    code, out, err, serial = _adb_for_device(["install", "-r", str(p)], device, timeout=120)
    if code != 0 or "success" not in (out + err).lower():
        return f"❌ فشل التثبيت: {err or out}"
    return f"✅ تم تثبيت '{p.name}' على {serial}"


@tool
def android_uninstall_app(
    package: Annotated[str, "Package name to uninstall, e.g. 'com.example.app'."],
    device: Annotated[str, "Device serial. Empty = auto-pick if only one connected."] = "",
) -> str:
    """Uninstall an app from the phone by its package name."""
    code, out, err, serial = _adb_for_device(["uninstall", package], device, timeout=60)
    if code != 0 or "success" not in (out + err).lower():
        return f"❌ فشل إلغاء التثبيت: {err or out}"
    return f"✅ تم إلغاء تثبيت '{package}' من {serial}"


@tool
def android_push_file(
    local_path: Annotated[str, "Path to the file on THIS computer."],
    remote_path: Annotated[str, "Destination path on the phone, e.g. '/sdcard/Download/file.pdf'."],
    device: Annotated[str, "Device serial. Empty = auto-pick if only one connected."] = "",
) -> str:
    """Copy a file from this computer to the phone (e.g. into /sdcard/Download)."""
    p = Path(local_path)
    if not p.is_file():
        return f"❌ الملف غير موجود: {local_path}"
    code, _, err, serial = _adb_for_device(["push", str(p), remote_path], device, timeout=120)
    if code != 0:
        return f"❌ فشل النقل: {err}"
    return f"✅ تم نقل '{p.name}' إلى {remote_path} على {serial}"


@tool
def android_pull_file(
    remote_path: Annotated[str, "Path on the phone, e.g. '/sdcard/DCIM/Camera/photo.jpg'."],
    local_path: Annotated[str, "Where to save on this computer. Empty = Desktop/HAYO_Android/."] = "",
    device: Annotated[str, "Device serial. Empty = auto-pick if only one connected."] = "",
) -> str:
    """Copy a file from the phone to this computer."""
    if not local_path.strip():
        _ANDROID_DIR.mkdir(parents=True, exist_ok=True)
        local_path = str(_ANDROID_DIR / Path(remote_path).name)
    code, _, err, serial = _adb_for_device(["pull", remote_path, local_path], device, timeout=120)
    if code != 0:
        return f"❌ فشل السحب: {err}"
    return f"✅ تم حفظ '{remote_path}' في: {local_path}"


@tool
def android_open_url(
    url: Annotated[str, "URL to open in the phone's default browser."],
    device: Annotated[str, "Device serial. Empty = auto-pick if only one connected."] = "",
) -> str:
    """Open a URL on the phone's default browser."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    code, out, err, serial = _adb_for_device(
        ["shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", url], device,
    )
    if code != 0:
        return f"❌ فشل فتح الرابط: {err}"
    return f"✅ تم فتح {url} على {serial}"


@tool
def android_shell(
    command: Annotated[str, "Raw shell command to run on the phone (adb shell <command>)."],
    device: Annotated[str, "Device serial. Empty = auto-pick if only one connected."] = "",
) -> str:
    """Run a raw shell command on the phone via `adb shell`. Use for anything not
    covered by the other android_* tools (e.g. checking a specific setting,
    listing a directory on /sdcard, reading a log)."""
    code, out, err, serial = _adb_for_device(["shell", command], device, timeout=60)
    if code != 0 and not out:
        return f"❌ [{serial}] {err}"
    result = out or "(no output)"
    if err:
        result += f"\n[STDERR] {err}"
    return result
