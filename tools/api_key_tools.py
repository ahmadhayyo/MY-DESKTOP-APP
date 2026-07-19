"""
api_key_tools.py — Verify API keys and endpoints (do they work? restricted? limits?).

These tools let the agent test the user's OWN credentials against each provider's
official API: whether a key is valid, which models it can reach, whether it's
rate-limited or restricted, and generic reachability/auth checks for any URL.

Keys are sent ONLY to their provider's own official endpoint (where they belong)
and are always masked in the output (last 4 chars). Nothing is logged or stored.

Tools:
  • test_api_key(api_key, provider)   — validate one key, list models, show limits
  • test_env_api_keys()               — test every key found in the environment
  • test_endpoint(url, ...)           — generic URL/endpoint reachability + auth check
"""
from __future__ import annotations

import os
from typing import Annotated

import httpx
from langchain_core.tools import tool

_TIMEOUT = 15.0


# ── Provider catalogue ─────────────────────────────────────────────────────────
# Each entry: how to reach a lightweight "list models" (or key-info) endpoint,
# how to attach the key, and how to detect the provider from the key prefix.
_PROVIDERS: dict[str, dict] = {
    "anthropic": {
        "label": "Anthropic (Claude)",
        "url": "https://api.anthropic.com/v1/models",
        "auth": ("header", "x-api-key"),
        "extra_headers": {"anthropic-version": "2023-06-01"},
        "prefixes": ("sk-ant-",),
    },
    "openai": {
        "label": "OpenAI",
        "url": "https://api.openai.com/v1/models",
        "auth": ("bearer", ""),
        "prefixes": ("sk-proj-", "sk-svcacct-"),
    },
    "gemini": {
        "label": "Google Gemini",
        "url": "https://generativelanguage.googleapis.com/v1beta/models",
        "auth": ("query", "key"),
        "prefixes": ("AIza",),
    },
    "groq": {
        "label": "Groq",
        "url": "https://api.groq.com/openai/v1/models",
        "auth": ("bearer", ""),
        "prefixes": ("gsk_",),
    },
    "deepseek": {
        "label": "DeepSeek",
        "url": "https://api.deepseek.com/models",
        "auth": ("bearer", ""),
        "prefixes": (),  # uses sk- (ambiguous) — resolved by fallback probing
    },
    "mistral": {
        "label": "Mistral",
        "url": "https://api.mistral.ai/v1/models",
        "auth": ("bearer", ""),
        "prefixes": (),
    },
    "openrouter": {
        "label": "OpenRouter",
        "url": "https://openrouter.ai/api/v1/key",  # returns usage + limits
        "auth": ("bearer", ""),
        "prefixes": ("sk-or-",),
    },
    "xai": {
        "label": "xAI (Grok)",
        "url": "https://api.x.ai/v1/models",
        "auth": ("bearer", ""),
        "prefixes": ("xai-",),
    },
    "together": {
        "label": "Together AI",
        "url": "https://api.together.xyz/v1/models",
        "auth": ("bearer", ""),
        "prefixes": (),
    },
    "cohere": {
        "label": "Cohere",
        "url": "https://api.cohere.ai/v1/models",
        "auth": ("bearer", ""),
        "prefixes": ("co-",),
    },
}

# When the prefix is ambiguous (bare "sk-"), try these providers in order.
_AMBIGUOUS_ORDER = ["openai", "deepseek", "mistral", "together"]

# Environment variable → provider, for test_env_api_keys().
_ENV_MAP: list[tuple[str, str]] = [
    ("ANTHROPIC_API_KEY", "anthropic"),
    ("OPENAI_API_KEY", "openai"),
    ("GOOGLE_API_KEY", "gemini"),
    ("GEMINI_API_KEY", "gemini"),
    ("GROQ_API_KEY", "groq"),
    ("DEEPSEEK_API_KEY", "deepseek"),
    ("MISTRAL_API_KEY", "mistral"),
    ("OPENROUTER_API_KEY", "openrouter"),
    ("XAI_API_KEY", "xai"),
    ("TOGETHER_API_KEY", "together"),
    ("COHERE_API_KEY", "cohere"),
]


def _mask(key: str) -> str:
    key = (key or "").strip()
    if len(key) <= 8:
        return "****"
    return f"{key[:6]}…{key[-4:]}"


def _detect_provider(key: str) -> str:
    key = (key or "").strip()
    for name, spec in _PROVIDERS.items():
        for pfx in spec.get("prefixes", ()):
            if pfx and key.startswith(pfx):
                return name
    return ""  # unknown / ambiguous


def _rate_limit_notes(headers: httpx.Headers) -> str:
    """Pull any rate-limit / restriction hints from response headers."""
    interesting = []
    for h, v in headers.items():
        hl = h.lower()
        if ("ratelimit" in hl or "rate-limit" in hl or hl == "retry-after"
                or hl.startswith("x-ratelimit")):
            interesting.append(f"    {h}: {v}")
    return "\n".join(interesting)


