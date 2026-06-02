"""
Process management tools: inspect, kill, manage Windows processes and services.

Provides more granular control than just taskkill — lets the agent understand
what's running, find resource hogs, start/stop Windows services, etc.
"""

from __future__ import annotations

import subprocess
from typing import Annotated

from langchain_core.tools import tool

from config import PS_TIMEOUT


@tool
def get_system_info() -> str:
    """
    Get essential system information: OS, CPU, RAM, disk usage.

    Uses fast registry/WMI queries (never Get-ComputerInfo which is too slow).
    """
    commands = [
        "(Get-WmiObject Win32_OperatingSystem).Caption",
        "(Get-WmiObject Win32_Processor).Name",
        "$os=Get-WmiObject Win32_OperatingSystem; "
        "'{0:N0} MB total, {1:N0} MB free' -f ($os.TotalVisibleMemorySize/1024), ($os.FreePhysicalMemory/1024)",
        "Get-WmiObject Win32_LogicalDisk -Filter \"DriveType=3\" | "
        "ForEach-Object { '{0} {1:N1}GB free / {2:N1}GB total' -f $_.DeviceID, ($_.FreeSpace/1GB), ($_.Size/1GB) }",
    ]
    script = "; ".join([f"'--- OS:'; {commands[0]}",
                        f"'--- CPU:'; {commands[1]}",
                        f"'--- RAM:'; {commands[2]}",
                        f"'--- Disk:'; {commands[3]}"])
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=PS_TIMEOUT,
        )
        return proc.stdout.strip() or proc.stderr.strip() or "[OK] (no output)"
    except subprocess.TimeoutExpired:
        return "[TIMEOUT] System info query took too long."
    except FileNotFoundError:
        return "[ERROR] powershell.exe not found."
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def list_processes(
    sort_by: Annotated[str, "Sort by: 'cpu', 'memory', or 'name'. Default: 'memory'."] = "memory",
    top_n: Annotated[int, "Number of top processes to show."] = 20,
    filter_name: Annotated[str, "Optional filter: only show processes containing this string."] = "",
) -> str:
    """
    List running processes sorted by CPU or memory usage.

    Returns a table of the top N processes with PID, name, CPU%, and memory.
    """
    if sort_by == "cpu":
        sort_prop = "CPU"
    elif sort_by == "name":
        sort_prop = "ProcessName"
    else:
        sort_prop = "WorkingSet64"

    filter_clause = ""
    if filter_name:
        filter_clause = f" | Where-Object {{ $_.ProcessName -like '*{filter_name}*' }}"

    cmd = (
        f"Get-Process{filter_clause} | "
        f"Sort-Object {sort_prop} -Descending | "
        f"Select-Object -First {top_n} "
        f"@{{N='PID';E={{$_.Id}}}}, "
        f"@{{N='Name';E={{$_.ProcessName}}}}, "
        f"@{{N='CPU_s';E={{[math]::Round($_.CPU,1)}}}}, "
        f"@{{N='RAM_MB';E={{[math]::Round($_.WorkingSet64/1MB,1)}}}} | "
        f"Format-Table -AutoSize | Out-String"
    )
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True, text=True, timeout=PS_TIMEOUT,
        )
        return proc.stdout.strip() or "(no processes found)"
    except subprocess.TimeoutExpired:
        return "[TIMEOUT]"
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def kill_process(
    target: Annotated[str, "Process name (e.g. 'chrome') or PID number."],
    force: Annotated[bool, "Force kill without graceful shutdown attempt."] = False,
) -> str:
    """
    Kill a process by name or PID.

    If target is a number, kills by PID. Otherwise kills by process name.
    """
    force_flag = "-Force" if force else ""

    # Determine if it's a PID or name
    if target.strip().isdigit():
        cmd = f"Stop-Process -Id {target} {force_flag} -ErrorAction Stop"
    else:
        name = target.strip().removesuffix(".exe")
        cmd = f"Stop-Process -Name '{name}' {force_flag} -ErrorAction Stop"

    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True, text=True, timeout=15,
        )
        if proc.returncode == 0:
            return f"[OK] Killed: {target}"
        return f"[ERROR] {proc.stderr.strip()}"
    except subprocess.TimeoutExpired:
        return "[TIMEOUT] Process kill timed out."
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def manage_service(
    service_name: Annotated[str, "Windows service name (e.g. 'wuauserv', 'Spooler')."],
    action: Annotated[str, "Action: 'status', 'start', 'stop', 'restart'."],
) -> str:
    """
    Manage a Windows service: check status, start, stop, or restart.

    Examples:
      manage_service('Spooler', 'status')   → check printer spooler status
      manage_service('wuauserv', 'stop')    → stop Windows Update service
    """
    action = action.lower().strip()

    if action == "status":
        cmd = f"Get-Service '{service_name}' | Format-List Name, Status, StartType | Out-String"
    elif action == "start":
        cmd = f"Start-Service '{service_name}' -ErrorAction Stop; 'Started'"
    elif action == "stop":
        cmd = f"Stop-Service '{service_name}' -Force -ErrorAction Stop; 'Stopped'"
    elif action == "restart":
        cmd = f"Restart-Service '{service_name}' -Force -ErrorAction Stop; 'Restarted'"
    else:
        return f"[ERROR] Unknown action '{action}'. Use: status, start, stop, restart."

    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True, text=True, timeout=30,
        )
        output = proc.stdout.strip()
        if proc.returncode != 0:
            output += f"\n[STDERR] {proc.stderr.strip()}"
        return output or "[OK]"
    except subprocess.TimeoutExpired:
        return "[TIMEOUT]"
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def scheduled_task(
    action: Annotated[str, "Action: 'list', 'create', 'delete', 'run'."],
    name: Annotated[str, "Task name. Required for create/delete/run."] = "",
    command: Annotated[str, "Command to run (for 'create' action)."] = "",
    trigger: Annotated[str, "Trigger: 'once', 'daily', 'startup'. For 'create'."] = "once",
    time_str: Annotated[str, "Time in HH:MM format (24h). For 'create' with 'once'/'daily'."] = "",
) -> str:
    """
    Manage Windows Task Scheduler tasks.

    Examples:
      scheduled_task('list')
      scheduled_task('create', name='Backup', command='robocopy ...', trigger='daily', time_str='02:00')
      scheduled_task('run', name='Backup')
      scheduled_task('delete', name='Backup')
    """
    action = action.lower().strip()

    if action == "list":
        cmd = "Get-ScheduledTask | Where-Object {$_.State -ne 'Disabled'} | Select-Object TaskName, State, TaskPath | Format-Table -AutoSize | Out-String"
    elif action == "run":
        if not name:
            return "[ERROR] 'name' is required for 'run' action."
        cmd = f"Start-ScheduledTask -TaskName '{name}'; 'Task started: {name}'"
    elif action == "delete":
        if not name:
            return "[ERROR] 'name' is required for 'delete' action."
        cmd = f"Unregister-ScheduledTask -TaskName '{name}' -Confirm:$false; 'Deleted: {name}'"
    elif action == "create":
        if not name or not command:
            return "[ERROR] 'name' and 'command' are required for 'create'."
        trigger_cmd = "$t = New-ScheduledTaskTrigger -Once -At (Get-Date)"
        if trigger == "daily" and time_str:
            trigger_cmd = f"$t = New-ScheduledTaskTrigger -Daily -At '{time_str}'"
        elif trigger == "startup":
            trigger_cmd = "$t = New-ScheduledTaskTrigger -AtStartup"
        elif trigger == "once" and time_str:
            trigger_cmd = f"$t = New-ScheduledTaskTrigger -Once -At '{time_str}'"

        cmd = (
            f"{trigger_cmd}; "
            f"$a = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-Command \"{command}\"'; "
            f"Register-ScheduledTask -TaskName '{name}' -Trigger $t -Action $a -Force; "
            f"'Created: {name}'"
        )
    else:
        return f"[ERROR] Unknown action '{action}'. Use: list, create, delete, run."

    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True, text=True, timeout=30,
        )
        output = proc.stdout.strip()
        if proc.returncode != 0 and proc.stderr.strip():
            output += f"\n[STDERR] {proc.stderr.strip()}"
        return output or "[OK]"
    except subprocess.TimeoutExpired:
        return "[TIMEOUT]"
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"
