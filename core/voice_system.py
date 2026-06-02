"""
Voice system for HAYO — real-time speech-in/speech-out conversation.

Architecture:
  • STT (Speech-to-Text): Groq Whisper API
      - whisper-large-v3 model, extremely fast on Groq infrastructure
      - Handles Arabic + English perfectly
      - Free tier is generous

  • TTS (Text-to-Speech): Microsoft Edge TTS
      - Free, no API key needed
      - Natural-sounding neural voices
      - 14+ Arabic dialects supported
      - Default: ar-EG-SalmaNeural (warm, natural Egyptian Arabic)

Audio format note:
  Chainlit's browser frontend uses AudioWorklet, which delivers RAW PCM bytes
  (16-bit signed little-endian, mono, 24000 Hz) without any container header.
  Whisper/Groq need a real media file (wav, mp3, etc.), so we wrap PCM in a
  minimal WAV header before sending. See pcm_to_wav() below.

Designed for ChatGPT-style voice mode: user speaks → agent listens → agent
speaks back with emotion + executes any tools the user requested.
"""

from __future__ import annotations

import asyncio
import io
import os
import re
import struct
import tempfile
import wave
from pathlib import Path
from typing import AsyncIterator

import edge_tts


# ── Voice catalogue ──────────────────────────────────────────────────────────
# Curated list of natural-sounding Arabic + English voices.
# Egyptian Arabic is the default — most widely understood across the region.
VOICES = {
    # Arabic
    "salma":   "ar-EG-SalmaNeural",      # Female — Egyptian, warm (DEFAULT)
    "shakir":  "ar-EG-ShakirNeural",     # Male   — Egyptian
    "zariyah": "ar-SA-ZariyahNeural",    # Female — Saudi, MSA
    "hamed":   "ar-SA-HamedNeural",      # Male   — Saudi, MSA
    "laila":   "ar-LB-LaylaNeural",      # Female — Lebanese
    "rami":    "ar-LB-RamiNeural",       # Male   — Lebanese

    # English
    "aria":    "en-US-AriaNeural",       # Female — US, friendly
    "guy":     "en-US-GuyNeural",        # Male   — US, professional
    "jenny":   "en-US-JennyNeural",      # Female — US, conversational
}

DEFAULT_VOICE_AR = "ar-EG-SalmaNeural"
DEFAULT_VOICE_EN = "en-US-AriaNeural"


def _is_arabic(text: str) -> bool:
    """Heuristic: any Arabic character in the text → use Arabic voice."""
    return bool(re.search(r"[؀-ۿ]", text))


def pick_voice(text: str, preferred: str | None = None) -> str:
    """Pick a voice that matches the language of the text."""
    if preferred:
        # Allow shortcuts like "salma" or full names like "ar-EG-SalmaNeural"
        return VOICES.get(preferred.lower(), preferred)
    return DEFAULT_VOICE_AR if _is_arabic(text) else DEFAULT_VOICE_EN


# ── Text cleaning for natural speech ─────────────────────────────────────────
_MARKDOWN_PATTERNS = [
    (re.compile(r"```[\s\S]*?```"), ""),          # fenced code blocks
    (re.compile(r"`([^`]+)`"), r"\1"),            # inline code → plain
    (re.compile(r"\*\*([^*]+)\*\*"), r"\1"),      # bold
    (re.compile(r"\*([^*]+)\*"), r"\1"),          # italic
    (re.compile(r"#{1,6}\s*"), ""),               # headings
    (re.compile(r"!\[[^\]]*\]\([^)]+\)"), ""),    # images
    (re.compile(r"\[([^\]]+)\]\([^)]+\)"), r"\1"),# links → just the text
    (re.compile(r"^\s*[-*+]\s+", re.MULTILINE), ""), # list bullets
    (re.compile(r"^\s*>\s+", re.MULTILINE), ""),  # blockquotes
    (re.compile(r"━+|═+|─+|—+"), " "),            # box-drawing
    (re.compile(r"[🔧🤖🌐📁🖱️🔍⚡🧠📋🔊⛔✅❌⚠️🔁🔄🚀💡📸▶️⏸️🔒🚫📎📄📊🎯🟦🟠🟢🔵🟣]"), ""), # emoji
    (re.compile(r"\s+"), " "),                    # collapse whitespace
]


