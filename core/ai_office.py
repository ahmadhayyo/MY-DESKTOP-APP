"""
core/ai_office.py — the AI "office brain" for precise, professional deliverables.

Purpose
-------
Built for a humanitarian-relief data worker (World Vision, North-Syria camps) who
must fill data into tables *exactly right*, across Excel · Word · PowerPoint. She
writes, in plain language, what she wants done and pastes her data; a strong model
understands the instruction, structures/cleans/computes the data, and returns a
STRICT machine spec (JSON). The deterministic renderers in core/office_convert.py
(and python-docx / python-pptx) then produce the file — so the *intelligence* is
the model's, but the *precision* is guaranteed by code, never by free-form text.

Model policy
------------
Precision matters more than pennies for this work, so the office brain tries the
strongest available model first and falls back to free:

    HAYO_OFFICE_PROVIDER (default) = "anthropic,openai,google,deepseek,omniroute"
    HAYO_OFFICE_MODEL_ANTHROPIC    = claude-sonnet-4-6   (recommended default)

Any provider without a key is skipped. The last (omniroute) is free.

The model is asked to NEVER invent numbers and to preserve Arabic as Arabic.
"""
from __future__ import annotations

import json
import os
import re

try:
    from core.key_rotation import get_active_key
except Exception:  # pragma: no cover
    def get_active_key(provider: str, fallback_env_var: str = "") -> str:
        return os.getenv(fallback_env_var or f"{provider.upper()}_API_KEY", "") or ""


_KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "groq": "GROQ_API_KEY",
    "omniroute": "",  # keyless local gateway
}


def _default_model(provider: str) -> str:
    envd = {
        "anthropic": ("HAYO_OFFICE_MODEL_ANTHROPIC",
                      os.getenv("ANTHROPIC_AGENT_MODEL", "claude-sonnet-4-6")),
        "openai": ("HAYO_OFFICE_MODEL_OPENAI",
                   os.getenv("OPENAI_AGENT_MODEL", "gpt-5.6-luna")),
        "google": ("HAYO_OFFICE_MODEL_GOOGLE",
                   os.getenv("GOOGLE_AGENT_MODEL", "gemini-flash-latest")),
        "deepseek": ("HAYO_OFFICE_MODEL_DEEPSEEK",
                     os.getenv("DEEPSEEK_AGENT_MODEL", "deepseek-chat")),
        "groq": ("HAYO_OFFICE_MODEL_GROQ",
                 os.getenv("GROQ_AGENT_MODEL", "llama-3.3-70b-versatile")),
        "omniroute": ("OMNIROUTE_AGENT_MODEL", "oc/deepseek-v4-flash-free"),
    }
    name, default = envd.get(provider, ("", ""))
    return os.getenv(name, default) if name else default


def _provider_order() -> list[str]:
    raw = os.getenv("HAYO_OFFICE_PROVIDER",
                    "anthropic,openai,google,deepseek,omniroute")
    order, seen = [], set()
    for p in (x.strip().lower() for x in raw.split(",") if x.strip()):
        if p in _KEY_ENV and p not in seen:
            seen.add(p)
            order.append(p)
    return order


def _has_key(provider: str) -> bool:
    if provider == "omniroute":
        return True  # local, keyless
    return bool(get_active_key(provider, _KEY_ENV.get(provider, "")))


def available_providers() -> list[str]:
    return [p for p in _provider_order() if _has_key(p)]


def _build_llm(provider: str):
    """Self-contained strong-model builder (independent of MODEL_PROVIDER)."""
    model = _default_model(provider)
    temp = float(os.getenv("HAYO_OFFICE_TEMPERATURE", "0"))
    max_tokens = int(os.getenv("HAYO_OFFICE_MAX_TOKENS", "4096"))
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=model, api_key=get_active_key("anthropic", _KEY_ENV["anthropic"]),
                             temperature=temp, max_tokens=max_tokens), model
    if provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model, api_key=get_active_key("openai", _KEY_ENV["openai"]),
                          temperature=temp, max_tokens=max_tokens), model
    if provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model=model, google_api_key=get_active_key("google", _KEY_ENV["google"]),
                                      temperature=temp, transport="rest",
                                      max_output_tokens=max_tokens), model
    if provider == "deepseek":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model, api_key=get_active_key("deepseek", _KEY_ENV["deepseek"]),
                          base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
                          temperature=temp, max_tokens=max_tokens), model
    if provider == "groq":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model, api_key=get_active_key("groq", _KEY_ENV["groq"]),
                          base_url="https://api.groq.com/openai/v1",
                          temperature=temp, max_tokens=max_tokens), model
    if provider == "omniroute":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model,
                          api_key=os.getenv("OMNIROUTE_API_KEY", "omniroute-local"),
                          base_url=os.getenv("OMNIROUTE_BASE_URL", "http://localhost:20128/v1"),
                          temperature=temp, max_tokens=max_tokens), model
    raise ValueError(f"provider غير معروف: {provider}")


# Injectable for tests: set ai_office._LLM_INVOKER to a callable(messages)->text
_LLM_INVOKER = None


