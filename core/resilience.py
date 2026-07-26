"""
core/resilience.py — Self-healing tool execution.

A daily-dependence agent must not fall over on a flaky network or a momentarily
locked file. This wraps every tool call so that:

  • TRANSIENT failures (network blips, timeouts, file-locked, rate limits,
    connection resets) are retried automatically with exponential backoff.
  • PERMANENT failures return a clear, actionable diagnostic the LLM can act on,
    instead of a raw Python traceback it tends to loop on.

It is intentionally dependency-free and synchronous (LangChain tools here are
sync). `run_tool_resiliently()` is the single entry point used by the worker.
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger("hayo.resilience")

# Substrings that indicate a retryable, transient condition.
_TRANSIENT_MARKERS = (
    "timeout", "timed out", "temporarily", "temporary failure",
    "connection reset", "connection aborted", "connection refused",
    "connection error", "max retries", "read timed out",
    "rate limit", "429", "too many requests", "503", "502", "504",
    "being used by another process", "resource temporarily unavailable",
    "permission denied",            # often a transient lock on Windows
    "the process cannot access the file", "sharing violation",
    "remotedisconnected", "incompleteread", "ssl", "eof occurred",
    "name or service not known", "getaddrinfo failed",
)

# Substrings that indicate a permanent error — never retry, give guidance.
_PERMANENT_MARKERS = (
    "no such file", "not found", "does not exist", "invalid", "syntax",
    "unauthorized", "forbidden", "401", "403", "not registered",
    "modulenotfounderror", "importerror", "attributeerror",
    "is not recognized as", "command not found",
)


def classify_error(text: str) -> str:
    """Return 'transient' | 'permanent' | 'unknown' for an error string."""
    low = (text or "").lower()
    for m in _PERMANENT_MARKERS:
        if m in low:
            return "permanent"
    for m in _TRANSIENT_MARKERS:
        if m in low:
            return "transient"
    return "unknown"


def _looks_like_error(result) -> bool:
    if not isinstance(result, str):
        return False
    low = result.lower()
    return (
        result.startswith("❌")
        or "[error]" in low
        or "traceback (most recent call last)" in low
        or "exception:" in low
    )


def _diagnostic(tool_name: str, err_text: str) -> str:
    """Turn a permanent error into an actionable hint for the LLM."""
    low = err_text.lower()
    hint = ""
    if "no such file" in low or "not found" in low or "does not exist" in low:
        hint = ("الملف/المسار غير موجود. تحقق من المسار بـ list_dir أو search_files، "
                "أو أنشئ المجلد أولاً.")
    elif "unauthorized" in low or "401" in low or "403" in low or "forbidden" in low:
        hint = ("فشل التحقق/الصلاحية. تحقق من مفتاح API أو تسجيل الدخول، "
                "أو جرّب أداة بديلة لا تتطلب صلاحية.")
    elif "modulenotfound" in low or "importerror" in low:
        hint = "حزمة مفقودة. ثبّتها بـ pip أو استخدم أداة بديلة."
    elif "is not recognized as" in low or "command not found" in low:
        hint = "الأمر غير متوفر على النظام. استخدم أداة مخصّصة بدل run_powershell."
    else:
        hint = "خطأ دائم — غيّر النهج أو استخدم أداة مختلفة بدل تكرار نفس الاستدعاء."
    return f"\n💡 تشخيص: {hint}"


def run_tool_resiliently(
    tool_fn,
    tool_args: dict,
    tool_name: str = "",
    *,
    max_retries: int = 2,
    base_delay: float = 0.8,
):
    """
    Invoke a LangChain tool with automatic retry on transient failures.

    Returns the tool's result string. On a transient failure it retries up to
    `max_retries` times with exponential backoff. On a permanent failure it
    appends an actionable diagnostic. The return value is ALWAYS a string the
    worker can hand to the model.

    Detects failures two ways:
      1. The tool raised an exception.
      2. The tool returned a string that looks like an error (❌ / [ERROR] / traceback).
    """
    attempt = 0
    last_text = ""
    while True:
        # ── Execute (capture both exceptions and error-shaped results) ────────
        try:
            result = tool_fn.invoke(tool_args)
            if not _looks_like_error(result):
                if attempt > 0:
                    logger.info("Tool '%s' recovered after %d retr%s",
                                tool_name, attempt, "y" if attempt == 1 else "ies")
                return result
            last_text = result if isinstance(result, str) else str(result)
            raised = False
        except Exception as exc:
            last_text = f"{type(exc).__name__}: {exc}"
            raised = True

        kind = classify_error(last_text)

        # ── Decide whether to retry ───────────────────────────────────────────
        if kind == "transient" and attempt < max_retries:
            delay = base_delay * (2 ** attempt)
            logger.info("Tool '%s' transient error (attempt %d/%d): %s — retrying in %.1fs",
                        tool_name, attempt + 1, max_retries, last_text[:120], delay)
            time.sleep(delay)
            attempt += 1
            continue

        # ── Give up — return an informative result ────────────────────────────
        if kind == "transient":
            prefix = (f"⚠️ تعذّر تنفيذ {tool_name} بعد {max_retries + 1} محاولات "
                      f"(خطأ مؤقت متكرر).\n")
            return prefix + last_text
        if kind == "permanent":
            base = (f"❌ خطأ في {tool_name}: {last_text}" if raised else last_text)
            return base + _diagnostic(tool_name, last_text)
        # unknown → return as-is (exception → format it)
        if raised:
            return f"❌ ERROR running {tool_name}: {last_text}"
        return last_text
