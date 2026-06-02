"""
File-system tools: read, write, append, list, search, download.

All paths are resolved through `_resolve_path` which:
  - Expands ~ and environment variables
  - Converts to absolute Path
  - Refuses traversal outside the user's home unless explicitly absolute
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Annotated

import httpx
from langchain_core.tools import tool

from config import DESKTOP_DIR, DOWNLOADS_DIR

MAX_READ_BYTES = 200_000  # ~200KB per read tool call


def _resolve_path(p: str) -> Path:
    """Expand ~, env vars, and resolve to absolute Path."""
    expanded = os.path.expandvars(os.path.expanduser(p))
    return Path(expanded).resolve()


@tool
def read_file(
    path: Annotated[str, "Absolute or ~-relative path to the file."],
    encoding: Annotated[str, "Text encoding."] = "utf-8",
) -> str:
    """Read a text file (capped at 200KB). For binary, use download_file or PowerShell."""
    target = _resolve_path(path)
    if not target.exists():
        return f"[ERROR] File not found: {target}"
    if not target.is_file():
        return f"[ERROR] Not a file: {target}"
    try:
        size = target.stat().st_size
        if size > MAX_READ_BYTES:
            with target.open("r", encoding=encoding, errors="replace") as fh:
                head = fh.read(MAX_READ_BYTES)
            return (
                f"[FILE TRUNCATED — {size} bytes total, showing first {MAX_READ_BYTES}]\n"
                + head
            )
        return target.read_text(encoding=encoding, errors="replace")
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def write_file(
    path: Annotated[str, "Where to write."],
    content: Annotated[str, "Text content. Overwrites existing file."],
    encoding: Annotated[str, "Text encoding."] = "utf-8",
) -> str:
    """Create or overwrite a text file. Parent folders are created automatically."""
    target = _resolve_path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding=encoding)
        return f"[OK] Wrote {len(content)} chars to {target}"
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def append_file(
    path: Annotated[str, "File to append to (created if missing)."],
    content: Annotated[str, "Text to append."],
    encoding: Annotated[str, "Text encoding."] = "utf-8",
) -> str:
    """Append text to a file. Useful for logs, journals, accumulating output."""
    target = _resolve_path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding=encoding) as fh:
            fh.write(content)
        return f"[OK] Appended {len(content)} chars to {target}"
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def list_dir(
    path: Annotated[str, "Folder to list. Use '.' for current."] = ".",
    show_hidden: Annotated[bool, "Include dotfiles."] = False,
) -> str:
    """List a folder's contents with size and type."""
    target = _resolve_path(path)
    if not target.exists():
        return f"[ERROR] Not found: {target}"
    if not target.is_dir():
        return f"[ERROR] Not a directory: {target}"
    rows = []
    try:
        for entry in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            if not show_hidden and entry.name.startswith("."):
                continue
            kind = "DIR " if entry.is_dir() else "FILE"
            try:
                size = entry.stat().st_size if entry.is_file() else 0
            except OSError:
                size = -1
            rows.append(f"{kind}  {size:>12}  {entry.name}")
    except PermissionError as exc:
        return f"[ERROR] Permission denied: {exc}"
    return f"Listing of {target}:\n" + ("\n".join(rows) if rows else "(empty)")


@tool
def search_files(
    root: Annotated[str, "Folder to search under."],
    pattern: Annotated[str, "Glob pattern, e.g. '*.pdf' or '**/*.py'."],
    max_results: Annotated[int, "Cap on returned matches."] = 100,
) -> str:
    """Recursive glob search under a folder. Use '**/*.ext' for full subtree."""
    base = _resolve_path(root)
    if not base.exists():
        return f"[ERROR] Not found: {base}"
    matches = []
    try:
        for path in base.glob(pattern):
            matches.append(str(path))
            if len(matches) >= max_results:
                break
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"
    if not matches:
        return f"No matches for {pattern} under {base}"
    return f"{len(matches)} match(es):\n" + "\n".join(matches)


@tool
def move_file(
    src: Annotated[str, "Source path."],
    dst: Annotated[str, "Destination path."],
) -> str:
    """Move or rename a file/folder."""
    s = _resolve_path(src)
    d = _resolve_path(dst)
    try:
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(s), str(d))
        return f"[OK] Moved {s} -> {d}"
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def copy_file(
    src: Annotated[str, "Source path."],
    dst: Annotated[str, "Destination path."],
) -> str:
    """Copy a file (or recursively copy a folder)."""
    s = _resolve_path(src)
    d = _resolve_path(dst)
    try:
        d.parent.mkdir(parents=True, exist_ok=True)
        if s.is_dir():
            shutil.copytree(s, d, dirs_exist_ok=True)
        else:
            shutil.copy2(s, d)
        return f"[OK] Copied {s} -> {d}"
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def download_file(
    url: Annotated[str, "Direct URL to a file (PDF, ZIP, image, etc.)."],
    dest: Annotated[
        str,
        "Destination path. Defaults to Desktop. Use '~/Downloads/foo.zip' or 'desktop:foo.zip'.",
    ] = "desktop:",
) -> str:
    """
    Download a file from a URL to disk.

    Examples:
      dest='desktop:report.pdf'         → ~/Desktop/report.pdf
      dest='~/Downloads/foo.zip'        → user's Downloads folder
      dest='C:/temp/data.csv'           → absolute path
    """
    # Resolve destination
    if dest.startswith("desktop:"):
        name = dest.removeprefix("desktop:") or url.rsplit("/", 1)[-1] or "download.bin"
        target = DESKTOP_DIR / name
    elif dest.startswith("downloads:"):
        name = dest.removeprefix("downloads:") or url.rsplit("/", 1)[-1] or "download.bin"
        target = DOWNLOADS_DIR / name
    else:
        target = _resolve_path(dest)
        if target.is_dir() or str(dest).endswith(("/", "\\")):
            target = target / (url.rsplit("/", 1)[-1] or "download.bin")

    target.parent.mkdir(parents=True, exist_ok=True)

    try:
        with httpx.Client(follow_redirects=True, timeout=60.0) as client:
            with client.stream("GET", url) as resp:
                resp.raise_for_status()
                total = 0
                with target.open("wb") as fh:
                    for chunk in resp.iter_bytes(chunk_size=64 * 1024):
                        fh.write(chunk)
                        total += len(chunk)
        return f"[OK] Downloaded {total} bytes -> {target}"
    except httpx.HTTPStatusError as exc:
        return f"[ERROR] HTTP {exc.response.status_code} for {url}"
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def make_dir(path: Annotated[str, "Folder to create."]) -> str:
    """Create a folder (and any missing parents)."""
    target = _resolve_path(path)
    try:
        target.mkdir(parents=True, exist_ok=True)
        return f"[OK] Created {target}"
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"
