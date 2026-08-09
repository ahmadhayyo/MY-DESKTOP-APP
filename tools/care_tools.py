"""
Care Tools — "وضع الرعاية": let the agent manage a loved one's medicines by chat.

These are the son-facing controls. He talks to the agent naturally
("أضف دواء الضغط لأمي، حبة الساعة 8 صباحاً و8 مساءً مع الطعام") and the agent
calls these tools. The actual timed announcements (spoken aloud to her, free of
any model cost) are fired by the background care loop in app.py.
"""
from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool

from core import care_mode as _care

_ST = {"taken": "✅ أُخذ", "pending": "⏳ بانتظار", "missed": "⚠️ فائت", "skipped": "⏭️ متخطّى"}


@tool
def care_add_medication(
    name: Annotated[str, "اسم الدواء، مثل: بانادول، دواء الضغط، الأنسولين."],
    times: Annotated[str, "أوقات الجرعات مفصولة بفواصل، بأي صيغة: '8 صباحا, 8 مساء' أو "
                          "'08:00,14:00,20:00'."],
    dose: Annotated[str, "وصف الجرعة، مثل: 'حبة'، 'ملعقة'، '10 وحدات'."] = "",
    notes: Annotated[str, "ملاحظة تُقال/تُعرض مع التذكير، مثل: 'قبل النوم'."] = "",
    with_food: Annotated[bool, "هل يؤخذ مع الطعام؟"] = False,
) -> str:
    """Add a medication with its daily dose times to Care Mode. It will be
    announced aloud, by the patient's name, at each time — for free."""
    try:
        m = _care.add_medication(name, times, dose=dose, notes=notes, with_food=with_food)
        food = " (مع الطعام)" if m["with_food"] else ""
        return (f"✅ أُضيف «{m['name']}»{food} — المواعيد: {'، '.join(m['times'])}. "
                f"سأناديها في كل موعد بصوت دافئ. (معرّف: {m['id']})")
    except Exception as exc:
        return f"❌ تعذّرت إضافة الدواء: {exc}"


@tool
def care_list_medications() -> str:
    """List all medications currently tracked in Care Mode."""
    meds = _care.list_medications(active_only=False)
    if not meds:
        return "🕊️ لا توجد أدوية مُسجّلة بعد. أضِف أولها بـ care_add_medication."
    lines = [f"💊 **أدوية {_care.get_patient()}:**"]
    for m in meds:
        flag = "" if m.get("active", True) else " (موقوف)"
        food = " · مع الطعام" if m.get("with_food") else ""
        dose = f" · {m['dose']}" if m.get("dose") else ""
        lines.append(f"• {m['name']}{dose} — {'، '.join(m['times'])}{food}{flag}  ⟨{m['id']}⟩")
    return "\n".join(lines)


@tool
def care_mark_taken(
    medication: Annotated[str, "اسم الدواء أو معرّفه."],
    slot: Annotated[str, "وقت الجرعة، مثل '08:00'. اتركه فارغاً ليُطابق أقرب جرعة الآن."] = "",
) -> str:
    """Record that a dose was taken (stops further reminders for that dose today)."""
    res = _care.mark(medication, slot=slot or None, status="taken")
    if not res:
        return f"❌ لم أجد دواءً باسم «{medication}»."
    return f"✅ سجّلت أخذ «{res['med']}» جرعة {res['slot']}. بُشرى — نفسٌ مطمئنة."


@tool
def care_status() -> str:
    """Show today's medication plan, next dose, and adherence for the week."""
    plan = _care.today_plan()
    if not plan:
        return "🕊️ لا توجد أدوية مُسجّلة بعد."
    lines = [f"🗓️ **خطة اليوم — {_care.get_patient()}:**"]
    for r in plan:
        food = " · مع الطعام" if r["with_food"] else ""
        dose = f" ({r['dose']})" if r.get("dose") else ""
        lines.append(f"  {r['slot']} — {r['med']}{dose}{food}  {_ST.get(r['status'], r['status'])}")
    nxt = _care.next_dose()
    if nxt:
        lines.append(f"\n⏭️ الجرعة القادمة: **{nxt['med']}** الساعة **{nxt['slot']}**.")
    a = _care.adherence(7)
    lines.append(f"📈 الالتزام (7 أيام): {a['taken']}/{a['total']} ({a['percent']}%)"
                 f"{' — ⚠️ ' + str(a['missed']) + ' جرعة فائتة' if a['missed'] else ''}.")
    return "\n".join(lines)


@tool
def care_remove_medication(
    medication: Annotated[str, "اسم الدواء أو معرّفه المراد حذفه."],
) -> str:
    """Remove a medication from Care Mode entirely."""
    ok = _care.remove_medication(medication)
    return f"🗑️ حُذف «{medication}»." if ok else f"❌ لم أجد «{medication}»."


@tool
def care_set_patient(
    name: Annotated[str, "الاسم الذي تُنادى به، مثل 'أمي' أو 'ماما فاطمة'."],
) -> str:
    """Set the name the patient is addressed by in every spoken reminder."""
    n = _care.set_patient(name)
    return f"💛 سأناديها بـ «{n}» في كل تذكير."


@tool
def care_set_voice(
    gender: Annotated[str, "'أنثى'/'female' أو 'ذكر'/'male' — جنس الصوت السوري للتذكير."],
) -> str:
    """Set the reminder voice to a female or male Syrian (Levantine) voice."""
    g = _care.set_voice_gender(gender)
    label = "أنثى (سوري)" if g == "female" else "ذكر (سوري)"
    return f"🔊 صوت التذكير الآن: **{label}**."


@tool
def care_set_guardian(
    name: Annotated[str, "اسم ولي الأمر (أنت)."] = "",
    telegram_chat_id: Annotated[str, "معرّف محادثة تيليجرام لإرسال تنبيه الجرعة الفائتة."] = "",
    email: Annotated[str, "بريد إلكتروني لتنبيه الجرعة الفائتة."] = "",
) -> str:
    """Set who gets alerted (Telegram/email) if a dose is missed — quiet peace of mind."""
    g = _care.set_guardian(name=name, telegram_chat_id=telegram_chat_id, email=email)
    ch = []
    if g.get("telegram_chat_id"):
        ch.append("تيليجرام")
    if g.get("email"):
        ch.append("بريد")
    where = " و".join(ch) if ch else "لا قناة بعد"
    return f"🛡️ وليّ الأمر: {g.get('name') or '—'} · التنبيه عبر: {where}."
