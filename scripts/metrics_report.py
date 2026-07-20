"""
scripts/metrics_report.py — Summarize logs/agent_metrics.jsonl.

Shows how often the Phase-1 robustness layer helped:
  - context compaction events and total tokens saved
  - doom-loop warnings (nudges injected) and halts (runs stopped early)

Run:
    venv\\Scripts\\python scripts\\metrics_report.py
    venv\\Scripts\\python scripts\\metrics_report.py --tail 20
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_METRICS_PATH = os.path.join(_ROOT, "logs", "agent_metrics.jsonl")


def _load(path: str) -> list[dict]:
    rows: list[dict] = []
    if not os.path.exists(path):
        return rows
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="Summarize agent robustness metrics.")
    ap.add_argument("--tail", type=int, default=0, help="Also print the last N raw events.")
    args = ap.parse_args()

    rows = _load(_METRICS_PATH)
    if not rows:
        print(f"No metrics yet at {_METRICS_PATH}")
        print("Run the agent on a few tasks, then check back.")
        return 0

    compaction = [r for r in rows if r.get("event") == "compaction"]
    warnings = [r for r in rows if r.get("event") == "loop_warning"]
    halts = [r for r in rows if r.get("event") == "loop_halt"]

    tokens_saved = sum(int(r.get("tokens_saved", 0)) for r in compaction)
    outputs_pruned = sum(int(r.get("pruned", 0)) for r in compaction)

    print("=" * 52)
    print(" HAYO agent robustness — metrics summary")
    print("=" * 52)
    print(f" total events recorded      : {len(rows)}")
    print(f" context compaction events  : {len(compaction)}")
    print(f"   • tool outputs pruned     : {outputs_pruned}")
    print(f"   • tokens saved (approx)   : {tokens_saved:,}")
    print(f" doom-loop warnings (nudges): {len(warnings)}")
    print(f" doom-loop halts (stopped)  : {len(halts)}")
    print("=" * 52)

    if args.tail:
        print(f"\nLast {args.tail} events:")
        for r in rows[-args.tail:]:
            print(" ", json.dumps(r, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    sys.exit(main())
