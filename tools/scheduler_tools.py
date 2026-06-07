"""
scheduler_tools.py — Let the agent schedule its own work.

The agent can register tasks to run later or repeatedly. A background loop in the
app executes each due job by running its prompt through the full agent — so a
scheduled job can do ANYTHING the agent can do (download, organize files, send a
report, remind the user, etc.).

Tools:
  • schedule_task(prompt, when)        — natural language: "in 30 minutes",
                                         "every day at 09:00", "every 2 hours"
  • list_scheduled_tasks()             — show all scheduled jobs
  • cancel_scheduled_task(job_id)      — delete a job
  • toggle_scheduled_task(job_id, on)  — enable/disable without deleting
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Annotated

from langchain_core.tools import tool

from core import scheduler


# ── natural-language schedule parsing ─────────────────────────────────────────
_AR_NUM = {"دقيقة": 60, "دقائق": 60, "ساعة": 3600, "ساعات": 3600,
           "يوم": 86400, "أيام": 86400}


def _parse_when(when: str) -> dict:
    """
    Parse a schedule phrase into scheduler.add_job kwargs.
    Returns {kind, ...} or raises ValueError with a helpful message.
    """
    w = when.strip().lower()

    # ── daily at HH:MM ── "every day at 9", "daily 09:30", "كل يوم 9:00", "يومياً 21:00"
    daily_markers = ("every day", "daily", "each day", "كل يوم", "يومي", "يومياً")
    if any(m in w for m in daily_markers) or re.search(r"\b(at|الساعة|عند)\b", w):
        tm = re.search(r"(\d{1,2})[:٫\.](\d{2})", w)
        if tm:
            h, m = int(tm.group(1)), int(tm.group(2))
        else:
            hm = re.search(r"\b(\d{1,2})\b\s*(am|pm|ص|م)?", w)
            h = int(hm.group(1)) if hm else 9
            if hm and hm.group(2) in ("pm", "م") and h < 12:
                h += 12
            m = 0
        if any(mk in w for mk in daily_markers):
            return {"kind": "daily", "at_hour": h % 24, "at_minute": m % 60}

    # ── interval ── "every 2 hours", "every 30 minutes", "كل 3 ساعات"
    iv = re.search(r"(?:every|each|كل)\s*(\d+)?\s*"
                   r"(hour|hours|minute|minutes|min|ساعة|ساعات|دقيقة|دقائق)", w)
    if iv:
        n = int(iv.group(1)) if iv.group(1) else 1
        unit = iv.group(2)
        if unit in ("hour", "hours", "ساعة", "ساعات"):
            secs = n * 3600
        else:
            secs = n * 60
        return {"kind": "interval", "interval_seconds": max(60, secs)}

    # ── relative once ── "in 30 minutes", "after 2 hours", "بعد 15 دقيقة"
    rel = re.search(r"(?:in|after|بعد)\s*(\d+)\s*"
                    r"(hour|hours|minute|minutes|min|second|seconds|ساعة|ساعات|دقيقة|دقائق|ثانية|ثوان)", w)
    if rel:
        n = int(rel.group(1))
        unit = rel.group(2)
        if unit in ("hour", "hours", "ساعة", "ساعات"):
            delta = n * 3600
        elif unit in ("second", "seconds", "ثانية", "ثوان"):
            delta = n
        else:
            delta = n * 60
        return {"kind": "once", "run_at": datetime.now().timestamp() + delta}

    # ── absolute once ── "at 2025-06-10 14:00" or "today 18:30" / "tomorrow 08:00"
    iso = re.search(r"(\d{4}-\d{2}-\d{2})[ t](\d{1,2}):(\d{2})", w)
    if iso:
        dt = datetime.strptime(f"{iso.group(1)} {iso.group(2)}:{iso.group(3)}", "%Y-%m-%d %H:%M")
        return {"kind": "once", "run_at": dt.timestamp()}

    tom = re.search(r"(tomorrow|غدا|غداً|بكرا)\s*(\d{1,2})[:٫\.](\d{2})", w)
    if tom:
        base = datetime.now() + timedelta(days=1)
        dt = base.replace(hour=int(tom.group(2)) % 24, minute=int(tom.group(3)) % 60,
                          second=0, microsecond=0)
        return {"kind": "once", "run_at": dt.timestamp()}

    raise ValueError(
        "تعذّر فهم التوقيت. أمثلة مقبولة: 'in 30 minutes' / 'بعد ساعة' / "
        "'every day at 09:00' / 'كل يوم 21:30' / 'every 2 hours' / 'كل 3 ساعات' / "
        "'2025-06-10 14:00'."
    )


@tool
def schedule_task(
    prompt: Annotated[str, "The task to run later, written exactly as you'd ask the agent, e.g. 'حمّل تقرير المبيعات واحفظه على سطح المكتب'."],
    when: Annotated[str, "When to run: 'in 30 minutes', 'بعد ساعة', 'every day at 09:00', 'كل يوم 21:30', 'every 2 hours', 'كل 3 ساعات', '2025-06-10 14:00'."],
    title: Annotated[str, "Optional short name for the job."] = "",
) -> str:
    """
    Schedule a task to run automatically later or on a repeating schedule.

    The scheduled task runs through the FULL agent, so it can do anything you can
    do now. Repeating jobs ('daily'/'every N hours') keep running until cancelled.

    NOTE: scheduled jobs run while the HAYO app is open (a background loop checks
    every minute). Tell the user to keep the app running for schedules to fire.

    Examples:
      schedule_task(prompt='ذكّرني بدواء والدتي', when='every day at 09:00')
      schedule_task(prompt='افتح المتصفح وحمّل آخر كشف حساب', when='كل يوم 21:00')
      schedule_task(prompt='زامن مستودع المشروع مع GitHub', when='every 2 hours')
      schedule_task(prompt='ذكّرني بالاتصال بالصيدلية', when='in 30 minutes')
    """
    try:
        kwargs = _parse_when(when)
        job = scheduler.add_job(prompt=prompt, title=title, **kwargs)
        return (
            f"⏰ تمت جدولة المهمة:\n"
            f"   • المعرّف: {job['id']}\n"
            f"   • المهمة: {job['title']}\n"
            f"   • التوقيت: {scheduler.human_when(job)}\n"
            f"   ℹ️ تعمل الجدولة أثناء فتح تطبيق HAYO."
        )
    except ValueError as ve:
        return f"❌ {ve}"
    except Exception as exc:
        return f"❌ تعذرت الجدولة: {type(exc).__name__}: {exc}"


@tool
def list_scheduled_tasks() -> str:
    """List all scheduled tasks (active and disabled) with their next run time."""
    try:
        jobs = scheduler.list_jobs(include_disabled=True)
        if not jobs:
            return "⏰ لا توجد مهام مجدولة."
        lines = [f"⏰ المهام المجدولة ({len(jobs)}):"]
        for j in jobs:
            status = "🟢" if j.get("enabled") else "⚪"
            last = ""
            if j.get("last_run"):
                last = f" | آخر تشغيل: {datetime.fromtimestamp(j['last_run']).strftime('%m-%d %H:%M')} ({j.get('last_status','')})"
            lines.append(
                f"  {status} [{j['id']}] {j['title']}\n"
                f"      {scheduler.human_when(j)} | مرات: {j.get('run_count',0)}{last}"
            )
        return "\n".join(lines)
    except Exception as exc:
        return f"❌ تعذر عرض المهام: {exc}"


@tool
def cancel_scheduled_task(
    job_id: Annotated[str, "The job id shown by list_scheduled_tasks (e.g. 'a1b2c3d4')."],
) -> str:
    """Permanently delete a scheduled task by its id."""
    try:
        ok = scheduler.remove_job(job_id)
        return f"🗑️ تم إلغاء المهمة {job_id}." if ok else f"ℹ️ لا توجد مهمة بالمعرّف {job_id}."
    except Exception as exc:
        return f"❌ تعذر الإلغاء: {exc}"


@tool
def toggle_scheduled_task(
    job_id: Annotated[str, "The job id."],
    enabled: Annotated[bool, "True to enable, False to pause without deleting."] = True,
) -> str:
    """Enable or pause a scheduled task without deleting it."""
    try:
        ok = scheduler.set_enabled(job_id, enabled)
        if not ok:
            return f"ℹ️ لا توجد مهمة بالمعرّف {job_id}."
        return f"{'🟢 تم تفعيل' if enabled else '⚪ تم إيقاف'} المهمة {job_id}."
    except Exception as exc:
        return f"❌ تعذر التغيير: {exc}"
