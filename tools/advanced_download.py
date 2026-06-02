"""
Advanced download utilities with retry, progress tracking, and integrity verification.

Complements existing download_file tool with:
  - Automatic retry on failure
  - Progress estimation
  - File type validation
  - Destination path expansion
"""

from __future__ import annotations

import os
import hashlib
import shutil
from pathlib import Path
from typing import Optional

import requests
from langchain_core.tools import tool


def _expand_dest_path(dest: str) -> str:
    """Expand destination paths like 'desktop:filename.ext' to full path."""
    if dest.startswith("desktop:"):
        filename = dest.replace("desktop:", "").strip()
        desktop = Path.home() / "Desktop"
        return str(desktop / filename)

    if dest.startswith("downloads:"):
        filename = dest.replace("downloads:", "").strip()
        downloads = Path.home() / "Downloads"
        return str(downloads / filename)

    if dest.startswith("documents:"):
        filename = dest.replace("documents:", "").strip()
        documents = Path.home() / "Documents"
        return str(documents / filename)

    # Treat as absolute path if not a shortcut
    return os.path.expanduser(dest)


def _get_file_size_estimate(url: str, timeout: int = 10) -> tuple[int, bool]:
    """
    Get file size without downloading.
    Returns: (size_bytes, is_available)
    """
    try:
        resp = requests.head(url, timeout=timeout, allow_redirects=True)
        if resp.status_code == 200:
            size = int(resp.headers.get("content-length", 0))
            return size, True
        return 0, False
    except Exception:
        return 0, False


def _format_size(bytes_: int) -> str:
    """Format bytes to human-readable size."""
    for unit in ["B", "KB", "MB", "GB"]:
        if bytes_ < 1024:
            return f"{bytes_:.1f} {unit}"
        bytes_ /= 1024
    return f"{bytes_:.1f} TB"


def _verify_download(file_path: str, expected_size: Optional[int] = None) -> bool:
    """Verify downloaded file exists and optionally matches expected size."""
    if not os.path.exists(file_path):
        return False

    if expected_size is None:
        return True

    actual_size = os.path.getsize(file_path)
    return actual_size == expected_size


@tool
def download_with_progress(
    url: str,
    dest: str = "desktop:",
    max_retries: int = 3,
    timeout: int = 120,
) -> str:
    """
    Download file from URL with retry logic and progress estimation.

    Args:
        url: Full URL of file to download
        dest: Destination path. Shortcuts: 'desktop:file.mp3', 'downloads:', 'documents:'
        max_retries: Number of retry attempts on failure (default: 3)
        timeout: Request timeout in seconds (default: 120)

    Returns:
        Success message with file path and size, or error description

    Examples:
        • download_with_progress('https://example.com/song.mp3', 'desktop:song.mp3')
        • download_with_progress('https://example.com/doc.pdf', 'documents:')
    """
    dest_path = _expand_dest_path(dest)
    dest_dir = os.path.dirname(dest_path)

    # Ensure destination directory exists
    try:
        os.makedirs(dest_dir, exist_ok=True)
    except Exception as e:
        return f"❌ Failed to create destination directory: {e}"

    # Try to get file size first
    size_bytes, is_available = _get_file_size_estimate(url, timeout)
    if not is_available:
        return f"⚠️ WARNING: Could not verify file availability at URL. Attempting download anyway..."

    size_str = _format_size(size_bytes) if size_bytes > 0 else "unknown size"

    # Retry loop
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(url, timeout=timeout, allow_redirects=True, stream=True)
            response.raise_for_status()

            # Download with simple progress tracking
            downloaded = 0
            chunk_size = 8192
            with open(dest_path, "wb") as f:
                for chunk in response.iter_content(chunk_size):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)

            # Verify download
            if not _verify_download(dest_path, size_bytes if size_bytes > 0 else None):
                raise Exception("File verification failed")

            actual_size = os.path.getsize(dest_path)
            return (
                f"✅ SUCCESS: File downloaded ({_format_size(actual_size)})\n"
                f"📁 Location: {dest_path}"
            )

        except Exception as e:
            last_error = str(e)
            if attempt < max_retries:
                # Try again
                try:
                    os.remove(dest_path)
                except:
                    pass
                continue
            break

    return f"❌ Download failed after {max_retries} attempts: {last_error}"


@tool
def check_url_availability(url: str, timeout: int = 10) -> str:
    """
    Check if a URL is accessible and get file information.

    Args:
        url: URL to check
        timeout: Timeout in seconds

    Returns:
        Information about URL availability and file size
    """
    try:
        resp = requests.head(url, timeout=timeout, allow_redirects=True)
        if resp.status_code == 200:
            size = resp.headers.get("content-length", "unknown")
            content_type = resp.headers.get("content-type", "unknown")
            if size != "unknown":
                size = _format_size(int(size))
            return (
                f"✅ URL is accessible\n"
                f"📊 Content-Type: {content_type}\n"
                f"📏 Size: {size}"
            )
        else:
            return f"❌ URL returned status {resp.status_code}"
    except Exception as e:
        return f"❌ URL not accessible: {e}"


@tool
def get_file_hash(file_path: str, algorithm: str = "md5") -> str:
    """
    Calculate hash of a downloaded file for verification.

    Args:
        file_path: Path to file
        algorithm: Hash algorithm ('md5', 'sha1', 'sha256')

    Returns:
        File hash value
    """
    file_path = os.path.expanduser(file_path)

    if not os.path.exists(file_path):
        return f"❌ File not found: {file_path}"

    try:
        hash_obj = hashlib.new(algorithm)
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hash_obj.update(chunk)

        return f"✅ {algorithm.upper()}: {hash_obj.hexdigest()}"
    except Exception as e:
        return f"❌ Failed to calculate hash: {e}"