def _probe(provider: str, key: str) -> dict:
    """Make one request to the provider's list-models/key-info endpoint.

    Returns a dict: {ok, status, label, models, note, limits, error}.
    """
    spec = _PROVIDERS[provider]
    url = spec["url"]
    headers = dict(spec.get("extra_headers", {}))
    params = {}
    auth_kind, auth_name = spec["auth"]

    if auth_kind == "bearer":
        headers["Authorization"] = f"Bearer {key}"
    elif auth_kind == "header":
        headers[auth_name] = key
    elif auth_kind == "query":
        params[auth_name] = key

    out = {"ok": False, "status": 0, "label": spec["label"],
           "models": [], "note": "", "limits": "", "error": ""}
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            r = client.get(url, headers=headers, params=params)
        out["status"] = r.status_code
        out["limits"] = _rate_limit_notes(r.headers)

        if r.status_code == 200:
            out["ok"] = True
            try:
                data = r.json()
            except Exception:
                data = {}
            # Extract model ids across the various response shapes.
            items = []
            if isinstance(data, dict):
                items = data.get("data") or data.get("models") or []
            if provider == "openrouter" and isinstance(data, dict) and "data" in data:
                # /key endpoint → usage & limits, not a model list
                d = data.get("data", {})
                out["note"] = (
                    f"Usage: {d.get('usage')} | Limit: {d.get('limit')} | "
                    f"Free tier: {d.get('is_free_tier')} | "
                    f"Rate limit: {d.get('rate_limit')}"
                )
                items = []
            model_ids = []
            for it in items[:60]:
                if isinstance(it, dict):
                    mid = it.get("id") or it.get("name") or it.get("model")
                    if mid:
                        model_ids.append(str(mid).split("/")[-1])
                elif isinstance(it, str):
                    model_ids.append(it)
            out["models"] = model_ids
        elif r.status_code in (401, 403):
            # Invalid OR restricted — surface the provider's message verbatim.
            msg = r.text.strip()
            out["error"] = msg[:400] if msg else f"HTTP {r.status_code}"
        elif r.status_code == 429:
            out["ok"] = True  # key is valid, just throttled
            out["note"] = "Key is VALID but currently RATE-LIMITED (429)."
        else:
            out["error"] = f"HTTP {r.status_code}: {r.text.strip()[:300]}"
    except httpx.TimeoutException:
        out["error"] = f"Timed out after {_TIMEOUT:.0f}s (endpoint unreachable?)."
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def _format_result(provider: str, key: str, res: dict) -> str:
    head = f"🔑 {res['label']}  ·  key `{_mask(key)}`"
    if res["ok"]:
        lines = [f"{head}\n✅ WORKS (HTTP {res['status']})"]
        if res["note"]:
            lines.append(f"   ℹ️ {res['note']}")
        if res["models"]:
            n = len(res["models"])
            sample = ", ".join(res["models"][:12])
            more = f" … (+{n - 12} more)" if n > 12 else ""
            lines.append(f"   📦 {n} model(s) accessible: {sample}{more}")
        if res["limits"]:
            lines.append(f"   ⏱️ Rate-limit headers:\n{res['limits']}")
        return "\n".join(lines)
    else:
        status = res["status"]
        if status in (401, 403):
            verdict = "❌ INVALID or RESTRICTED"
        elif status == 0:
            verdict = "❌ UNREACHABLE"
        else:
            verdict = f"❌ FAILED (HTTP {status})"
        out = [f"{head}\n{verdict}"]
        if res["error"]:
            out.append(f"   ⚠️ {res['error']}")
        if status == 403:
            out.append("   💡 403 غالباً يعني المفتاح مقيّد (IP/Referrer/API غير مُفعّل).")
        return "\n".join(out)


@tool
def test_api_key(
    api_key: Annotated[str, "The API key to test (the user's own key)."],
    provider: Annotated[
        str,
        "Provider name: anthropic, openai, gemini, groq, deepseek, mistral, "
        "openrouter, xai, together, cohere. Leave empty to auto-detect.",
    ] = "",
) -> str:
    """Test whether an API key WORKS: valid? which models? rate-limited? restricted?

    Sends one lightweight request to the provider's official endpoint (list models
    or key-info). Reports validity, accessible models, and any rate-limit/restriction
    signals. The key is masked in all output. Auto-detects the provider from the key
    format when `provider` is omitted; for ambiguous `sk-` keys it probes a few
    providers and reports which one accepts it.

    Examples:
      test_api_key(api_key='sk-ant-...')                      # auto → Anthropic
      test_api_key(api_key='AIza...')                         # auto → Gemini
      test_api_key(api_key='sk-...', provider='deepseek')     # explicit
    """
    key = (api_key or "").strip()
    if not key:
        return "❌ No API key provided."

    provider = (provider or "").strip().lower()
    if provider and provider not in _PROVIDERS:
        known = ", ".join(_PROVIDERS.keys())
        return f"❌ Unknown provider '{provider}'. Known: {known}"

    if provider:
        return _format_result(provider, key, _probe(provider, key))

    # Auto-detect by prefix.
    detected = _detect_provider(key)
    if detected:
        return _format_result(detected, key, _probe(detected, key))

    # Ambiguous (bare sk-…): probe candidates until one accepts it.
    attempts = []
    for cand in _AMBIGUOUS_ORDER:
        res = _probe(cand, key)
        if res["ok"] or res["status"] in (429,):
            return (
                f"🔎 Auto-detected as {res['label']}.\n"
                + _format_result(cand, key, res)
            )
        attempts.append(f"  • {res['label']}: HTTP {res['status'] or '—'}")
    return (
        "❌ Could not validate this key against common providers.\n"
        "Tried:\n" + "\n".join(attempts)
        + "\n💡 حدّد المزوّد صراحةً: test_api_key(api_key=..., provider='...')"
    )


