"""
Audio and media tools: volume control, text-to-speech, notifications.

Gives the agent the ability to control system audio, play sounds,
speak text aloud, and show Windows notifications.
"""

from __future__ import annotations

import subprocess
from typing import Annotated

from langchain_core.tools import tool


@tool
def volume_control(
    action: Annotated[str, "Action: 'get', 'set', 'mute', 'unmute', 'up', 'down'."],
    level: Annotated[int, "Volume level 0-100. Required for 'set'."] = -1,
    step: Annotated[int, "Volume step for 'up'/'down' (default 10)."] = 10,
) -> str:
    """
    Control system audio volume.

    Actions:
      - 'get'    → Current volume level (0-100)
      - 'set'    → Set volume to specific level (0-100)
      - 'mute'   → Mute system audio
      - 'unmute' → Unmute system audio
      - 'up'     → Increase volume by step (default +10)
      - 'down'   → Decrease volume by step (default -10)
    """
    action = action.lower().strip()

    # Use nircmd for volume control (common on Windows), fallback to PowerShell with audio COM
    volume_script = """
Add-Type -TypeDefinition @'
using System.Runtime.InteropServices;
[Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioEndpointVolume {
    int _0(); int _1(); int _2(); int _3();
    int SetMasterVolumeLevelScalar(float fLevel, System.Guid pguidEventContext);
    int _5();
    int GetMasterVolumeLevelScalar(out float pfLevel);
    int SetMute([MarshalAs(UnmanagedType.Bool)] bool bMute, System.Guid pguidEventContext);
    int GetMute(out bool pbMute);
}
[Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDevice { int Activate(ref System.Guid iid, int dwClsCtx, System.IntPtr pActivationParams, [MarshalAs(UnmanagedType.IUnknown)] out object ppInterface); }
[Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceEnumerator { int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice ppDevice); }
[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] class MMDeviceEnumerator {}
'@
$enum = New-Object MMDeviceEnumerator
$dev = $null; $enum.GetDefaultAudioEndpoint(0, 1, [ref]$dev)
$iid = [Guid]'5CDF2C82-841E-4546-9722-0CF74078229A'
$epv = $null; $dev.Activate([ref]$iid, 23, [IntPtr]::Zero, [ref]$epv)
$vol = [IAudioEndpointVolume]$epv
"""

    if action == "get":
        cmd = volume_script + "$l=0.0; $vol.GetMasterVolumeLevelScalar([ref]$l); [math]::Round($l*100)"
    elif action == "set":
        if level < 0 or level > 100:
            return "[ERROR] Level must be 0-100."
        scalar = level / 100.0
        cmd = volume_script + f"$vol.SetMasterVolumeLevelScalar({scalar}, [Guid]::Empty); 'Volume set to {level}%'"
    elif action == "mute":
        cmd = volume_script + "$vol.SetMute($true, [Guid]::Empty); 'Muted'"
    elif action == "unmute":
        cmd = volume_script + "$vol.SetMute($false, [Guid]::Empty); 'Unmuted'"
    elif action == "up":
        cmd = volume_script + (
            f"$l=0.0; $vol.GetMasterVolumeLevelScalar([ref]$l); "
            f"$new=[math]::Min(1.0, $l + {step/100.0}); "
            f"$vol.SetMasterVolumeLevelScalar($new, [Guid]::Empty); "
            f"'Volume: ' + [math]::Round($new*100) + '%'"
        )
    elif action == "down":
        cmd = volume_script + (
            f"$l=0.0; $vol.GetMasterVolumeLevelScalar([ref]$l); "
            f"$new=[math]::Max(0.0, $l - {step/100.0}); "
            f"$vol.SetMasterVolumeLevelScalar($new, [Guid]::Empty); "
            f"'Volume: ' + [math]::Round($new*100) + '%'"
        )
    else:
        return f"[ERROR] Unknown action '{action}'. Use: get, set, mute, unmute, up, down."

    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True, text=True, timeout=15,
        )
        output = proc.stdout.strip()
        if proc.returncode != 0:
            # Fallback: use nircmd if available
            return _nircmd_volume_fallback(action, level, step)
        return output or "[OK]"
    except FileNotFoundError:
        return "[ERROR] powershell.exe not found."
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


