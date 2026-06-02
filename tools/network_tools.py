"""
Network tools: IP info, connectivity checks, Wi-Fi management, port scanning.

Gives the agent visibility into the network state and basic control over
Windows networking (Wi-Fi, adapters, DNS, etc.).
"""

from __future__ import annotations

import subprocess
from typing import Annotated

from langchain_core.tools import tool

from config import PS_TIMEOUT


@tool
def get_network_info() -> str:
    """
    Get current network information: IP addresses, adapters, DNS, gateway.

    Returns a summary of all active network interfaces.
    """
    cmd = (
        "Get-NetIPConfiguration | Where-Object {$_.IPv4DefaultGateway -ne $null} | "
        "ForEach-Object { "
        "  '--- Interface: ' + $_.InterfaceAlias; "
        "  '    IPv4: ' + $_.IPv4Address.IPAddress; "
        "  '    Gateway: ' + $_.IPv4DefaultGateway.NextHop; "
        "  '    DNS: ' + ($_.DnsServer.ServerAddresses -join ', '); "
        "  '' "
        "}"
    )
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True, text=True, timeout=PS_TIMEOUT,
        )
        output = proc.stdout.strip()
        if not output:
            return "[INFO] No active network interfaces with default gateway found."
        return output
    except subprocess.TimeoutExpired:
        return "[TIMEOUT]"
    except FileNotFoundError:
        return "[ERROR] powershell.exe not found."
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def get_public_ip() -> str:
    """Get the public (external) IP address of this machine."""
    cmd = "(Invoke-WebRequest -Uri 'https://api.ipify.org' -UseBasicParsing -TimeoutSec 10).Content"
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True, text=True, timeout=15,
        )
        ip = proc.stdout.strip()
        if ip and not ip.startswith("["):
            return f"Public IP: {ip}"
        return f"[ERROR] Could not determine public IP. {proc.stderr.strip()}"
    except subprocess.TimeoutExpired:
        return "[TIMEOUT] Could not reach ipify.org"
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def ping_host(
    host: Annotated[str, "Hostname or IP to ping (e.g. 'google.com', '192.168.1.1')."],
    count: Annotated[int, "Number of ping packets."] = 4,
) -> str:
    """
    Ping a host to check connectivity and measure latency.

    Returns ping statistics (min/max/avg response time).
    """
    count = max(1, min(count, 20))
    cmd = f"Test-Connection -ComputerName '{host}' -Count {count} -ErrorAction Stop | Format-Table Address, ResponseTime -AutoSize | Out-String"
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True, text=True, timeout=30,
        )
        output = proc.stdout.strip()
        if proc.returncode != 0:
            return f"[FAILED] Cannot reach {host}: {proc.stderr.strip()}"
        return output or f"[OK] {host} is reachable"
    except subprocess.TimeoutExpired:
        return f"[TIMEOUT] Ping to {host} timed out."
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def check_port(
    host: Annotated[str, "Host to check."],
    port: Annotated[int, "TCP port number."],
) -> str:
    """
    Check if a specific TCP port is open on a host.

    Useful for verifying if a service is running/reachable.
    """
    cmd = (
        f"$t = New-Object Net.Sockets.TcpClient; "
        f"try {{ $t.Connect('{host}', {port}); 'OPEN' }} "
        f"catch {{ 'CLOSED' }} "
        f"finally {{ $t.Dispose() }}"
    )
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True, text=True, timeout=15,
        )
        result = proc.stdout.strip()
        if "OPEN" in result:
            return f"[OK] Port {port} on {host} is OPEN"
        return f"[INFO] Port {port} on {host} is CLOSED/FILTERED"
    except subprocess.TimeoutExpired:
        return f"[TIMEOUT] Connection to {host}:{port} timed out."
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def wifi_management(
    action: Annotated[str, "Action: 'list', 'connect', 'disconnect', 'status'."],
    network_name: Annotated[str, "Wi-Fi network name (SSID). Required for 'connect'."] = "",
    password: Annotated[str, "Wi-Fi password. Required for 'connect' to a new network."] = "",
) -> str:
    """
    Manage Wi-Fi connections.

    Actions:
      - 'status'     → Show current Wi-Fi connection status
      - 'list'       → List available Wi-Fi networks
      - 'connect'    → Connect to a specific network
      - 'disconnect' → Disconnect from current Wi-Fi
    """
    action = action.lower().strip()

    if action == "status":
        cmd = "netsh wlan show interfaces"
    elif action == "list":
        cmd = "netsh wlan show networks mode=bssid"
    elif action == "disconnect":
        cmd = "netsh wlan disconnect"
    elif action == "connect":
        if not network_name:
            return "[ERROR] 'network_name' (SSID) is required for 'connect'."
        if password:
            # Create a temporary profile and connect
            profile_xml = f'''<?xml version="1.0"?>
<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">
    <name>{network_name}</name>
    <SSIDConfig><SSID><name>{network_name}</name></SSID></SSIDConfig>
    <connectionType>ESS</connectionType>
    <connectionMode>auto</connectionMode>
    <MSM><security>
        <authEncryption><authentication>WPA2PSK</authentication><encryption>AES</encryption></authEncryption>
        <sharedKey><keyType>passPhrase</keyType><protected>false</protected><keyMaterial>{password}</keyMaterial></sharedKey>
    </security></MSM>
</WLANProfile>'''
            # Write profile, add it, connect
            cmd = (
                f"$xml = @'\n{profile_xml}\n'@; "
                f"$f = \"$env:TEMP\\wifi_{network_name}.xml\"; "
                f"$xml | Out-File -Encoding utf8 $f; "
                f"netsh wlan add profile filename=$f; "
                f"netsh wlan connect name='{network_name}'; "
                f"Remove-Item $f"
            )
        else:
            cmd = f"netsh wlan connect name='{network_name}'"
    else:
        return f"[ERROR] Unknown action '{action}'. Use: status, list, connect, disconnect."

    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True, text=True, timeout=20,
        )
        output = proc.stdout.strip()
        if proc.returncode != 0 and proc.stderr.strip():
            output += f"\n[STDERR] {proc.stderr.strip()}"
        return output or "[OK]"
    except subprocess.TimeoutExpired:
        return "[TIMEOUT]"
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def dns_lookup(
    hostname: Annotated[str, "Domain name to resolve."],
    record_type: Annotated[str, "DNS record type: A, AAAA, MX, CNAME, TXT, NS."] = "A",
) -> str:
    """
    Perform a DNS lookup for a hostname.

    Useful for troubleshooting network issues or finding mail servers.
    """
    cmd = f"Resolve-DnsName -Name '{hostname}' -Type {record_type} -ErrorAction Stop | Format-List | Out-String"
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True, text=True, timeout=15,
        )
        output = proc.stdout.strip()
        if proc.returncode != 0:
            return f"[ERROR] DNS lookup failed: {proc.stderr.strip()}"
        return output or f"[OK] No {record_type} records found for {hostname}"
    except subprocess.TimeoutExpired:
        return "[TIMEOUT]"
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"
