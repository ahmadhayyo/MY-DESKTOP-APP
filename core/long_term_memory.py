"""
core/long_term_memory.py — Durable, human-readable knowledge store.

This is the agent's long-term memory: facts it should remember ACROSS sessions,
independent of the rolling conversation history (which gets summarized/pruned).
Think of it as the agent's notebook — user preferences, recurring details,
project context, credentials hints, "always do X", etc.

Design choices for a user who depends on this daily:
  • Stored as a single pretty-printed JSON file the user can open and edit by hand.
  • Atomic writes (temp file + os.replace) so a crash never corrupts it.
  • Each fact has: key, value, category, tags, created/updated timestamps,
    and a hit counter so the most-used facts surface first.
  • Simple, dependency-free keyword search (works offline, behind any VPN).

Public API used by the tools layer:
    remember(key, value, category, tags) -> dict
    recall(query, category, limit)        -> list[dict]
    forget(key)                           -> bool
    get(key)                              -> dict | None
    all_facts(category)                   -> list[dict]
    stats()                               -> dict
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

# Stored next to the app root. Gitignored (agent_facts.json).
_ROOT = Path(__file__).resolve().parent.parent
_STORE_PATH = Path(os.getenv("AGENT_FACTS_PATH", str(_ROOT / "agent_facts.json")))

_lock = threading.RLock()


# ── Persistence ───────────────────────────────────────────────────────────────
def _load() -> dict:
    if not _STORE_PATH.is_file():
        return {"facts": {}, "version": 1}
    try:
        with open(_STORE_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict) or "facts" not in data:
            return {"facts": {}, "version": 1}
        return data
    except Exception:
        # Corrupt file → back it up and start fresh rather than crash.
        try:
            _STORE_PATH.replace(_STORE_PATH.with_suffix(".corrupt.json"))
        except Exception:
            pass
        return {"facts": {}, "version": 1}


def _save(data: dict) -> None:
    """Atomic write: temp file in same dir, then os.replace."""
    tmp = _STORE_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, _STORE_PATH)


def _norm_key(key: str) -> str:
    return re.sub(r"\s+", " ", key.strip().lower())


# ── Core operations ───────────────────────────────────────────────────────────
def remember(
    key: str,
    value: str,
    category: str = "general",
    tags: list[str] | None = None,
) -> dict:
    """Create or update a fact. Returns the stored fact."""
    key_n = _norm_key(key)
    if not key_n:
        raise ValueError("key must not be empty")
    now = time.time()
    with _lock:
        data = _load()
        facts = data["facts"]
        existing = facts.get(key_n)
        fact = {
            "key": key_n,
            "display_key": key.strip(),
            "value": str(value).strip(),
            "category": (category or "general").strip().lower(),
            "tags": sorted({t.strip().lower() for t in (tags or []) if t.strip()}),
            "created_at": existing["created_at"] if existing else now,
            "updated_at": now,
            "hits": existing.get("hits", 0) if existing else 0,
        }
        facts[key_n] = fact
        _save(data)
        return fact


def get(key: str) -> dict | None:
    with _lock:
        data = _load()
        fact = data["facts"].get(_norm_key(key))
        if fact:
            fact["hits"] = fact.get("hits", 0) + 1
            _save(data)
        return fact


def forget(key: str) -> bool:
    with _lock:
        data = _load()
        key_n = _norm_key(key)
        if key_n in data["facts"]:
            del data["facts"][key_n]
            _save(data)
            return True
        return False


def _score(fact: dict, terms: list[str]) -> int:
    """Cheap relevance score: term hits across key/value/tags/category."""
    hay = " ".join([
        fact.get("key", ""), fact.get("value", ""),
        fact.get("category", ""), " ".join(fact.get("tags", [])),
    ]).lower()
    score = 0
    for t in terms:
        if t in hay:
            score += 2
        # token-boundary bonus
        if re.search(rf"\b{re.escape(t)}\b", hay):
            score += 1
    # Popularity tiebreaker
    score += min(fact.get("hits", 0), 5)
    return score


def recall(query: str = "", category: str = "", limit: int = 10) -> list[dict]:
    """
    Return facts matching the query/category, best matches first.
    Empty query + empty category → most-recently-updated facts.
    """
    with _lock:
        data = _load()
        facts = list(data["facts"].values())

    if category:
        cat = category.strip().lower()
        facts = [f for f in facts if f.get("category") == cat]

    q = (query or "").strip().lower()
    if not q:
        facts.sort(key=lambda f: f.get("updated_at", 0), reverse=True)
        return facts[:limit]

    terms = [t for t in re.split(r"\s+", q) if t]
    scored = [(f, _score(f, terms)) for f in facts]
    scored = [(f, s) for f, s in scored if s > 0]
    scored.sort(key=lambda fs: fs[1], reverse=True)
    return [f for f, _ in scored[:limit]]


def all_facts(category: str = "") -> list[dict]:
    with _lock:
        data = _load()
        facts = list(data["facts"].values())
    if category:
        cat = category.strip().lower()
        facts = [f for f in facts if f.get("category") == cat]
    facts.sort(key=lambda f: (f.get("category", ""), -f.get("updated_at", 0)))
    return facts


def stats() -> dict:
    with _lock:
        data = _load()
        facts = list(data["facts"].values())
    cats: dict[str, int] = {}
    for f in facts:
        cats[f.get("category", "general")] = cats.get(f.get("category", "general"), 0) + 1
    return {
        "total": len(facts),
        "categories": cats,
        "path": str(_STORE_PATH),
    }