def _nircmd_volume_fallback(action: str, level: int, step: int) -> str:
    """Fallback volume control using SendKeys."""
    # Use VBScript-based approach as fallback
    if action == "mute":
        vbs = 'CreateObject("WScript.Shell").SendKeys(chr(&HAD))'
    elif action == "up":
        vbs = 'CreateObject("WScript.Shell").SendKeys(chr(&HAF))'
    elif action == "down":
        vbs = 'CreateObject("WScript.Shell").SendKeys(chr(&HAE))'
    else:
        return f"[ERROR] Fallback volume control only supports mute/up/down."

    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             f"$vbs = '{vbs}'; $f = \"$env:TEMP\\vol.vbs\"; $vbs | Out-File $f -Encoding ascii; cscript //nologo $f; Remove-Item $f"],
            capture_output=True, text=True, timeout=10,
        )
        return "[OK] Volume adjusted"
    except Exception:
        return "[ERROR] Volume control failed on all methods."


@tool
def text_to_speech(
    text: Annotated[str, "Text to speak aloud."],
    rate: Annotated[int, "Speech rate: -10 (slow) to 10 (fast). Default 0."] = 0,
    volume: Annotated[int, "Speech volume: 0-100. Default 100."] = 100,
) -> str:
    """
    Speak text aloud using Windows SAPI (text-to-speech).

    The agent can use this to read content aloud, announce results,
    or provide audio feedback to the user.
    """
    # Escape single quotes for PowerShell
    escaped = text.replace("'", "''")
    rate = max(-10, min(10, rate))
    volume = max(0, min(100, volume))

    cmd = (
        f"Add-Type -AssemblyName System.Speech; "
        f"$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$s.Rate = {rate}; $s.Volume = {volume}; "
        f"$s.Speak('{escaped}'); "
        f"$s.Dispose(); 'Spoken'"
    )
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True, text=True, timeout=60,
        )
        if "Spoken" in proc.stdout:
            return f"[OK] Spoke: '{text[:80]}...'" if len(text) > 80 else f"[OK] Spoke: '{text}'"
        return f"[ERROR] TTS failed: {proc.stderr.strip()}"
    except subprocess.TimeoutExpired:
        return "[TIMEOUT] Speech took too long."
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def show_notification(
    title: Annotated[str, "Notification title."],
    message: Annotated[str, "Notification body text."],
    icon: Annotated[str, "Icon type: 'info', 'warning', 'error'. Default 'info'."] = "info",
) -> str:
    """
    Show a Windows toast notification (balloon tip in system tray).

    Use this to alert the user when a long task completes.
    """
    icon_map = {"info": "Info", "warning": "Warning", "error": "Error"}
    icon_type = icon_map.get(icon.lower(), "Info")

    escaped_title = title.replace("'", "''")
    escaped_msg = message.replace("'", "''")

    cmd = (
        "[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; "
        "$n = New-Object System.Windows.Forms.NotifyIcon; "
        "$n.Icon = [System.Drawing.SystemIcons]::Information; "
        "$n.Visible = $true; "
        f"$n.ShowBalloonTip(5000, '{escaped_title}', '{escaped_msg}', "
        f"[System.Windows.Forms.ToolTipIcon]::{icon_type}); "
        "Start-Sleep -Seconds 3; "
        "$n.Dispose(); 'Shown'"
    )
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True, text=True, timeout=15,
        )
        if "Shown" in proc.stdout:
            return f"[OK] Notification shown: {title}"
        return f"[ERROR] {proc.stderr.strip()}"
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def play_sound(
    path: Annotated[str, "Path to a .wav file, or 'beep' for system beep, or 'asterisk'/'hand'/'exclamation' for system sounds."],
) -> str:
    """
    Play a sound file or system sound.

    Examples:
      play_sound('beep')                    → System beep
      play_sound('asterisk')                → Windows asterisk sound
      play_sound('C:/Users/PT/Music/a.wav') → Play a WAV file
    """
    system_sounds = {
        "beep": "[Console]::Beep(800, 300)",
        "asterisk": "[System.Media.SystemSounds]::Asterisk.Play()",
        "hand": "[System.Media.SystemSounds]::Hand.Play()",
        "exclamation": "[System.Media.SystemSounds]::Exclamation.Play()",
        "question": "[System.Media.SystemSounds]::Question.Play()",
    }

    key = path.lower().strip()
    if key in system_sounds:
        cmd = system_sounds[key] + "; 'Played'"
    else:
        escaped = path.replace("'", "''")
        cmd = (
            f"$p = New-Object System.Media.SoundPlayer('{escaped}'); "
            f"$p.PlaySync(); $p.Dispose(); 'Played'"
        )

    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True, text=True, timeout=30,
        )
        if "Played" in proc.stdout:
            return f"[OK] Played: {path}"
        return f"[ERROR] {proc.stderr.strip()}"
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"
