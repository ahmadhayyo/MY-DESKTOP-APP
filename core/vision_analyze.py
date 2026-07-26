"""
core/vision_analyze.py — Real multimodal "eyes" for the HAYO agent.

Problem this solves
-------------------
The agent could screenshot + OCR, but it could not *see*: understand layout,
colours, icons without text, whether a rendered UI looks correct, or diagnose a
visual bug. The main text provider (groq/deepseek) is text-only and cannot look
at an image at all.

Strategy
--------
A dedicated, self-contained vision path that is **independent of MODEL_PROVIDER**.
It takes an image (a PIL image, a file path, or a raw base64 string), sends it to
a vision-capable model as a proper multimodal message, and returns the model's
natural-language analysis answering an optional question.

Provider selection honours HAYO_VISION_PROVIDER (default order below) and falls
back automatically to the next provider that has a key — so the "eyes" keep
working even if one provider errors.

  Default order (user choice 2026-07-21): google (Gemini) → anthropic (Claude).

Env:
  HAYO_VISION_PROVIDER  = "google,anthropic"  (comma list, tried in order)
  HAYO_VISION_GOOGLE_MODEL     = gemini-2.0-flash
  HAYO_VISION_ANTHROPIC_MODEL  = claude-sonnet-4-20250514
  HAYO_VISION_OPENAI_MODEL     = gpt-4o
  HAYO_VISION_MAX_TOKENS       = 1500
"""

from __future__ import annotations

import base64
import io
import os
from dataclasses import dataclass

try:
    from core.key_rotation import get_active_key
except Exception:  # pragma: no cover - key rotation optional
    def get_active_key(provider: str, fallback_env_var: str = "") -> str:
        return os.getenv(fallback_env_var or f"{provider.upper()}_API_KEY", "") or ""


# Vision-capable providers only. groq/deepseek/ollama are excluded (text-only in
# this deployment) so we never hand an image to a model that cannot read it.
_DEFAULT_ORDER = ("google", "anthropic", "openai")

_MODEL_ENV = {
    # gemini-flash-latest is a stable alias that auto-tracks the current flash
    # model, so a retired dated model (e.g. gemini-2.0-flash) never breaks vision.
    "google": ("HAYO_VISION_GOOGLE_MODEL", "gemini-flash-latest"),
    "anthropic": ("HAYO_VISION_ANTHROPIC_MODEL",
                  os.getenv("ANTHROPIC_AGENT_MODEL", "claude-sonnet-4-6")),
    "openai": ("HAYO_VISION_OPENAI_MODEL", "gpt-4o"),
}

