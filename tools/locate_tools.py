"""
Locate Tools — find ANY file or application anywhere on the computer.

Gives the agent a real "search my whole PC" capability, layered for speed:

  1. Windows Search index (instant, but only covers indexed user folders).
  2. Direct scan of the common app/file locations across ALL drives
     (Program Files, AppData, Desktop, Downloads, Documents, LDPlayer, etc.).
  3. Optional full-drive walk (thorough but slow) when deep=True.

This is what lets the agent, mid-task, locate a program/file it needs — then
open it, or (if missing) decide to download+install it from the web.
"""

from __future__ import annotations

import os
from typing import Annotated

from langchain_core.tools import tool

# Folders worth scanning directly (index-independent). Populated per-drive.
_COMMON_SUBDIRS = [
    "Program Files", "Program Files (x86)",
    r"Users\{user}\AppData\Local", r"Users\{user}\AppData\Local\Programs",
    r"Users\{user}\AppData\Roaming",
    r"Users\{user}\Desktop", r"Users\{user}\Downloads",
    r"Users\{user}\Documents", r"Users\{user}\Music", r"Users\{user}\Videos",
    r"Users\{user}\Pictures",
    # Start-Menu shortcuts (fast, catches almost every installed app by its .lnk)
    r"Users\{user}\AppData\Roaming\Microsoft\Windows\Start Menu\Programs",
    r"ProgramData\Microsoft\Windows\Start Menu\Programs",
    # Popular non-standard install roots users pick (emulators, portable tools).
    "LDPlayer", "LDPlayer9", "Program Files\\BlueStacks_nxt", "Nox",
    "Games", "Apps", "Tools", "Portable",
]

_SKIP_DIRS = {
    "$recycle.bin", "system volume information", "windows\\winsxs",
    "node_modules", ".git", "__pycache__", "$windows.~bt", "$windows.~ws",
}

_EXE_EXTS = {".exe", ".lnk", ".bat", ".cmd", ".com", ".msi"}


def _drive_roots() -> list[str]:
    roots = []
    for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        root = f"{letter}:\\"
        if os.path.isdir(root):
            roots.append(root)
    return roots or ["C:\\"]


def _index_search(name_like: str, limit: int) -> list[str]:
    """Query the Windows Search index (fast). Returns [] if unavailable."""
    try:
        import win32com.client
    except Exception:
        return []
    try:
        conn = win32com.client.Dispatch("ADODB.Connection")
        conn.Open('Provider=Search.CollatorDSO;Extended Properties="Application=Windows"')
        safe = name_like.replace("'", "''")
        sql = (
            "SELECT TOP %d System.ItemPathDisplay FROM SystemIndex "
            "WHERE System.FileName LIKE '%%%s%%'" % (limit, safe)
        )
        rs = conn.Execute(sql)[0]
        out = []
        while not rs.EOF and len(out) < limit:
            val = rs.Fields.Item("System.ItemPathDisplay").Value
            if val:
                out.append(str(val))
            rs.MoveNext()
        conn.Close()
        return out
    except Exception:
        return []


def _direct_scan(name_lower: str, exts: set[str] | None, limit: int,
                 deep: bool) -> list[str]:
    """Scan the filesystem for files whose name contains `name_lower`.

    deep=False → only the common app/file locations (fast).
    deep=True  → walk entire drives (thorough, slower).
    """
    user = os.environ.get("USERNAME", "")
    scan_roots: list[str] = []
    if deep:
        scan_roots = _drive_roots()
    else:
        for drive in _drive_roots():
            for sub in _COMMON_SUBDIRS:
                p = os.path.join(drive, sub.format(user=user))
                if os.path.isdir(p):
                    scan_roots.append(p)
        # de-dup while preserving order
        seen: set[str] = set()
        scan_roots = [r for r in scan_roots if not (r.lower() in seen or seen.add(r.lower()))]

    found: list[str] = []
    for root in scan_roots:
        for dirpath, dirnames, filenames in os.walk(root):
            low_dir = dirpath.lower()
            if any(skip in low_dir for skip in _SKIP_DIRS):
                dirnames[:] = []
                continue
            for fn in filenames:
                fl = fn.lower()
                if name_lower in fl:
                    if exts is None or os.path.splitext(fl)[1] in exts:
                        found.append(os.path.join(dirpath, fn))
                        if len(found) >= limit:
                            return found
    return found


@tool
def find_on_computer(
    name: Annotated[str, "File or app name (or part of it) to find, e.g. 'chrome', 'report', 'LDPlayer'."],
    kind: Annotated[str, "'app' = executables only (.exe/.lnk/.bat...), 'file' = any file, 'all'. Default 'all'."] = "all",
    deep: Annotated[bool, "False = fast (index + common locations). True = full scan of every drive (slow, thorough)."] = False,
    max_results: Annotated[int, "Max matches to return. Default 40."] = 40,
) -> str:
    """Find ANY file or application ANYWHERE on the computer (all drives).

    Strategy: the fast Windows index + a direct scan of common app/file
    locations first. If nothing is found (or deep=True), it walks entire drives.
    Use this BEFORE deciding a program/file is missing — only when this returns
    nothing should you fall back to downloading it from the web.
    """
    try:
        name = (name or "").strip()
        if not name:
            return "❌ find_on_computer: يجب تحديد اسم للبحث."
        name_lower = name.lower()
        exts = _EXE_EXTS if kind == "app" else None

        results: list[str] = []
        seen: set[str] = set()

        def _add(paths):
            for p in paths:
                key = p.lower()
                if key in seen:
                    continue
                if exts is not None and os.path.splitext(key)[1] not in exts:
                    continue
                seen.add(key)
                results.append(p)

        # Layer 1: Windows index (instant).
        _add(_index_search(name, max_results))

        # Layer 2: direct scan of common locations (fast) if not enough yet.
        if len(results) < max_results:
            _add(_direct_scan(name_lower, exts, max_results, deep=False))

        # Layer 3: full-drive walk if still nothing OR the caller asked for deep.
        if (not results or deep) and len(results) < max_results:
            _add(_direct_scan(name_lower, exts, max_results, deep=True))

        results = results[:max_results]
        if not results:
            return (f"🔍 لم يُعثر على '{name}' على الحاسوب"
                    f"{' (بحث شامل لكل الأقراص)' if deep else ' (بحث سريع — جرّب deep=True لمسح كامل)'}. "
                    "إن كان تطبيقاً، ابحث عنه في الويب وحمّله.")
        header = f"✅ {len(results)} نتيجة لـ '{name}':"
        return header + "\n" + "\n".join(f"  • {p}" for p in results)
    except Exception as exc:
        return f"❌ find_on_computer: {exc}"


if __name__ == "__main__":  # smoke test
    print(find_on_computer.invoke({"name": "python", "kind": "app", "max_results": 5}))
