"""
web_search_tools.py — Robust web search that bypasses CAPTCHA & SSL interception.

ROOT FIX for two failures:
  1. Google search → CAPTCHA wall ("unusual traffic") when automated.
  2. VPN does TLS interception → `requests` SSL verify fails.

Solution: DuckDuckGo via the `duckduckgo_search`/`ddgs` library using the
**lite backend**, which works reliably even behind a VPN and never shows CAPTCHA.

Tools:
  • web_search(query, max_results)  → ranked results (title + snippet + url)
  • web_answer(query)               → best short answer synthesized from top hits
"""
from __future__ import annotations

import logging
import warnings
from typing import Annotated

from langchain_core.tools import tool

warnings.filterwarnings("ignore")
logger = logging.getLogger("hayo.tools.websearch")

# Prefer the new package name, fall back to the old one
_DDGS = None
try:
    from ddgs import DDGS as _DDGS  # new package
except Exception:
    try:
        from duckduckgo_search import DDGS as _DDGS  # legacy
    except Exception:
        _DDGS = None


# Backend order. `None` = library auto-pick (works best). Then explicit engines.
# ddgs 9.x supports: bing, brave, google, mojeek, mullvad, yahoo, duckduckgo...
# We try auto first, then resilient engines that work behind a VPN.
_BACKENDS = [None, "bing", "brave", "google"]


def _ddg_text(query: str, max_results: int) -> list[dict]:
    """Run a web text search, trying backends until one returns results."""
    if _DDGS is None:
        return []
    last_err = None
    for backend in _BACKENDS:
        try:
            kw = {"max_results": max_results}
            if backend is not None:
                kw["backend"] = backend
            with _DDGS() as d:
                results = list(d.text(query, **kw))
            if results:
                return results
        except Exception as e:
            last_err = e
            continue
    if last_err:
        logger.warning("Web search failed on all backends: %s", last_err)
    return []


def _ddg_news(query: str, max_results: int) -> list[dict]:
    """Run a news search (good for recent events like match results)."""
    if _DDGS is None:
        return []
    for backend in _BACKENDS:
        try:
            kw = {"max_results": max_results}
            if backend is not None:
                kw["backend"] = backend
            with _DDGS() as d:
                results = list(d.news(query, **kw))
            if results:
                return results
        except Exception:
            continue
    return []


@tool
def web_search(
    query: Annotated[str, "What to search for. Be specific, e.g. 'Egypt Brazil match result June 2026'."],
    max_results: Annotated[int, "How many results to return (1-10)."] = 6,
) -> str:
    """
    Search the web and return ranked results (title, snippet, URL).

    Use this for ANY factual/web question — news, scores, prices, facts, definitions,
    'what is', 'who won', 'latest', etc. This is the PRIMARY way to answer questions
    that need fresh information from the internet.

    ⚡ IMPORTANT: Prefer this over opening a browser to Google. Google blocks the
    automated browser with a CAPTCHA ("unusual traffic"). This tool uses DuckDuckGo's
    lite endpoint which never shows CAPTCHA and works behind a VPN.

    Examples:
      web_search('Egypt Brazil match result yesterday')
      web_search('USD to EGP exchange rate today')
      web_search('Python 3.14 release date')

    Returns: A numbered list of results with title, snippet, and link.
    """
    max_results = max(1, min(int(max_results or 6), 10))

    if _DDGS is None:
        return (
            "❌ مكتبة البحث (ddgs/duckduckgo_search) غير مثبّتة.\n"
            "   ثبّتها بـ: pip install ddgs"
        )

    results = _ddg_text(query, max_results)

    # For recent events, also try news and merge if text was thin
    if len(results) < 2:
        news = _ddg_news(query, max_results)
        if news:
            # Normalize news shape to text shape
            for n in news:
                results.append({
                    "title": n.get("title", ""),
                    "body": n.get("body", ""),
                    "href": n.get("url", n.get("href", "")),
                })

    if not results:
        return (
            f"⚠️ لم أجد نتائج لـ «{query}».\n"
            f"   جرّب صياغة مختلفة أو كلمات أبسط."
        )

    lines = [f"🔎 نتائج البحث عن «{query}» ({len(results)} نتيجة):\n"]
    for i, r in enumerate(results, 1):
        title = (r.get("title") or "").strip()
        body = (r.get("body") or "").strip()
        url = (r.get("href") or r.get("url") or "").strip()
        lines.append(f"{i}. {title}")
        if body:
            lines.append(f"   {body[:280]}")
        if url:
            lines.append(f"   🔗 {url}")
        lines.append("")

    lines.append(
        "💡 لقراءة صفحة بالكامل: browser_open(url) ثم browser_get_text(). "
        "لكن غالباً المقتطفات أعلاه كافية للإجابة مباشرةً."
    )
    return "\n".join(lines)


@tool
def web_answer(
    query: Annotated[str, "A direct question, e.g. 'who won Egypt vs Brazil yesterday?'"],
) -> str:
    """
    Get a concise answer to a factual question by searching the web and
    summarizing the top results. Best for quick 'what/who/when/score/price' questions.

    This searches DuckDuckGo (no CAPTCHA, VPN-safe) and returns the most relevant
    snippets so you can state the answer directly to the user.

    Examples:
      web_answer('what was the score of Egypt vs Brazil yesterday?')
      web_answer('current price of Bitcoin')
    """
    text_results = _ddg_text(query, 5)
    news_results = _ddg_news(query, 5)

    if not text_results and not news_results:
        if _DDGS is None:
            return "❌ مكتبة البحث غير مثبّتة (pip install ddgs)."
        return f"⚠️ لم أجد إجابة لـ «{query}». جرّب صياغة أبسط."

    lines = [f"🧭 ملخص نتائج البحث عن «{query}»:\n"]

    if news_results:
        lines.append("📰 أحدث الأخبار:")
        for n in news_results[:4]:
            t = (n.get("title") or "").strip()
            b = (n.get("body") or "").strip()
            date = (n.get("date") or "").strip()
            src = (n.get("source") or "").strip()
            meta = " · ".join(x for x in [src, date] if x)
            lines.append(f"  • {t}" + (f"  ({meta})" if meta else ""))
            if b:
                lines.append(f"    {b[:240]}")
        lines.append("")

    if text_results:
        lines.append("🌐 نتائج عامة:")
        for r in text_results[:4]:
            t = (r.get("title") or "").strip()
            b = (r.get("body") or "").strip()
            lines.append(f"  • {t}")
            if b:
                lines.append(f"    {b[:240]}")
        lines.append("")

    lines.append("✍️ استخرج الإجابة المباشرة من المقتطفات أعلاه وقدّمها للمستخدم بوضوح.")
    return "\n".join(lines)
