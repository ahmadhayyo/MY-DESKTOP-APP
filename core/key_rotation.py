"""
core/key_rotation.py — Multi-account API key rotation.

For providers with a generous-but-rate-limited free tier (Groq, Gemini, ...),
a user may hold several free accounts and want the agent to automatically move
to the next key once one hits its rate limit/quota, instead of stalling.

Configuration (in .env): a comma-separated list in `<PROVIDER>_API_KEYS`
overrides the single `<PROVIDER>_API_KEY`. Example:
    GROQ_API_KEYS=gsk_key_one,gsk_key_two,gsk_key_three,gsk_key_four
If `<PROVIDER>_API_KEYS` is absent, behavior is unchanged: the single
`<PROVIDER>_API_KEY` is used and no rotation ever triggers.

Nothing here talks to the network — it only decides which key is "current"
and tracks short cooldowns for keys that were just rate-limited.
"""
from __future__ import annotations

import os
import threading
import time

_lock = threading.RLock()
_pools: dict[str, "KeyPool"] = {}


class KeyPool:
    """A rotating set of API keys for one provider."""

    def __init__(self, keys: list[str]):
        # De-dupe while preserving order.
        seen: set[str] = set()
        self._keys = [k for k in keys if k.strip() and not (k in seen or seen.add(k))]
        self._idx = 0
        self._cooldown_until: dict[str, float] = {}

    def __len__(self) -> int:
        return len(self._keys)

    def current(self) -> str:
        """The active key, or '' if the pool is empty."""
        if not self._keys:
            return ""
        return self._keys[self._idx % len(self._keys)]

    def mark_exhausted(self, key: str, cooldown_s: int = 90) -> bool:
        """Mark `key` as rate-limited and rotate to the next non-cooling key.

        Returns True if a DIFFERENT key is now current (caller should retry
        immediately), or False if there's only one key / all keys are cooling
        down (caller should fall back to waiting on the current key).
        """
        if len(self._keys) <= 1:
            return False
        with _lock:
            self._cooldown_until[key] = time.time() + cooldown_s
            start = self._idx
            for _ in range(len(self._keys)):
                self._idx = (self._idx + 1) % len(self._keys)
                cand = self._keys[self._idx]
                if self._cooldown_until.get(cand, 0.0) <= time.time():
                    return self._idx != start or cand != key
            # Every key is cooling down — stay put, caller waits.
            self._idx = start
            return False

    def stats(self) -> dict:
        now = time.time()
        return {
            "total": len(self._keys),
            "current_index": self._idx if self._keys else -1,
            "available_now": sum(
                1 for k in self._keys if self._cooldown_until.get(k, 0.0) <= now
            ),
            "cooling_down": sum(
                1 for k in self._keys if self._cooldown_until.get(k, 0.0) > now
            ),
        }


def _env_names(provider: str) -> tuple[str, str]:
    p = provider.upper().strip()
    return f"{p}_API_KEYS", f"{p}_API_KEY"


def _load_pool(provider: str) -> KeyPool:
    plural_var, single_var = _env_names(provider)
    multi = os.getenv(plural_var, "")
    if multi.strip():
        keys = [k.strip() for k in multi.split(",") if k.strip()]
    else:
        single = os.getenv(single_var, "").strip()
        keys = [single] if single else []
    return KeyPool(keys)


def get_pool(provider: str) -> KeyPool:
    """Get (lazily building) the key pool for a provider."""
    provider = provider.lower().strip()
    with _lock:
        if provider not in _pools:
            _pools[provider] = _load_pool(provider)
        return _pools[provider]


def reload_pool(provider: str) -> None:
    """Force a rebuild of a provider's pool from the current environment
    (e.g. after .env changes or a manual key update at runtime)."""
    with _lock:
        _pools.pop(provider.lower().strip(), None)


def get_active_key(provider: str, fallback_env_var: str = "") -> str:
    """The key `_build_llm` should use right now for this provider.

    Falls back to a plain os.getenv(fallback_env_var) if no pool/keys are
    configured at all, so providers without rotation set up keep working
    exactly as before.
    """
    key = get_pool(provider).current()
    if key:
        return key
    return os.getenv(fallback_env_var or f"{provider.upper()}_API_KEY", "") or ""


def rotate_on_rate_limit(provider: str) -> bool:
    """Call when `provider`'s CURRENT key just got rate-limited.

    Marks it exhausted and rotates. Returns True if a different key is now
    active (caller should rebuild its LLM client and retry immediately).
    """
    pool = get_pool(provider)
    current = pool.current()
    if not current:
        return False
    return pool.mark_exhausted(current)


def pool_status(provider: str) -> str:
    """Human-readable status line for a provider's key pool."""
    pool = get_pool(provider)
    if len(pool) <= 1:
        return f"{provider}: مفتاح واحد (لا تدوير)."
    st = pool.stats()
    return (
        f"{provider}: {st['total']} مفاتيح — "
        f"{st['available_now']} متاحة الآن، {st['cooling_down']} في فترة تهدئة "
        f"(المفتاح الحالي: #{st['current_index'] + 1})"
    )
