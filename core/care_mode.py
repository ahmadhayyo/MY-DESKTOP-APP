"""
core/care_mode.py — "وضع الرعاية" (Care Mode): a gentle medication & wellbeing
companion, built as a gift for a mother.

Why this exists
---------------
An elderly parent needs her medicines on time, spoken to her by name in a warm
voice — not a cold beep she has to read. And her son needs quiet peace of mind
that a dose was taken, without hovering. This module is the pure, testable brain
of that experience:

  • It stores each medicine (name, dose, the times of day, whether with food).
  • It knows, at any given minute, which dose is *due right now* and which was
    *missed* — without ever calling an AI model, so it is 100% free and reliable.
  • It builds the warm Arabic sentence that will be spoken aloud to her.
  • It tracks adherence and lets a guardian (the son) be alerted on a missed dose.

Design (mirrors core/scheduler.py so it feels native to this codebase)
---------------------------------------------------------------------
  • State persists to a JSON file, atomic writes, survives restarts.
  • `due_reminders(now)` is the heartbeat: it returns the events that need to
    happen this minute AND advances its own bookkeeping (how many times a dose
    was announced, whether the guardian was already alerted) — exactly the way
    scheduler.due_jobs advances next_run. The app layer just performs the I/O
    (speak / toast / alert); the decision logic lives here and is unit-tested.

Public API
    set_patient(name) / get_patient() -> str
    set_guardian(name, telegram_chat_id, email) / get_guardian() -> dict
    add_medication(name, times, dose, notes, with_food) -> dict
    list_medications(active_only) -> list[dict]
    remove_medication(id_or_name) -> bool
    mark(id_or_name, slot=None, status="taken", date=None) -> dict|None
    due_reminders(now=None) -> list[dict]     # mutates bookkeeping, like due_jobs
    today_plan(date=None) -> list[dict]
    next_dose(now=None) -> dict|None
    adherence(days=7) -> dict
    build_reminder_speech(ev) -> str
    build_missed_speech(ev) -> str
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import datetime, date as _date, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_STORE_PATH = Path(os.getenv("CARE_DATA_PATH", str(_ROOT / "care_data.json")))

_lock = threading.RLock()

# ── Tunable timing (env-overridable) ──────────────────────────────────────────
# How long after the scheduled time we keep gently re-announcing before we treat
# the dose as missed; how often to re-announce; and the cap on announcements.
GRACE_MIN = int(os.getenv("CARE_GRACE_MIN", "60"))       # missed after this long
REPEAT_MIN = int(os.getenv("CARE_REPEAT_MIN", "10"))     # re-announce cadence
MAX_ANNOUNCE = int(os.getenv("CARE_MAX_ANNOUNCE", "4"))  # announcements per dose
LEAD_MIN = int(os.getenv("CARE_LEAD_MIN", "0"))          # announce this early


# ── Persistence ───────────────────────────────────────────────────────────────
# Syrian (Levantine) neural voices — closest dialect + most natural free TTS,
# the nearest approachable equivalent to a ChatGPT-style spoken voice.
VOICE_FEMALE = os.getenv("CARE_VOICE_FEMALE", "amany")  # ar-SY-AmanyNeural
VOICE_MALE = os.getenv("CARE_VOICE_MALE", "laith")      # ar-SY-LaithNeural


def _default() -> dict:
    return {"patient": "أمي", "guardian": {"name": "", "telegram_chat_id": "", "email": ""},
            "voice_gender": "female", "meds": {}}


def _load() -> dict:
    if not _STORE_PATH.exists():
        return _default()
    try:
        with open(_STORE_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return _default()
        data.setdefault("patient", "أمي")
        data.setdefault("guardian", {"name": "", "telegram_chat_id": "", "email": ""})
        data.setdefault("voice_gender", "female")
        data.setdefault("meds", {})
        return data
    except Exception:
        return _default()


def _save(data: dict) -> None:
    tmp = _STORE_PATH.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, _STORE_PATH)


# ── Helpers ───────────────────────────────────────────────────────────────────
def _norm_time(t: str) -> str:
    """Normalise a user time string into 'HH:MM' (24h). Accepts '8', '8:5',
    '08:00', '8 am', '8 pm', '8 مساءً', '8 صباحا'. Raises ValueError on garbage."""
    raw = str(t).strip()
    if not raw:
        raise ValueError("وقت فارغ")
    low = raw.lower()
    pm = any(k in low for k in ("pm", "مساء", "مساءً", "مساءا", "م.")) or "مسا" in low
    am = any(k in low for k in ("am", "صباح", "صباحا", "صباحً", "ص.")) or "صبا" in low
    # strip non digit/colon
    cleaned = "".join(ch if (ch.isdigit() or ch == ":") else " " for ch in low).strip()
    cleaned = cleaned.split()[0] if cleaned.split() else ""
    if not cleaned:
        raise ValueError(f"تعذّر فهم الوقت: {t!r}")
    if ":" in cleaned:
        hh_s, mm_s = (cleaned.split(":") + ["0"])[:2]
    else:
        hh_s, mm_s = cleaned, "0"
    hh, mm = int(hh_s or 0), int(mm_s or 0)
    if pm and hh < 12:
        hh += 12
    if am and hh == 12:
        hh = 0
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ValueError(f"وقت غير صالح: {t!r}")
    return f"{hh:02d}:{mm:02d}"


def _norm_times(times) -> list[str]:
    if isinstance(times, str):
        parts = [p for p in times.replace("،", ",").replace(" و ", ",").split(",")]
    else:
        parts = list(times)
    out: list[str] = []
    for p in parts:
        p = str(p).strip()
        if not p:
            continue
        s = _norm_time(p)
        if s not in out:
            out.append(s)
    out.sort()
    if not out:
        raise ValueError("لا يوجد وقت صالح واحد للدواء")
    return out


def _today_str(now: float | None = None) -> str:
    dt = datetime.fromtimestamp(now) if now else datetime.now()
    return dt.strftime("%Y-%m-%d")


def _slot_epoch(date_str: str, slot: str) -> float:
    return datetime.strptime(f"{date_str} {slot}", "%Y-%m-%d %H:%M").timestamp()


def _find(data: dict, id_or_name: str) -> dict | None:
    key = str(id_or_name).strip().lower()
    for m in data["meds"].values():
        if m["id"] == id_or_name or m["name"].strip().lower() == key:
            return m
    # loose contains match on name
    for m in data["meds"].values():
        if key and key in m["name"].strip().lower():
            return m
    return None


def _entry(med: dict, date_str: str, slot: str) -> dict:
    log = med.setdefault("log", {})
    day = log.setdefault(date_str, {})
    return day.setdefault(slot, {"status": "pending", "announced": 0,
                                 "last_announced": None, "alerted": False,
                                 "taken_at": None})


# ── Patient / guardian ────────────────────────────────────────────────────────
def set_patient(name: str) -> str:
    with _lock:
        data = _load()
        data["patient"] = (name or "").strip() or "أمي"
        _save(data)
        return data["patient"]


def get_patient() -> str:
    return _load().get("patient", "أمي")


def set_guardian(name: str = "", telegram_chat_id: str = "", email: str = "") -> dict:
    with _lock:
        data = _load()
        g = data["guardian"]
        if name:
            g["name"] = name.strip()
        if telegram_chat_id:
            g["telegram_chat_id"] = str(telegram_chat_id).strip()
        if email:
            g["email"] = email.strip()
        _save(data)
        return dict(g)


def get_guardian() -> dict:
    return dict(_load().get("guardian", {}))


# ── Voice (Syrian, switchable male ↔ female) ──────────────────────────────────
def set_voice_gender(gender: str) -> str:
    """Choose whether reminders are spoken in a female or male Syrian voice."""
    g = (gender or "").strip().lower()
    if g in ("male", "ذكر", "رجل", "man", "m"):
        g = "male"
    else:
        g = "female"
    with _lock:
        data = _load()
        data["voice_gender"] = g
        _save(data)
    return g


def toggle_voice_gender() -> str:
    """Flip between the male and female Syrian voice; returns the new gender."""
    cur = _load().get("voice_gender", "female")
    return set_voice_gender("female" if cur == "male" else "male")


def get_voice_gender() -> str:
    return _load().get("voice_gender", "female")


def get_voice() -> str:
    """The short voice name (from voice_system.VOICES) for the chosen gender."""
    return VOICE_MALE if get_voice_gender() == "male" else VOICE_FEMALE


# ── Medications ───────────────────────────────────────────────────────────────
def add_medication(name: str, times, dose: str = "", notes: str = "",
                   with_food: bool = False) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("اسم الدواء مطلوب")
    slots = _norm_times(times)
    med = {
        "id": uuid.uuid4().hex[:8],
        "name": name,
        "dose": (dose or "").strip(),
        "times": slots,
        "notes": (notes or "").strip(),
        "with_food": bool(with_food),
        "active": True,
        "created_at": time.time(),
        "log": {},
    }
    with _lock:
        data = _load()
        data["meds"][med["id"]] = med
        _save(data)
    return med


def list_medications(active_only: bool = True) -> list[dict]:
    data = _load()
    meds = list(data["meds"].values())
    if active_only:
        meds = [m for m in meds if m.get("active", True)]
    meds.sort(key=lambda m: (m.get("times") or ["99:99"])[0])
    return meds


def remove_medication(id_or_name: str) -> bool:
    with _lock:
        data = _load()
        med = _find(data, id_or_name)
        if not med:
            return False
        del data["meds"][med["id"]]
        _save(data)
        return True


def set_active(id_or_name: str, active: bool) -> bool:
    with _lock:
        data = _load()
        med = _find(data, id_or_name)
        if not med:
            return False
        med["active"] = bool(active)
        _save(data)
        return True


def mark(id_or_name: str, slot: str | None = None, status: str = "taken",
         date: str | None = None, now: float | None = None) -> dict | None:
    """Record that a dose was taken/skipped. If `slot` is None, resolve to the
    nearest dose today (the one being reminded), so a plain "she took it" works."""
    with _lock:
        data = _load()
        med = _find(data, id_or_name)
        if not med:
            return None
        date_str = date or _today_str(now)
        if slot is None:
            slot = _nearest_slot(med, now)
        if slot is None:
            return None
        slot = _norm_time(slot)
        entry = _entry(med, date_str, slot)
        entry["status"] = status
        if status == "taken":
            entry["taken_at"] = now or time.time()
        _save(data)
        return {"med": med["name"], "slot": slot, "status": status, "date": date_str}


def _nearest_slot(med: dict, now: float | None = None) -> str | None:
    """The dose slot closest to `now` today — used when the caller didn't say
    which one. Prefers a slot in the recent past (the one just reminded)."""
    now = now or time.time()
    today = _today_str(now)
    best, best_d = None, None
    for slot in med.get("times", []):
        d = abs(_slot_epoch(today, slot) - now)
        if best_d is None or d < best_d:
            best, best_d = slot, d
    return best


# ── The heartbeat: what needs to happen this minute ───────────────────────────
def due_reminders(now: float | None = None) -> list[dict]:
    """Return the reminder events that should fire now, and advance bookkeeping.

    Each event: {"kind": "due"|"missed", "med_id", "med", "dose", "slot",
                 "with_food", "notes", "announce_no", "patient"}.

    Like scheduler.due_jobs, this MUTATES state: it counts announcements and
    flags a missed dose as alerted, so the caller performs each side effect
    exactly the right number of times. Pure decision logic — no I/O, no model.
    """
    now = now or time.time()
    date_str = _today_str(now)
    patient = get_patient()
    events: list[dict] = []
    changed = False

    with _lock:
        data = _load()
        for med in data["meds"].values():
            if not med.get("active", True):
                continue
            for slot in med.get("times", []):
                slot_ts = _slot_epoch(date_str, slot)
                # not time yet (respect optional early lead)
                if now < slot_ts - LEAD_MIN * 60:
                    continue
                entry = _entry(med, date_str, slot)
                if entry["status"] == "taken" or entry.get("status") == "skipped":
                    continue
                elapsed = now - slot_ts
                base = {"med_id": med["id"], "med": med["name"],
                        "dose": med.get("dose", ""), "slot": slot,
                        "with_food": med.get("with_food", False),
                        "notes": med.get("notes", ""), "patient": patient}
                if elapsed <= GRACE_MIN * 60:
                    # Still within the caring window → announce (throttled).
                    announced = entry.get("announced", 0)
                    last = entry.get("last_announced")
                    due_again = (last is None) or (now - last >= REPEAT_MIN * 60)
                    if announced < MAX_ANNOUNCE and due_again:
                        entry["announced"] = announced + 1
                        entry["last_announced"] = now
                        changed = True
                        events.append({**base, "kind": "due",
                                       "announce_no": entry["announced"]})
                else:
                    # Past the grace window → missed. Alert guardian once.
                    if not entry.get("alerted"):
                        entry["alerted"] = True
                        entry["status"] = "missed"
                        changed = True
                        events.append({**base, "kind": "missed", "announce_no": 0})
        if changed:
            _save(data)
    return events


# ── Views: plan / next dose / adherence ───────────────────────────────────────
def today_plan(date: str | None = None, now: float | None = None) -> list[dict]:
    date_str = date or _today_str(now)
    rows: list[dict] = []
    data = _load()
    for med in data["meds"].values():
        if not med.get("active", True):
            continue
        for slot in med.get("times", []):
            entry = (med.get("log", {}).get(date_str, {}) or {}).get(slot, {})
            rows.append({"slot": slot, "med": med["name"], "dose": med.get("dose", ""),
                         "with_food": med.get("with_food", False),
                         "status": entry.get("status", "pending")})
    rows.sort(key=lambda r: r["slot"])
    return rows


def next_dose(now: float | None = None) -> dict | None:
    now = now or time.time()
    best = None
    for row in today_plan(now=now):
        if row["status"] in ("taken", "skipped"):
            continue
        ts = _slot_epoch(_today_str(now), row["slot"])
        if ts >= now - GRACE_MIN * 60:
            if best is None or ts < best[0]:
                best = (ts, row)
    return best[1] if best else None


def adherence(days: int = 7, now: float | None = None) -> dict:
    now = now or time.time()
    data = _load()
    taken = total = missed = 0
    for i in range(days):
        d = (datetime.fromtimestamp(now) - timedelta(days=i)).strftime("%Y-%m-%d")
        # only count slots whose time has already passed today
        for med in data["meds"].values():
            if not med.get("active", True):
                continue
            for slot in med.get("times", []):
                if i == 0 and _slot_epoch(d, slot) > now:
                    continue  # future dose today — not countable yet
                total += 1
                st = ((med.get("log", {}).get(d, {}) or {}).get(slot, {}) or {}).get("status", "pending")
                if st == "taken":
                    taken += 1
                elif st == "missed":
                    missed += 1
    pct = round(100 * taken / total) if total else 0
    return {"days": days, "taken": taken, "missed": missed, "total": total, "percent": pct}


# ── Warm spoken lines (Arabic) ────────────────────────────────────────────────
def _dose_phrase(ev: dict) -> str:
    parts = [ev["med"]]
    if ev.get("dose"):
        parts.append(ev["dose"])
    txt = " ".join(parts)
    if ev.get("with_food"):
        txt += "، مع الطعام"
    return txt


def build_reminder_speech(ev: dict) -> str:
    """The sentence spoken aloud to her — warm, by name, unhurried."""
    patient = ev.get("patient") or "أمي"
    dose = _dose_phrase(ev)
    n = ev.get("announce_no", 1)
    if n <= 1:
        return (f"{patient} الغالية، حان الآن موعد دوائكِ: {dose}. "
                f"خذيه على مهلكِ مع كوب من الماء. أدام الله عليكِ الصحة والعافية.")
    if n == 2:
        return (f"{patient}، تذكير لطيف: دواء {ev['med']} لا يزال بانتظاركِ. "
                f"لا تنسَيْه حفظكِ الله.")
    return (f"{patient}، من فضلكِ لا تنسي دواء {ev['med']}. "
            f"صحّتكِ أغلى ما نملك.")


def build_missed_speech(ev: dict) -> str:
    patient = ev.get("patient") or "أمي"
    return (f"{patient}، فاتَ موعد دواء {ev['med']} منذ قليل. "
            f"إن لم تكوني قد أخذتِه بعد، خذيه الآن رجاءً واعتني بنفسكِ.")


def companion_summary() -> str:
    """A tiny, plain-text snapshot of today's doses for the companion persona,
    so she can ask 'شو دوائي اليوم؟' and get a real answer."""
    rows = today_plan()
    if not rows:
        return "لا يوجد أدوية مُسجّلة اليوم."
    parts = []
    st = {"taken": "تم أخذه", "missed": "فات موعده", "skipped": "متروك",
          "pending": "لسا"}
    for r in rows:
        food = " مع الأكل" if r["with_food"] else ""
        parts.append(f"{r['med']} الساعة {r['slot']}{food} ({st.get(r['status'], r['status'])})")
    return "؛ ".join(parts)


def companion_system_prompt() -> str:
    """The persona for general companionship chat with the patient — warm,
    unhurried, Syrian dialect, spoken-friendly, and safe for an elder who is
    sometimes alone. Personalised with her name and today's medicines."""
    patient = get_patient()
    meds = companion_summary()
    return (
        f"إنتِ رفيقة ذكية دافئة اسمها «هايو»، بتحكي مع {patient} — سيّدة كبيرة "
        f"بالعمر بتكون أحياناً لحالها بالبيت، وابنها جهّزك تأنسها وتهتم فيها. "
        "احكي معها باللهجة السورية الشامية، بكلام بسيط وحنون ومحترم. "
        "\n\nقواعد مهمة:\n"
        "- خلّي جوابك قصير (جملة لـ ثلاث جمل بالكتير) لأنه رح ينحكى بصوت عالي.\n"
        "- كوني صبورة، لطيفة، ومتفهّمة. اسأليها عن يومها، عن ذكرياتها، عن ولادها، "
        "عن الأكل والصلاة، وشجّعيها تشرب مي وتاكل وترتاح وتقعد بالشمس شوي.\n"
        "- إذا سألت عن دوائها، جاوبيها من هالمعلومات: " + meds + ".\n"
        "- ذكّريها بلطف بموعد الدوا إذا حان أو قرب، بلا إلحاح.\n"
        "- إنتِ مو دكتورة: ما تشخّصي مرض ولا تنصحي بجرعات دوا. \n"
        "- ⚠️ إذا اشتكت من وجع صدر، أو ضيق نفس، أو وقعة، أو نزيف، أو دوخة قوية، أو "
        "تشوّش، أو أي شي خطير: بهدوء ووضوح خبّريها تتصل فوراً بابنها أو أهلها أو "
        "بالإسعاف، وطمّنيها إنه رح يكونوا معها.\n"
        "- إذا حسّيتها زعلانة أو حزينة أو وحيدة، احتوِها بحنان وشجّعيها تتواصل مع "
        "أهلها وأحبابها.\n"
        "- لا تحكي أبداً عن مصاري أو حسابات، ولا تطلبي منها كلمة سر أو رمز. "
        "لا تخوّفيها ولا تكذبي عليها.\n"
        "- بلا رموز تعبيرية وبلا إنكليزي إلا إذا هي حكت إنكليزي. جاوبي كإنك عم تحكي "
        "معها وجهاً لوجه."
    )


def build_guardian_alert(ev: dict) -> str:
    patient = ev.get("patient") or "الوالدة"
    return (f"🔔 تنبيه الرعاية: لم يتم تأكيد أخذ {patient} لدواء "
            f"«{ev['med']}» جرعة الساعة {ev['slot']}. "
            f"قد ترغب في الاطمئنان عليها.")


if __name__ == "__main__":  # smoke test — no network, no model
    import tempfile
    _STORE_PATH = Path(tempfile.mktemp(suffix=".json"))
    set_patient("فاطمة")
    m = add_medication("بانادول", ["8", "8 مساءً"], dose="حبة", with_food=True)
    print("added:", m["name"], m["times"])
    print("plan:", today_plan())
    print("adherence:", adherence())
    # force a due event by pretending now == 08:00
    ts = _slot_epoch(_today_str(), "08:00") + 5
    evs = due_reminders(now=ts)
    print("due events:", [(e["kind"], e["slot"]) for e in evs])
    if evs:
        print("speech:", build_reminder_speech(evs[0]))
    print("care_mode smoke OK")
