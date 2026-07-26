"""
core/agent_metrics.py — Lightweight, best-effort observability for the agent loop.

Appends one JSON line per notable event to ``logs/agent_metrics.jsonl`` so you can
see, after the fact, how often the new robustness layer actually helps:
  - context compaction pruning old tool outputs (tokens saved)
  - doom-loop warnings and halts

Design goals:
  - ZERO risk to the running agent: every call is wrapped so a metrics failure
    can never break a node. Nothing here is on a critical execution path.
  - No new dependencies. Plain stdlib.
  - Cheap: only writes when something notable happened.

Read it later with, e.g.:
    Get-Content logs/agent_metrics.jsonl -Tail 50
"""

from __future__ import annotations

import json
import logging
import os
import time

logger = logging.getLogger("hayo.metrics")

_METRICS_ENABLED = os.getenv("AGENT_METRICS", "1").strip().lower() not in ("0", "false", "no")
_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
_METRICS_PATH = os.path.join(_LOG_DIR, "agent_metrics.jsonl")


def record_event(event: str, **fields) -> None:
    """Append a single metrics event. Never raises."""
    if not _METRICS_ENABLED:
        return
    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
        row = {"ts": round(time.time(), 3), "event": event, **fields}
        line = json.dumps(row, ensure_ascii=False, default=str)
        with open(_METRICS_PATH, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception as exc:  # pragma: no cover - observability must never break the agent
        logger.debug("metrics write skipped: %s", exc)


if __name__ == "__main__":
    record_event("smoke_test", ok=True, note="metrics module")
    print("agent_metrics wrote to:", _METRICS_PATH)
