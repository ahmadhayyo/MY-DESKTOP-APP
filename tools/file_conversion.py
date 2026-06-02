"""
File conversion utilities for converting between different formats.

Supports conversions:
  - Audio: mp3, wav, m4a, flac, ogg
  - Video: mp4, avi, mkv, webm
  - Documents: pdf, docx, xlsx, pptx
  - Images: jpg, png, gif, webp, bmp
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional

from langchain_core.tools import tool


def _find_converter_tool(target_format: str) -> Optional[str]:
    """Find appropriate converter tool for target format."""
    # Map formats to tools that can convert to them
    converters = {
        # Audio converters
        "mp3": ["ffmpeg", "sox"],
        "wav": ["ffmpeg", "sox"],
        "m4a": ["ffmpeg"],
        "flac": ["ffmpeg"],
        "ogg": ["ffmpeg"],
        # Video converters
        "mp4": ["ffmpeg"],
        "avi": ["ffmpeg"],
        "mkv": ["ffmpeg"],
        "webm": ["ffmpeg"],
        # Document converters
        "pdf": ["libreoffice", "convert"],
        "docx": ["pandoc"],
        "xlsx": ["libreoffice"],
        # Image converters
        "jpg": ["ffmpeg", "convert", "magick"],
        "png": ["ffmpeg", "convert", "magick"],
        "gif": ["ffmpeg", "convert", "magick"],
        "webp": ["convert", "magick"],
        "bmp": ["convert", "magick"],
    }
    tools = converters.get(target_format.lower(), [])
    for tool in tools:
        result = subprocess.run(["where" if os.name == "nt" else "which", tool],
                              capture_output=True)
        if result.returncode == 0:
            return tool
    return None


def _get_file_info(file_path: str) -> dict:
    """Get information about a file using ffprobe if available."""
    file_path = os.path.expanduser(file_path)
    if not os.path.exists(file_path):
        return {"exists": False, "error": f"File not found: {file_path}"}

    size = os.path.getsize(file_path)
    ext = Path(file_path).suffix.lstrip(".")

    return {
        "exists": True,
        "path": file_path,
        "size_bytes": size,
        "size_mb": round(size / 1024 / 1024, 2),
        "extension": ext,
    }


@tool
def convert_file(
    src: str,
    target_format: str,
    dest: Optional[str] = None,
    bitrate: str = "192k",
    quality: int = 85,
) -> str:
    """
    Convert a file to a different format.

    Args:
        src: Source file path (e.g., '/path/to/song.wav')
        target_format: Target format without dot (e.g., 'mp3', 'pdf', 'png')
        dest: Destination path (default: same dir, new extension)
        bitrate: Audio bitrate (default: '192k', e.g., '128k', '320k')
        quality: Image/video quality 1-100 (default: 85)

    Returns:
        Conversion status and output file path

    Supported Formats:
        Audio:     mp3, wav, m4a, flac, ogg
        Video:     mp4, avi, mkv, webm
        Documents: pdf, docx, xlsx
        Images:    jpg, png, gif, webp, bmp

    Examples:
        • convert_file('/music/song.wav', 'mp3', bitrate='256k')
        • convert_file('/images/photo.png', 'jpg', quality=90)
        • convert_file('/docs/report.docx', 'pdf')
        • convert_file('/video.avi', 'mp4')

    Requirements:
        • Audio/Video: ffmpeg (ffmpeg.org)
        • Documents: LibreOffice or Pandoc
        • Images: ImageMagick or GraphicsMagick

    Workflow:
        1. Check source file exists
        2. Detect available converters
        3. Build conversion command
        4. Execute conversion
        5. Verify output file
        6. Return result with file size info
    """
    src = os.path.expanduser(src)
    target_format = target_format.lstrip(".").lower()

    # Check source file
    src_info = _get_file_info(src)
    if not src_info.get("exists"):
        return f"❌ {src_info.get('error')}"

    # Determine destination
    if dest is None:
        dest = str(Path(src).with_suffix(f".{target_format}"))
    else:
        dest = os.path.expanduser(dest)

    # Check for available converter
    converter = _find_converter_tool(target_format)
    if not converter:
        return (
            f"❌ No converter found for '{target_format}' format.\n"
            f"Install one of: ffmpeg (audio/video), LibreOffice (docs), "
            f"ImageMagick (images)"
        )

    # Build command based on converter
    if converter == "ffmpeg":
        if target_format in ["mp3", "wav", "m4a", "flac", "ogg"]:
            cmd = [
                "ffmpeg", "-i", src,
                "-b:a", bitrate,
                "-y", dest
            ]
        else:  # Video/images
            cmd = [
                "ffmpeg", "-i", src,
                "-q:v", str(101 - quality),
                "-y", dest
            ]

    elif converter == "libreoffice":
        cmd = [
            "libreoffice", "--headless", "--convert-to",
            target_format, "--outdir", os.path.dirname(dest), src
        ]

    elif converter == "pandoc":
        cmd = ["pandoc", "-i", src, "-o", dest]

    elif converter in ["convert", "magick"]:
        cmd = [converter, src, "-quality", str(quality), dest]

    else:
        return f"❌ Unknown converter: {converter}"

    # Execute conversion
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

        if result.returncode != 0:
            error_msg = result.stderr or result.stdout or "Unknown error"
            return f"❌ Conversion failed: {error_msg}"

        # Verify output
        if not os.path.exists(dest):
            return "❌ Conversion completed but output file not found"

        dest_size = os.path.getsize(dest)
        dest_size_mb = round(dest_size / 1024 / 1024, 2)

        return (
            f"✅ Conversion successful!\n"
            f"📁 Source: {src} ({src_info.get('size_mb')} MB)\n"
            f"📁 Output: {dest} ({dest_size_mb} MB)\n"
            f"⚙️ Converter: {converter}"
        )

    except subprocess.TimeoutExpired:
        return "❌ Conversion timed out (> 10 minutes)"
    except Exception as e:
        return f"❌ Conversion error: {e}"


@tool
def get_supported_formats() -> str:
    """
    Get list of supported conversion formats and required tools.

    Returns:
        Formatted list of supported formats and requirements
    """
    return """