@tool
def test_env_api_keys() -> str:
    """Test EVERY API key found in the environment (.env) and report each one's status.

    Scans known variables (ANTHROPIC_API_KEY, GOOGLE_API_KEY, OPENAI_API_KEY,
    GROQ_API_KEY, DEEPSEEK_API_KEY, GEMINI_API_KEY, OPENROUTER_API_KEY, …), tests
    each present key against its provider, and returns a consolidated report:
    which keys work, which are invalid/restricted, and which are rate-limited.
    Keys are masked in the output.
    """
    seen: set[str] = set()
    reports = []
    for env_name, prov in _ENV_MAP:
        val = (os.getenv(env_name) or "").strip()
        if not val or val in seen:
            continue
        seen.add(val)
        res = _probe(prov, val)
        reports.append(f"[{env_name}]\n" + _format_result(prov, val, res))

    if not reports:
        return (
            "ℹ️ لم أجد أي مفاتيح API في البيئة.\n"
            "المتغيرات المدعومة: "
            + ", ".join(name for name, _ in _ENV_MAP)
        )
    return "🔐 نتائج فحص مفاتيح البيئة:\n\n" + "\n\n".join(reports)


@tool
def test_endpoint(
    url: Annotated[str, "The URL / API endpoint to test."],
    method: Annotated[str, "HTTP method: GET, POST, HEAD. Default GET."] = "GET",
    api_key: Annotated[str, "Optional API key/token to send for an authenticated check."] = "",
    auth_header: Annotated[
        str,
        "How to send the key: 'bearer' (Authorization: Bearer), a header name "
        "like 'x-api-key', or 'query:paramname'. Default 'bearer' when a key is given.",
    ] = "",
) -> str:
    """Check any URL/endpoint: reachable? status code? requires auth? response time?

    Reports HTTP status, whether the endpoint is open or needs authentication,
    response time, content-type, redirects, and any rate-limit headers. Optionally
    sends an API key to test authenticated access. The key is masked in output.

    Examples:
      test_endpoint(url='https://api.example.com/health')
      test_endpoint(url='https://api.example.com/v1/data', api_key='...', auth_header='x-api-key')
      test_endpoint(url='https://api.example.com/v1/data', api_key='...', auth_header='query:key')
    """
    u = (url or "").strip()
    if not u:
        return "❌ No URL provided."
    if not u.lower().startswith(("http://", "https://")):
        u = "https://" + u

    method = (method or "GET").strip().upper()
    headers: dict[str, str] = {}
    params: dict[str, str] = {}
    key = (api_key or "").strip()

    if key:
        scheme = (auth_header or "bearer").strip()
        if scheme.lower() == "bearer":
            headers["Authorization"] = f"Bearer {key}"
        elif scheme.lower().startswith("query:"):
            params[scheme.split(":", 1)[1] or "key"] = key
        else:
            headers[scheme] = key

    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            r = client.request(method, u, headers=headers, params=params)
        elapsed = r.elapsed.total_seconds() if r.elapsed else 0.0
        status = r.status_code

        if status < 300:
            verdict = "✅ OPEN / reachable"
        elif status in (401, 403):
            verdict = "🔒 Requires auth (or restricted)"
        elif status == 404:
            verdict = "⚠️ Not found (404)"
        elif status == 429:
            verdict = "⏱️ Rate-limited (429)"
        else:
            verdict = f"HTTP {status}"

        lines = [
            f"🌐 {u}",
            f"   {verdict}  ·  status {status}  ·  {elapsed*1000:.0f} ms",
            f"   Content-Type: {r.headers.get('content-type', '—')}",
        ]
        if key:
            lines.append(f"   Sent key: `{_mask(key)}`")
        if str(r.url) != u:
            lines.append(f"   ↪ Redirected to: {r.url}")
        rl = _rate_limit_notes(r.headers)
        if rl:
            lines.append(f"   ⏱️ Rate-limit headers:\n{rl}")
        # Small body preview for context.
        body = r.text.strip()
        if body:
            lines.append(f"   Body (first 200): {body[:200]}")
        return "\n".join(lines)
    except httpx.TimeoutException:
        return f"❌ {u}\n   UNREACHABLE — timed out after {_TIMEOUT:.0f}s."
    except Exception as exc:
        return f"❌ {u}\n   {type(exc).__name__}: {exc}"