def _invoke(messages) -> tuple[str, str]:
    """Try each available provider until one returns text. Returns (text, label)."""
    if _LLM_INVOKER is not None:  # test hook
        return _LLM_INVOKER(messages), "test"
    providers = available_providers()
    if not providers:
        raise RuntimeError("لا يوجد أي نموذج متاح. أضِف مفتاحاً في .env أو شغّل OmniRoute.")
    last = ""
    for prov in providers:
        try:
            llm, model = _build_llm(prov)
            resp = llm.invoke(messages)
            text = resp.content if isinstance(resp.content, str) else \
                "".join(b.get("text", "") for b in resp.content if isinstance(b, dict))
            if text and text.strip():
                return text, f"{prov}:{model}"
        except Exception as exc:
            last = f"{prov}: {exc}"
            continue
    raise RuntimeError(f"فشل تنفيذ مهمة الأوفيس على كل النماذج. آخر خطأ — {last}")


# ── strict JSON extraction ────────────────────────────────────────────────────
def extract_json(text: str):
    """Pull the first JSON object/array out of a model reply, tolerating code
    fences and surrounding prose."""
    if not text:
        raise ValueError("رد فارغ من النموذج.")
    m = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    candidate = m.group(1).strip() if m else text.strip()
    try:
        return json.loads(candidate)
    except Exception:
        pass
    # find first balanced {...} or [...]
    for open_c, close_c in (("{", "}"), ("[", "]")):
        i = candidate.find(open_c)
        if i == -1:
            continue
        depth = 0
        for j in range(i, len(candidate)):
            if candidate[j] == open_c:
                depth += 1
            elif candidate[j] == close_c:
                depth -= 1
                if depth == 0:
                    return json.loads(candidate[i:j + 1])
    raise ValueError("تعذّر استخراج JSON من رد النموذج.")


# ── table planning (→ Excel) ──────────────────────────────────────────────────
_TABLE_SYS = (
    "You are a precise data-structuring engine for humanitarian relief reporting "
    "(World Vision, North-Syria camps). You receive an instruction and raw data. "
    "Return ONLY strict JSON, no prose, with this schema:\n"
    '{ "title": string, "sheet_name": string, "rtl": boolean, '
    '"header": [string,...], "rows": [[cell,...],...] }\n'
    "Rules — accuracy is critical:\n"
    "- NEVER invent, drop, or alter data values. Preserve every record exactly.\n"
    "- Keep Arabic text in Arabic; keep numbers as numbers (no thousands text).\n"
    "- If the instruction asks to compute/aggregate/sort/filter, do it exactly and "
    "show your result; do not guess.\n"
    "- Every row MUST have the same number of columns as 'header'.\n"
    "- Set rtl=true if the content is mainly Arabic.\n"
    "Output JSON only."
)


def plan_table(instruction: str, data: str) -> dict:
    """Ask the office brain to structure `data` per `instruction` into a table
    spec. Returns a validated dict {title, sheet_name, rtl, header, rows}."""
    from langchain_core.messages import SystemMessage, HumanMessage
    user = f"INSTRUCTION:\n{instruction}\n\nDATA:\n{data}"
    text, label = _invoke([SystemMessage(content=_TABLE_SYS),
                           HumanMessage(content=user)])
    spec = extract_json(text)
    if not isinstance(spec, dict):
        raise ValueError("النموذج لم يُعِد كائن جدول صالح.")
    header = spec.get("header") or []
    rows = spec.get("rows") or []
    if not isinstance(header, list) or not isinstance(rows, list):
        raise ValueError("بنية الجدول غير صالحة.")
    width = len(header) if header else (max((len(r) for r in rows), default=0))
    # normalise widths defensively (precision guard)
    norm_rows = []
    for r in rows:
        r = list(r) if isinstance(r, list) else [r]
        r = (r + [""] * width)[:width] if width else r
        norm_rows.append(["" if c is None else c for c in r])
    spec["header"] = header
    spec["rows"] = norm_rows
    spec["_model"] = label
    return spec


# ── document planning (→ Word / PowerPoint) ───────────────────────────────────
_DOC_SYS = (
    "You are a professional report builder for humanitarian relief (World Vision, "
    "North-Syria camps). From the instruction and data, return ONLY strict JSON:\n"
    '{ "title": string, "rtl": boolean, "sections": [ '
    '{ "heading": string, "paragraphs": [string,...], '
    '"bullets": [string,...], "table": {"header":[...],"rows":[[...]]} } ] }\n'
    "Each section may use any subset of paragraphs/bullets/table (omit or leave "
    "empty what you don't need). Rules: never invent data; keep Arabic in Arabic; "
    "be clear, accurate and professional. Output JSON only."
)


def plan_document(instruction: str, data: str) -> dict:
    from langchain_core.messages import SystemMessage, HumanMessage
    user = f"INSTRUCTION:\n{instruction}\n\nDATA:\n{data}"
    text, label = _invoke([SystemMessage(content=_DOC_SYS),
                           HumanMessage(content=user)])
    spec = extract_json(text)
    if not isinstance(spec, dict) or "sections" not in spec:
        raise ValueError("النموذج لم يُعِد بنية مستند صالحة.")
    spec.setdefault("title", "")
    spec.setdefault("rtl", False)
    if not isinstance(spec["sections"], list):
        raise ValueError("بنية الأقسام غير صالحة.")
    spec["_model"] = label
    return spec