📋 SUPPORTED CONVERSION FORMATS

🎵 AUDIO (requires: ffmpeg)
  Source → Target: wav, mp3, m4a, flac, ogg
  Bitrate options: 128k, 192k, 256k, 320k (higher = better quality, larger file)

🎬 VIDEO (requires: ffmpeg)
  Source → Target: mp4, avi, mkv, webm
  Quality options: 1-100 (85 is good default)

📄 DOCUMENTS (requires: LibreOffice or Pandoc)
  Source → Target: pdf, docx, xlsx

🖼️ IMAGES (requires: ImageMagick/GraphicsMagick)
  Source → Target: jpg, png, gif, webp, bmp
  Quality options: 1-100 (85-95 recommended for photos)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚙️ INSTALLATION

Windows (using Chocolatey):
  • choco install ffmpeg
  • choco install libreoffice
  • choco install imagemagick

macOS (using Homebrew):
  • brew install ffmpeg
  • brew install libreoffice
  • brew install imagemagick

Linux (Ubuntu/Debian):
  • sudo apt install ffmpeg libreoffice imagemagick
  • sudo apt install pandoc
"""


@tool
def check_conversion_support(
    source_format: str,
    target_format: str,
) -> str:
    """
    Check if a specific format conversion is supported.

    Args:
        source_format: Source file format (e.g., 'wav', 'png')
        target_format: Target file format (e.g., 'mp3', 'jpg')

    Returns:
        Support status and required tools
    """
    source_format = source_format.lstrip(".").lower()
    target_format = target_format.lstrip(".").lower()

    # Define conversion support
    conversions = {
        # From WAV
        "wav": ["mp3", "m4a", "flac", "ogg"],
        # From MP3
        "mp3": ["wav", "m4a", "flac", "ogg"],
        # From PNG
        "png": ["jpg", "gif", "webp", "bmp"],
        # From JPG
        "jpg": ["png", "gif", "webp", "bmp"],
        # From DOCX
        "docx": ["pdf", "html"],
        # From PDF
        "pdf": ["docx", "txt"],
    }

    if source_format not in conversions:
        return f"❓ Source format '{source_format}' not recognized"

    if target_format in conversions.get(source_format, []):
        converter = _find_converter_tool(target_format)
        if converter:
            return f"✅ Conversion supported!\n   {source_format} → {target_format}\n   Using: {converter}"
        else:
            return f"⚠️ Conversion possible but required tool not found.\n   Install: ffmpeg, LibreOffice, or ImageMagick"
    else:
        return f"❌ Conversion not supported: {source_format} → {target_format}"
