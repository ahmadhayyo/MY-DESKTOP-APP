"""
Media tools — download audio/video from YouTube and other sites via yt-dlp.

For "download song <title>" requests, this is FAR more reliable than scraping
Google + sketchy mp3 sites. yt-dlp handles 1000+ sites, finds the best audio
stream, and saves it directly.

Tools exposed:
  • download_audio_by_search — search YouTube for a song, download best audio
  • download_audio_from_url   — download audio from a known URL (YouTube etc.)
  • download_video_from_url   — download video from a URL
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Annotated

from langchain_core.tools import tool

from config import DESKTOP_DIR, DOWNLOADS_DIR


def _ffmpeg_available() -> bool:
    """Check whether ffmpeg is on PATH (needed for mp3 conversion)."""
    return shutil.which("ffmpeg") is not None


def _resolve_dest(dest: str) -> Path:
    """
    Resolve a destination string:
      • 'desktop:'   → Desktop folder
      • 'downloads:' → Downloads folder
      • absolute path → that path
      • bare filename → Desktop / filename
    """
    if not dest or dest.lower() in ("desktop", "desktop:", "desktop:/"):
        return DESKTOP_DIR
    if dest.lower() in ("downloads", "downloads:", "downloads:/"):
        return DOWNLOADS_DIR
    if dest.lower().startswith("desktop:"):
        return DESKTOP_DIR / dest.split(":", 1)[1].lstrip("/\\")
    if dest.lower().startswith("downloads:"):
        return DOWNLOADS_DIR / dest.split(":", 1)[1].lstrip("/\\")
    p = Path(dest)
    if p.is_absolute():
        return p
    return DESKTOP_DIR / dest


def _yt_dlp_audio_opts(out_path: Path, prefer_mp3: bool) -> dict:
    """Build yt-dlp options for audio-only download."""
    out_template = str(out_path.with_suffix(".%(ext)s"))
    opts = {
        "outtmpl": out_template,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "format": "bestaudio/best",
        "ignoreerrors": False,
        "retries": 3,
        "fragment_retries": 3,
    }
    # mp3 conversion requires ffmpeg
    if prefer_mp3 and _ffmpeg_available():
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]
    return opts


@tool
def download_audio_by_search(
    query: Annotated[str, "What to search for, e.g. 'بعيش تامر حسني' or 'Hotel California Eagles'"],
    dest: Annotated[str, "Where to save: 'desktop:', 'downloads:', or absolute path. Defaults to Desktop."] = "desktop:",
    filename: Annotated[str, "Optional custom filename (without extension). Defaults to YouTube title."] = "",
) -> str:
    """
    Search YouTube for the given query and download the best audio of the top
    result. Saves as MP3 if ffmpeg is installed, otherwise keeps the native
    format (m4a/webm — most players handle these fine).

    Use this for ANY "download song X" or "download audio Y" request. It is
    much more reliable than scraping Google and clicking sketchy mp3 sites.
    """
    try:
        import yt_dlp
    except ImportError:
        return "[ERROR] yt-dlp is not installed. Run: pip install yt-dlp"

    target_dir = _resolve_dest(dest)
    target_dir.mkdir(parents=True, exist_ok=True)

    # If user gave a filename, sanitize and use it; else use video title
    safe_name = "".join(c for c in filename if c not in '<>:"/\\|?*').strip() if filename else ""
    base_path = target_dir / (safe_name or "%(title)s")

    opts = _yt_dlp_audio_opts(base_path, prefer_mp3=True)

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            # ytsearch1: picks the top YouTube result for the query
            info = ydl.extract_info(f"ytsearch1:{query}", download=True)
            if info and "entries" in info and info["entries"]:
                info = info["entries"][0]
            title = info.get("title", "unknown") if info else "unknown"
            duration = info.get("duration", 0) if info else 0
    except Exception as exc:
        return f"[ERROR] yt-dlp failed: {type(exc).__name__}: {exc}"

    # Find what was actually saved (extension may vary)
    if safe_name:
        candidates = list(target_dir.glob(f"{safe_name}.*"))
    else:
        # Match by title (sanitized similarly to how yt-dlp does it)
        candidates = sorted(
            target_dir.glob("*"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:5]

    saved = [c for c in candidates if c.suffix.lower() in (".mp3", ".m4a", ".webm", ".opus", ".aac", ".ogg")]
    if not saved:
        return f"[WARN] Downloaded but couldn't locate the output file in {target_dir}"

    final = saved[0]
    note = ""
    if not _ffmpeg_available() and final.suffix.lower() != ".mp3":
        note = (
            f"\n  Note: ffmpeg is not installed, so the file was kept as "
            f"{final.suffix} instead of being converted to mp3. Most media "
            f"players (VLC, Windows Media Player, browsers) play it fine."
        )

    return (
        f"[OK] Downloaded '{title}' ({duration//60}:{duration%60:02d})\n"
        f"  File: {final}\n"
        f"  Size: {final.stat().st_size / 1024 / 1024:.1f} MB{note}"
    )


@tool
def download_audio_from_url(
    url: Annotated[str, "Direct URL of a YouTube / SoundCloud / other supported video"],
    dest: Annotated[str, "Where to save: 'desktop:', 'downloads:', or absolute path"] = "desktop:",
    filename: Annotated[str, "Optional custom filename (without extension)"] = "",
) -> str:
    """Download audio from a known URL. Use this when the user gives you a link."""
    try:
        import yt_dlp
    except ImportError:
        return "[ERROR] yt-dlp is not installed. Run: pip install yt-dlp"

    target_dir = _resolve_dest(dest)
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(c for c in filename if c not in '<>:"/\\|?*').strip() if filename else ""
    base_path = target_dir / (safe_name or "%(title)s")

    opts = _yt_dlp_audio_opts(base_path, prefer_mp3=True)

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "unknown") if info else "unknown"
    except Exception as exc:
        return f"[ERROR] yt-dlp failed: {type(exc).__name__}: {exc}"

    candidates = sorted(
        target_dir.glob(f"{safe_name}.*" if safe_name else "*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    saved = [c for c in candidates if c.suffix.lower() in (".mp3", ".m4a", ".webm", ".opus", ".aac", ".ogg")]
    if not saved:
        return f"[WARN] Downloaded '{title}' but couldn't locate the output file in {target_dir}"

    final = saved[0]
    return f"[OK] Downloaded '{title}' to {final} ({final.stat().st_size / 1024 / 1024:.1f} MB)"


@tool
def download_video_from_url(
    url: Annotated[str, "Direct URL of a YouTube / Vimeo / other supported video"],
    dest: Annotated[str, "Where to save: 'desktop:', 'downloads:', or absolute path"] = "desktop:",
    filename: Annotated[str, "Optional custom filename (without extension)"] = "",
    quality: Annotated[str, "Video quality: 'best', '1080', '720', '480'. Default 'best'."] = "best",
) -> str:
    """Download a video (with audio) from a URL."""
    try:
        import yt_dlp
    except ImportError:
        return "[ERROR] yt-dlp is not installed. Run: pip install yt-dlp"

    target_dir = _resolve_dest(dest)
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(c for c in filename if c not in '<>:"/\\|?*').strip() if filename else ""
    base_path = target_dir / (safe_name or "%(title)s")

    # Format selector based on requested quality
    if quality == "best":
        fmt = "best"
    else:
        fmt = f"best[height<={quality}]/best"

    opts = {
        "outtmpl": str(base_path.with_suffix(".%(ext)s")),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "format": fmt,
        "retries": 3,
        "fragment_retries": 3,
    }

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "unknown") if info else "unknown"
            duration = info.get("duration", 0) if info else 0
    except Exception as exc:
        return f"[ERROR] yt-dlp failed: {type(exc).__name__}: {exc}"

    candidates = sorted(
        target_dir.glob(f"{safe_name}.*" if safe_name else "*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    saved = [c for c in candidates if c.suffix.lower() in (".mp4", ".mkv", ".webm", ".avi", ".mov")]
    if not saved:
        return f"[WARN] Downloaded '{title}' but couldn't locate the output file in {target_dir}"

    final = saved[0]
    return (
        f"[OK] Downloaded video '{title}' ({duration//60}:{duration%60:02d})\n"
        f"  File: {final}\n"
        f"  Size: {final.stat().st_size / 1024 / 1024:.1f} MB"
    )


__all__ = [
    "download_audio_by_search",
    "download_audio_from_url",
    "download_video_from_url",
]