def clean_for_speech(text: str, max_chars: int = 2000) -> str:
    """
    Strip markdown / code / emoji so TTS reads natural prose,
    not bullet markers and asterisks.
    """
    out = text
    for pattern, replacement in _MARKDOWN_PATTERNS:
        out = pattern.sub(replacement, out)
    out = out.strip()
    if len(out) > max_chars:
        out = out[:max_chars].rsplit(" ", 1)[0] + "..."
    return out


# ── Text-to-Speech (Edge TTS) ────────────────────────────────────────────────
async def text_to_speech(
    text: str,
    voice: str | None = None,
    rate: str = "+0%",
    pitch: str = "+0Hz",
) -> bytes:
    """
    Convert text to natural-sounding speech.

    Args:
      text:  what to say
      voice: short name ('salma', 'aria') or full ('ar-EG-SalmaNeural').
             If None, autodetected from text language.
      rate:  speed adjustment, e.g. "-10%" or "+15%"
      pitch: pitch adjustment, e.g. "-5Hz" or "+3Hz"

    Returns:
      MP3 audio bytes ready to send to the user.
    """
    clean = clean_for_speech(text)
    if not clean:
        return b""

    voice_name = pick_voice(clean, voice)
    communicate = edge_tts.Communicate(clean, voice_name, rate=rate, pitch=pitch)

    buf = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])
    return buf.getvalue()


async def text_to_speech_file(
    text: str,
    out_path: str | Path,
    voice: str | None = None,
    rate: str = "+0%",
    pitch: str = "+0Hz",
) -> Path:
    """Same as text_to_speech but writes directly to a file path."""
    audio = await text_to_speech(text, voice=voice, rate=rate, pitch=pitch)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(audio)
    return out_path


# ── Audio format helpers ─────────────────────────────────────────────────────
def pcm_to_wav(pcm_bytes: bytes, sample_rate: int = 24000, channels: int = 1, sample_width: int = 2) -> bytes:
    """
    Wrap raw PCM bytes in a minimal WAV container so Whisper/Groq can decode it.

    Defaults match what Chainlit's AudioWorklet sends:
      - 16-bit signed little-endian (sample_width = 2)
      - mono (channels = 1)
      - 24000 Hz (matches .chainlit/config.toml [features.audio] sample_rate)

    A WAV header is 44 bytes — we use the stdlib `wave` module so we don't
    have to hand-roll the RIFF format and risk getting it wrong.
    """
    if not pcm_bytes:
        return b""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(sample_width)
        w.setframerate(sample_rate)
        w.writeframes(pcm_bytes)
    return buf.getvalue()


