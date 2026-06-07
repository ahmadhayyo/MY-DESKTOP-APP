"""
core/scheduler.py — Persistent job scheduler for recurring/one-off agent tasks.

Lets the agent run work on a schedule: "every morning at 9 download the report",
"in 30 minutes remind me to call the pharmacy", "every 2 hours sync my repo".

Design:
  • Jobs persist to a JSON file (survives restarts), atomic writes.
  • Three schedule kinds:
      - "once"     : run a single time at `run_at` (epoch seconds)
      - "interval" : run every `interval_seconds`
      - "daily"    : run every day at `at_hour:at_minute` (local time)
  • `due_jobs(now)` returns jobs whose next_run <= now and marks the next run.
  • The actual EXECUTION is done by the app layer (app.py background loop),
    which feeds each due job's `prompt` back through the agent graph. This keeps
    the scheduler pure/testable and lets scheduled tasks use the FULL agent.

Public API:
    add_job(prompt, kind, ...) -> dict
    list_jobs(include_disabled) -> list[dict]
    remove_job(job_id) -> bool
    set_enabled(job_id, enabled) -> bool
    due_jobs(now) -> list[dict]          # also advances next_run / disables once-jobs
    mark_ran(job_id, ok, note)
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_STORE_PATH = Path(os.getenv("SCHEDULED_JOBS_PATH", str(_ROOT / "scheduled_jobs.json")))

_lock = threading.RLock()

VALID_KINDS = ("once", "interval", "daily")


# ── Persistence ───────────────────────────────────────────────────────────────
def _load() -> dict:
    if not _STORE_PATH.is_file():
        return {"jobs": {}, "version": 1}
    try:
        with open(_STORE_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict) or "jobs" not in data:
            return {"jobs": {}, "version": 1}
        return data
    except Exception:
        try:
            _STORE_PATH.replace(_STORE_PATH.with_suffix(".corrupt.json"))
        except Exception:
            pass
        return {"jobs": {}, "version": 1}


def _save(data: dict) -> None:
    tmp = _STORE_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, _STORE_PATH)


# ── next-run computation ──────────────────────────────────────────────────────
def _compute_first_run(kind: str, now: float, *, run_at: float | None,
                       interval_seconds: int | None,
                       at_hour: int | None, at_minute: int | None) -> float:
    if kind == "once":
        return float(run_at if run_at is not None else now)
    if kind == "interval":
        return now + float(interval_seconds or 3600)
    if kind == "daily":
        h = int(at_hour if at_hour is not None else 9)
        m = int(at_minute if at_minute is not None else 0)
        dt = datetime.fromtimestamp(now)
        target = dt.replace(hour=h, minute=m, second=0, microsecond=0)
        if target.timestamp() <= now:
            target = target + timedelta(days=1)
        return target.timestamp()
    return now


def _advance(job: dict, now: float) -> float | None:
    """Compute the next run after firing. Returns None for finished once-jobs."""
    kind = job["kind"]
    if kind == "once":
        return None
    if kind == "interval":
        return now + float(job.get("interval_seconds") or 3600)
    if kind == "daily":
        h = int(job.get("at_hour", 9))
        m = int(job.get("at_minute", 0))
        dt = datetime.fromtimestamp(now)
        target = dt.replace(hour=h, minute=m, second=0, microsecond=0) + timedelta(days=1)
        return target.timestamp()
    return None


# ── CRUD ──────────────────────────────────────────────────────────────────────
def add_job(
    prompt: str,
    kind: str = "once",
    *,
    run_at: float | None = None,
    interval_seconds: int | None = None,
    at_hour: int | None = None,
    at_minute: int | None = None,
    title: str = "",
) -> dict:
    if kind not in VALID_KINDS:
        raise ValueError(f"kind must be one of {VALID_KINDS}, got '{kind}'")
    if not prompt.strip():
        raise ValueError("prompt must not be empty")

    now = time.time()
    next_run = _compute_first_run(
        kind, now, run_at=run_at, interval_seconds=interval_seconds,
        at_hour=at_hour, at_minute=at_minute,
    )
    job = {
        "id": uuid.uuid4().hex[:8],
        "title": title.strip() or prompt.strip()[:60],
        "prompt": prompt.strip(),
        "kind": kind,
        "interval_seconds": int(interval_seconds) if interval_seconds else None,
        "at_hour": int(at_hour) if at_hour is not None else None,
        "at_minute": int(at_minute) if at_minute is not None else None,
        "created_at": now,
        "next_run": next_run,
        "enabled": True,
        "run_count": 0,
        "last_run": None,
        "last_status": "",
    }
    with _lock:
        data = _load()
        data["jobs"][job["id"]] = job
        _save(data)
    return job


def list_jobs(include_disabled: bool = True) -> list[dict]:
    with _lock:
        data = _load()
        jobs = list(data["jobs"].values())
    if not include_disabled:
        jobs = [j for j in jobs if j.get("enabled")]
    jobs.sort(key=lambda j: j.get("next_run") or 0)
    return jobs


def remove_job(job_id: str) -> bool:
    with _lock:
        data = _load()
        if job_id in data["jobs"]:
            del data["jobs"][job_id]
            _save(data)
            return True
        return False


def set_enabled(job_id: str, enabled: bool) -> bool:
    with _lock:
        data = _load()
        j = data["jobs"].get(job_id)
        if not j:
            return False
        j["enabled"] = bool(enabled)
        _save(data)
        return True


def due_jobs(now: float | None = None) -> list[dict]:
    """
    Return enabled jobs whose next_run <= now, and advance their schedule
    (or disable finished once-jobs) atomically so they don't double-fire.
    """
    now = now if now is not None else time.time()
    fired: list[dict] = []
    with _lock:
        data = _load()
        changed = False
        for j in data["jobs"].values():
            if not j.get("enabled"):
                continue
            nr = j.get("next_run")
            if nr is None or nr > now:
                continue
            fired.append(dict(j))  # snapshot for the caller
            nxt = _advance(j, now)
            if nxt is None:
                j["enabled"] = False
                j["next_run"] = None
            else:
                j["next_run"] = nxt
            changed = True
        if changed:
            _save(data)
    return fired


def mark_ran(job_id: str, ok: bool, note: str = "") -> None:
    with _lock:
        data = _load()
        j = data["jobs"].get(job_id)
        if not j:
            return
        j["run_count"] = j.get("run_count", 0) + 1
        j["last_run"] = time.time()
        j["last_status"] = ("ok" if ok else "error") + (f": {note[:120]}" if note else "")
        _save(data)


def human_when(job: dict) -> str:
    """Readable description of when a job runs next."""
    kind = job["kind"]
    nr = job.get("next_run")
    nr_str = datetime.fromtimestamp(nr).strftime("%Y-%m-%d %H:%M") if nr else "—"
    if kind == "once":
        return f"مرة واحدة في {nr_str}"
    if kind == "interval":
        secs = job.get("interval_seconds") or 0
        if secs % 3600 == 0:
            every = f"كل {secs // 3600} ساعة"
        elif secs % 60 == 0:
            every = f"كل {secs // 60} دقيقة"
        else:
            every = f"كل {secs} ثانية"
        return f"{every} (التالي: {nr_str})"
    if kind == "daily":
        return f"يومياً الساعة {job.get('at_hour', 9):02d}:{job.get('at_minute', 0):02d} (التالي: {nr_str})"
    return nr_str
