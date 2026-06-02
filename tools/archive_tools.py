"""
Archive & file management tools: zip, unzip, delete.

Provides the agent with the ability to compress/decompress files
and safely delete files and folders.
"""

from __future__ import annotations

import os
import shutil
import zipfile
from pathlib import Path
from typing import Annotated

from langchain_core.tools import tool

from config import DESKTOP_DIR


def _resolve_path(p: str) -> Path:
    """Expand ~, env vars, and resolve to absolute Path."""
    expanded = os.path.expandvars(os.path.expanduser(p))
    return Path(expanded).resolve()


@tool
def zip_files(
    paths: Annotated[str, "Comma-separated list of file/folder paths to compress."],
    output: Annotated[str, "Output ZIP file path. Default: first item name + .zip on Desktop."] = "",
) -> str:
    """Create a ZIP archive from one or more files/folders."""
    items = [p.strip() for p in paths.split(",") if p.strip()]
    if not items:
        return "[ERROR] No paths provided."

    resolved = []
    for p in items:
        r = _resolve_path(p)
        if not r.exists():
            return f"[ERROR] Not found: {r}"
        resolved.append(r)

    # Determine output path
    if not output:
        base_name = resolved[0].stem + ".zip"
        out_path = DESKTOP_DIR / base_name
    else:
        out_path = _resolve_path(output)
        if out_path.is_dir():
            out_path = out_path / (resolved[0].stem + ".zip")

    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        file_count = 0
        with zipfile.ZipFile(str(out_path), "w", zipfile.ZIP_DEFLATED) as zf:
            for item in resolved:
                if item.is_file():
                    zf.write(item, item.name)
                    file_count += 1
                elif item.is_dir():
                    for root, _dirs, files in os.walk(item):
                        for f in files:
                            full = Path(root) / f
                            arcname = str(full.relative_to(item.parent))
                            zf.write(full, arcname)
                            file_count += 1

        size = out_path.stat().st_size
        return f"[OK] Created {out_path} ({file_count} files, {size:,} bytes)"
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def unzip_file(
    path: Annotated[str, "Path to the ZIP file."],
    dest: Annotated[str, "Destination folder. Default: same folder as ZIP."] = "",
) -> str:
    """Extract a ZIP archive to a folder."""
    zip_path = _resolve_path(path)
    if not zip_path.exists():
        return f"[ERROR] File not found: {zip_path}"

    if not zipfile.is_zipfile(str(zip_path)):
        return f"[ERROR] Not a valid ZIP file: {zip_path}"

    if dest:
        dest_dir = _resolve_path(dest)
    else:
        dest_dir = zip_path.parent / zip_path.stem

    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(str(zip_path), "r") as zf:
            zf.extractall(str(dest_dir))
            file_list = zf.namelist()

        return (
            f"[OK] Extracted {len(file_list)} items to {dest_dir}\n"
            f"Contents: {', '.join(file_list[:10])}"
            + (f"... (+{len(file_list)-10} more)" if len(file_list) > 10 else "")
        )
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def delete_path(
    path: Annotated[str, "Path to file or folder to delete."],
    confirm: Annotated[bool, "Must be True to actually delete. Safety check."] = False,
) -> str:
    """Delete a file or folder. Set confirm=True to actually delete (safety measure)."""
    target = _resolve_path(path)
    if not target.exists():
        return f"[ERROR] Not found: {target}"

    if not confirm:
        if target.is_dir():
            # Count contents
            count = sum(1 for _ in target.rglob("*"))
            return (
                f"[CONFIRM REQUIRED] About to delete folder: {target}\n"
                f"Contains {count} items. Call again with confirm=True to proceed."
            )
        else:
            size = target.stat().st_size
            return (
                f"[CONFIRM REQUIRED] About to delete file: {target} ({size:,} bytes)\n"
                "Call again with confirm=True to proceed."
            )

    try:
        if target.is_dir():
            shutil.rmtree(target)
            return f"[OK] Deleted folder: {target}"
        else:
            target.unlink()
            return f"[OK] Deleted file: {target}"
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def get_file_size(
    path: Annotated[str, "Path to file or folder."],
) -> str:
    """Get the size of a file or total size of a folder."""
    target = _resolve_path(path)
    if not target.exists():
        return f"[ERROR] Not found: {target}"

    try:
        if target.is_file():
            size = target.stat().st_size
            return f"File: {target.name} — {_human_size(size)} ({size:,} bytes)"
        else:
            total = 0
            file_count = 0
            dir_count = 0
            for item in target.rglob("*"):
                if item.is_file():
                    total += item.stat().st_size
                    file_count += 1
                elif item.is_dir():
                    dir_count += 1
            return (
                f"Folder: {target.name}\n"
                f"  Total size: {_human_size(total)} ({total:,} bytes)\n"
                f"  Files: {file_count}, Folders: {dir_count}"
            )
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


def _human_size(size: int) -> str:
    """Convert bytes to human-readable size."""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