_KEY_ENV = {
    "google": "GOOGLE_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}


@dataclass
class VisionResult:
    ok: bool
    text: str
    provider: str = ""
    model: str = ""

    def __str__(self) -> str:
        return self.text


# ── image normalisation ──────────────────────────────────────────────────────

def _to_base64_png(image) -> str:
    """Accept a PIL image, a file path, raw bytes, or an existing base64 string
    and return a base64-encoded PNG (no data: prefix)."""
    # Already a base64 string?
    if isinstance(image, str):
        # data URI → strip header
        if image.startswith("data:"):
            return image.split(",", 1)[1]
        # looks like a path
        if os.path.exists(image):
            with open(image, "rb") as fh:
                raw = fh.read()
            return base64.b64encode(raw).decode()
        # assume it is already bare base64
        return image
    if isinstance(image, (bytes, bytearray)):
        return base64.b64encode(bytes(image)).decode()
    # PIL image
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


# ── provider order ───────────────────────────────────────────────────────────

def _extract_text(content) -> str:
    """Normalise a LangChain message content into plain text.

    Gemini/Anthropic can return content as a list of blocks
    (``[{"type": "text", "text": "..."}, ...]``) instead of a bare string.
    Join the text parts so callers always get clean prose, never a repr.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                t = block.get("text") or block.get("content") or ""
                if t:
                    parts.append(str(t))
        return "\n".join(parts)
    return str(content) if content is not None else ""


def _provider_order() -> list[str]:
    raw = os.getenv("HAYO_VISION_PROVIDER", "").strip()
    if raw:
        order = [p.strip().lower() for p in raw.split(",") if p.strip()]
    else:
        order = list(_DEFAULT_ORDER)
    # keep only known vision providers, preserving order + de-dup
    seen: set[str] = set()
    out: list[str] = []
    for p in order:
        if p in _MODEL_ENV and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _has_key(provider: str) -> bool:
    return bool(get_active_key(provider, _KEY_ENV.get(provider, "")))


def available_vision_providers() -> list[str]:
    """Vision providers that both are in the configured order AND have a key."""
    return [p for p in _provider_order() if _has_key(p)]


# ── model builders (self-contained; no import of agent.nodes) ─────────────────

def _build_vision_llm(provider: str):
    max_tokens = int(os.getenv("HAYO_VISION_MAX_TOKENS", "1500"))
    env_name, default_model = _MODEL_ENV[provider]
    model = os.getenv(env_name, default_model)
    key = get_active_key(provider, _KEY_ENV[provider])

    if provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=model, google_api_key=key, temperature=0.0,
            max_output_tokens=max_tokens,
        ), model
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=model, api_key=key, max_tokens=max_tokens, temperature=0.0,
        ), model
    if provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model, api_key=key, temperature=0.0, max_tokens=max_tokens,
        ), model
    raise ValueError(f"Unknown vision provider: {provider}")


_DEFAULT_PROMPT = (
    "You are the visual perception module of an autonomous desktop agent. "
    "Look at this screenshot and describe precisely what is visible: the "
    "application/window, the layout, key UI elements and their state, any text, "
    "and — importantly — anything that looks wrong, broken, misaligned, an error "
    "dialog, or an unexpected visual state. Be concrete and specific; the agent "
    "will act on your description."
)


def analyze(image, question: str = "", *, detail_prompt: str = "") -> VisionResult:
    """Send `image` to a vision model and return its analysis.

    `image` may be a PIL image, a file path, raw bytes, or a base64 string.
    Tries each available vision provider in order until one succeeds.
    """
    providers = available_vision_providers()
    if not providers:
        return VisionResult(
            ok=False,
            text=(
                "❌ لا يوجد نموذج رؤية متاح. أضِف مفتاح GOOGLE_API_KEY أو "
                "ANTHROPIC_API_KEY في .env لتفعيل تحليل الصور."
            ),
        )

    try:
        b64 = _to_base64_png(image)
    except Exception as exc:
        return VisionResult(ok=False, text=f"❌ تعذّر تجهيز الصورة: {exc}")

    prompt = (detail_prompt or _DEFAULT_PROMPT)
    if question:
        prompt = f"{prompt}\n\nUser question about the image: {question}"

    from langchain_core.messages import HumanMessage

    msg = HumanMessage(content=[
        {"type": "text", "text": prompt},
        {"type": "image_url",
         "image_url": {"url": f"data:image/png;base64,{b64}"}},
    ])

    last_err = ""
    for provider in providers:
        try:
            llm, model = _build_vision_llm(provider)
            resp = llm.invoke([msg])
            text = _extract_text(resp.content)
            if text and text.strip():
                return VisionResult(ok=True, text=text.strip(),
                                    provider=provider, model=model)
            last_err = f"{provider}: رد فارغ"
        except Exception as exc:  # try next provider
            last_err = f"{provider}: {exc}"
            continue

    return VisionResult(ok=False, text=f"❌ فشل تحليل الصورة. آخر خطأ — {last_err}")


if __name__ == "__main__":  # smoke test (no network): provider resolution only
    print("configured order:", _provider_order())
    print("available (with key):", available_vision_providers())
    # tiny 1x1 png
    from PIL import Image
    img = Image.new("RGB", (1, 1), (255, 0, 0))
    print("base64 len:", len(_to_base64_png(img)))
    print("vision_analyze smoke OK")
