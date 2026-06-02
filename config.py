"""
Central configuration loader.

Reads .env once, exposes typed constants the rest of the codebase imports.
Every module in agent/, tools/, core/ should import from here — never call
os.getenv directly. This keeps the surface area for misconfiguration tiny.

Supported providers: google, anthropic, openai, deepseek, groq
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

# ── Resolve project root and load .env once ──────────────────────────────────
ROOT_DIR: Path = Path(__file__).resolve().parent
ENV_PATH: Path = ROOT_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=False)

# ── Logging ──────────────────────────────────────────────────────────────────
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("hayo")


# Placeholder values that should be treated as empty (user forgot to fill .env)
_PLACEHOLDER_PATTERNS = (
    "your_", "YOUR_", "sk-placeholder",
    "_here", "_HERE", "put_your", "PUT_YOUR",
    "change_me", "CHANGE_ME", "replace_me", "REPLACE_ME",
)


def _is_placeholder(value: str) -> bool:
    """Return True if the value looks like an unfilled placeholder."""
    v = value.strip()
    if not v:
        return True
    return any(p in v for p in _PLACEHOLDER_PATTERNS)


def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _get_int(name: str, default: int) -> int:
    raw = _get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# ── Provider selection ──────────────────────────────────────────────────────
ProviderName = Literal["anthropic", "google", "openai", "deepseek", "groq", "ollama"]
MODEL_PROVIDER: ProviderName = _get("MODEL_PROVIDER", "google").lower()  # type: ignore
if MODEL_PROVIDER not in ("anthropic", "google", "openai", "deepseek", "groq", "ollama"):
    raise ValueError(
        f"MODEL_PROVIDER must be 'anthropic', 'google', 'openai', 'deepseek', 'groq', or 'ollama', got '{MODEL_PROVIDER}'"
    )

# ── Anthropic ────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY: str = _get("ANTHROPIC_API_KEY")
ANTHROPIC_AGENT_MODEL: str = _get("ANTHROPIC_AGENT_MODEL", "claude-sonnet-4-20250514")
ANTHROPIC_SUMMARIZER_MODEL: str = _get(
    "ANTHROPIC_SUMMARIZER_MODEL", "claude-haiku-4-5-20251001"
)

# ── Google Gemini ────────────────────────────────────────────────────────────
GOOGLE_API_KEY: str = _get("GOOGLE_API_KEY")
GOOGLE_AGENT_MODEL: str = _get("GOOGLE_AGENT_MODEL", "gemini-2.5-flash")
GOOGLE_SUMMARIZER_MODEL: str = _get("GOOGLE_SUMMARIZER_MODEL", "gemini-2.0-flash")

# ── OpenAI (ChatGPT) ────────────────────────────────────────────────────────
OPENAI_API_KEY: str = _get("OPENAI_API_KEY")
OPENAI_AGENT_MODEL: str = _get("OPENAI_AGENT_MODEL", "gpt-4o")
OPENAI_SUMMARIZER_MODEL: str = _get("OPENAI_SUMMARIZER_MODEL", "gpt-4o-mini")

# ── DeepSeek ─────────────────────────────────────────────────────────────────
DEEPSEEK_API_KEY: str = _get("DEEPSEEK_API_KEY")
DEEPSEEK_AGENT_MODEL: str = _get("DEEPSEEK_AGENT_MODEL", "deepseek-chat")
DEEPSEEK_SUMMARIZER_MODEL: str = _get("DEEPSEEK_SUMMARIZER_MODEL", "deepseek-chat")
DEEPSEEK_BASE_URL: str = _get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

# ── Groq ─────────────────────────────────────────────────────────────────────
GROQ_API_KEY: str = _get("GROQ_API_KEY")
GROQ_AGENT_MODEL: str = _get("GROQ_AGENT_MODEL", "llama-3.3-70b-versatile")
GROQ_SUMMARIZER_MODEL: str = _get("GROQ_SUMMARIZER_MODEL", "llama-3.1-8b-instant")

# ── Ollama (local, free) ─────────────────────────────────────────────────────
OLLAMA_BASE_URL: str = _get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_AGENT_MODEL: str = _get("OLLAMA_AGENT_MODEL", "dolphin3")
OLLAMA_SUMMARIZER_MODEL: str = _get("OLLAMA_SUMMARIZER_MODEL", "dolphin3")

# ── Agent behaviour ─────────────────────────────────────────────────────────
MAX_ITERATIONS: int = min(_get_int("MAX_ITERATIONS", 50), 500)
MAX_HISTORY: int = min(_get_int("MAX_HISTORY", 30), 300)
PS_TIMEOUT: int = min(_get_int("PS_TIMEOUT", 120), 300)

# ── Workspace / downloads ───────────────────────────────────────────────────
DEFAULT_WORKSPACE: Path = Path(_get("DEFAULT_WORKSPACE", str(ROOT_DIR)))
DESKTOP_DIR: Path = Path(_get("DESKTOP_DIR", str(Path.home() / "Desktop")))
DOWNLOADS_DIR: Path = Path(_get("DOWNLOADS_DIR", str(Path.home() / "Downloads")))

# ── Browser ─────────────────────────────────────────────────────────────────
BROWSER_HEADLESS: bool = _get("BROWSER_HEADLESS", "false").lower() == "true"
BROWSER_USER_DATA_DIR: Path = ROOT_DIR / ".browser_profile"

# ── Safety / HITL ────────────────────────────────────────────────────────────
DESTRUCTIVE_PATTERNS: tuple[str, ...] = (
    "Remove-Item -Recurse",
    "rm -rf",
    "rmdir /s",
    "format ",
    "del /f /s /q",
    "shutdown",
    "Restart-Computer",
    "Stop-Computer",
    "Set-ExecutionPolicy",
    "Invoke-WebRequest -OutFile",
    "Add-LocalGroupMember",
    "New-LocalUser",
    "reg delete",
    "diskpart",
    "cipher /w",
)

# ── All available providers (for UI model selector) ─────────────────────────
AVAILABLE_PROVIDERS: dict[str, dict] = {
    "google": {
        "label": "Google Gemini",
        "icon": "🟦",
        "key_var": "GOOGLE_API_KEY",
        "models": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
    },
    "anthropic": {
        "label": "Anthropic Claude",
        "icon": "🟠",
        "key_var": "ANTHROPIC_API_KEY",
        "models": ["claude-sonnet-4-20250514", "claude-3-5-sonnet-20241022", "claude-haiku-4-5-20251001"],
    },
    "openai": {
        "label": "OpenAI ChatGPT",
        "icon": "🟢",
        "key_var": "OPENAI_API_KEY",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
    },
    "deepseek": {
        "label": "DeepSeek",
        "icon": "🔵",
        "key_var": "DEEPSEEK_API_KEY",
        "models": ["deepseek-chat", "deepseek-reasoner"],
    },
    "groq": {
        "label": "Groq",
        "icon": "🟣",
        "key_var": "GROQ_API_KEY",
        "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"],
    },
    "ollama": {
        "label": "Ollama (محلي مجاني)",
        "icon": "🦙",
        "key_var": "",
        "models": ["dolphin3", "dolphin-llama3", "llama3.1", "llama3.2", "mistral", "gemma2", "qwen2.5", "phi3", "codellama"],
    },
}


def active_provider_key() -> str:
    """Return the API key for the currently selected provider.
    
    Ollama runs locally and does not need an API key, so it always returns
    a non-empty sentinel to pass the 'key present' check.
    """
    if MODEL_PROVIDER == "ollama":
        return "ollama-local"
    key_map = {
        "anthropic": ANTHROPIC_API_KEY,
        "google": GOOGLE_API_KEY,
        "openai": OPENAI_API_KEY,
        "deepseek": DEEPSEEK_API_KEY,
        "groq": GROQ_API_KEY,
    }
    return key_map.get(MODEL_PROVIDER, "")


def assert_keys_present() -> None:
    """Fail fast at startup if the active provider has no key.
    
    Ollama is exempt — it runs locally with no API key.
    Also detects placeholder values like 'your_gemini_api_key_here'.
    """
    if MODEL_PROVIDER == "ollama":
        return
    key_var_map = {
        "anthropic": "ANTHROPIC_API_KEY",
        "google": "GOOGLE_API_KEY",
        "openai": "OPENAI_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "groq": "GROQ_API_KEY",
    }
    provider_var = key_var_map.get(MODEL_PROVIDER, "UNKNOWN_KEY")
    key_value = active_provider_key()
    if not key_value or _is_placeholder(key_value):
        raise RuntimeError(
            f"MODEL_PROVIDER='{MODEL_PROVIDER}' but {provider_var} is empty or contains a placeholder value. "
            f"Edit {ENV_PATH} and set a real API key.\n"
            f"Tip: if you want free local AI, set MODEL_PROVIDER=ollama (no API key needed)."
        )