def looks_like_raw_pcm(audio: bytes, mime: str = "") -> bool:
    """
    Heuristic: does this look like raw PCM (no container) rather than a real
    media file? We need to wrap raw PCM in WAV before sending to Whisper.

    Real audio files start with magic bytes:
      WAV   → b"RIFF"
      MP3   → b"ID3" or b"\\xff\\xfb" / b"\\xff\\xf3" / b"\\xff\\xf2"
      WebM  → b"\\x1a\\x45\\xdf\\xa3"
      OGG   → b"OggS"
      M4A   → b"....ftyp"  (bytes 4-8)
      FLAC  → b"fLaC"

    If none of those match, treat it as raw PCM.
    """
    if not audio or len(audio) < 8:
        return True
    head = audio[:8]
    # WAV / RIFF
    if head.startswith(b"RIFF"):
        return False
    # MP3
    if head.startswith(b"ID3") or head[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return False
    # WebM / Matroska EBML
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return False
    # OGG
    if head.startswith(b"OggS"):
        return False
    # M4A / MP4 (ftyp at offset 4)
    if audio[4:8] == b"ftyp":
        return False
    # FLAC
    if head.startswith(b"fLaC"):
        return False
    # Looks like raw PCM
    return True


# ── Speech-to-Text (Groq → OpenAI Whisper fallback) ──────────────────────────
# Tries providers in this order, using the first one that has a valid key:
#   1. Groq whisper-large-v3   (fastest, free tier, ~10x faster than OpenAI)
#   2. OpenAI whisper-1        (very reliable, paid)
# If neither works, raises a clear error so the UI can ask for typed input.

_STT_PROVIDERS_TRIED: list[str] = []


def _try_groq_transcribe(audio_bytes: bytes, filename: str) -> str | None:
    """Return transcript or None if provider unavailable / failed."""
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from groq import Groq
    except ImportError:
        return None

    try:
        client = Groq(api_key=api_key)
        result = client.audio.transcriptions.create(
            file=(filename, audio_bytes),
            model="whisper-large-v3",
            response_format="text",
            temperature=0.0,
        )
        return str(result).strip() if result else ""
    except Exception as exc:
        _STT_PROVIDERS_TRIED.append(f"groq: {type(exc).__name__}: {exc}")
        return None


def _try_openai_transcribe(audio_bytes: bytes, filename: str) -> str | None:
    """OpenAI Whisper fallback."""
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key or api_key.startswith("your_") or api_key == "sk-placeholder":
        return None
    try:
        from openai import OpenAI
    except ImportError:
        return None

    try:
        client = OpenAI(api_key=api_key)
        result = client.audio.transcriptions.create(
            file=(filename, audio_bytes),
            model="whisper-1",
            response_format="text",
            temperature=0.0,
        )
        return str(result).strip() if result else ""
    except Exception as exc:
        _STT_PROVIDERS_TRIED.append(f"openai: {type(exc).__name__}: {exc}")
        return None


def transcribe_sync(
    audio_bytes: bytes,
    filename: str = "audio.wav",
    sample_rate: int = 24000,
) -> str:
    """
    Transcribe audio bytes to text using whichever Whisper provider is configured.

    Handles BOTH input shapes:
      - A real audio file (mp3, webm, wav, ogg, m4a, flac, ...)
      - Raw PCM bytes from Chainlit's AudioWorklet (16-bit LE mono, ~24kHz)

    If the bytes look like raw PCM (no recognised magic header), we wrap them
    in a WAV container before sending to Whisper. Without this, Groq returns
    'could not process file - is it a valid media file?'.

    Tries Groq first (free + fast), then OpenAI as fallback. Raises with a
    helpful error message if no provider works.
    """
    _STT_PROVIDERS_TRIED.clear()

    # If this is raw PCM (no container), wrap in WAV so Whisper can decode it
    if looks_like_raw_pcm(audio_bytes):
        audio_bytes = pcm_to_wav(audio_bytes, sample_rate=sample_rate)
        filename = "audio.wav"

    for fn in (_try_groq_transcribe, _try_openai_transcribe):
        result = fn(audio_bytes, filename)
        if result is not None:
            return result

    # No provider worked
    if _STT_PROVIDERS_TRIED:
        details = " | ".join(_STT_PROVIDERS_TRIED)
        raise RuntimeError(f"All STT providers failed: {details}")
    raise RuntimeError(
        "No speech-to-text provider configured. Add a valid GROQ_API_KEY "
        "(free at https://console.groq.com) or OPENAI_API_KEY in .env."
    )


async def transcribe(
    audio_bytes: bytes,
    filename: str = "audio.wav",
    sample_rate: int = 24000,
) -> str:
    """Async wrapper around transcribe_sync."""
    return await asyncio.to_thread(transcribe_sync, audio_bytes, filename, sample_rate)


def stt_available() -> bool:
    """Quick check: is any STT provider configured (key present, syntactically valid)?"""
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    if groq_key and not groq_key.startswith("your_"):
        return True
    if openai_key and not openai_key.startswith("your_") and openai_key != "sk-placeholder":
        return True
    return False


# ── High-level: full round trip ──────────────────────────────────────────────
async def listen_and_respond(audio_bytes: bytes, agent_response_fn) -> tuple[str, str, bytes]:
    """
    Full voice round-trip:
      1. Transcribe user audio → text
      2. Pass text to agent_response_fn(text) → reply text
      3. Synthesize reply text → audio bytes

    Returns (user_text, agent_reply_text, agent_reply_audio).
    """
    user_text = await transcribe(audio_bytes)
    reply_text = await agent_response_fn(user_text)
    reply_audio = await text_to_speech(reply_text)
    return user_text, reply_text, reply_audio


# ── Convenience: list available voices ───────────────────────────────────────
async def list_voices(locale_prefix: str = "ar-") -> list[dict]:
    """List all Edge TTS voices, optionally filtered by locale prefix."""
    voices = await edge_tts.list_voices()
    if locale_prefix:
        voices = [v for v in voices if v["Locale"].startswith(locale_prefix)]
    return voices


__all__ = [
    "VOICES",
    "text_to_speech",
    "text_to_speech_file",
    "transcribe",
    "transcribe_sync",
    "listen_and_respond",
    "pick_voice",
    "clean_for_speech",
    "list_voices",
]
