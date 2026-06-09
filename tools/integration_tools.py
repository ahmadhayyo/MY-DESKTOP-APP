"""
integration_tools.py — REAL working connectors to external services.

The integrations hub previously listed services (Slack, Discord, Notion…) with no
actual tools behind them. This module implements genuine, testable connectors, plus
several new integrations chosen for everyday usefulness:

  Notifications / messaging:
    • send_discord(message)            — Discord via incoming webhook
    • send_slack(message)              — Slack via incoming webhook
    • telegram_bot_send(text, chat_id) — Telegram via your bot token
  Productivity / data:
    • send_email(to, subject, body, attachments)  — SMTP email (NEW)
    • notion_create_page(title, content)          — Notion page (NEW)
  General purpose:
    • http_request(method, url, headers, json_body) — call ANY REST API (NEW)
    • get_weather(city)                              — live weather, no key (NEW)
    • get_crypto_price(symbol)                       — live crypto price, no key (NEW)

Each tool degrades gracefully with clear setup instructions when a key is missing.
All HTTP calls tolerate the user's VPN doing TLS interception (verify fallback).
"""
from __future__ import annotations

import os
import warnings
from pathlib import Path
from typing import Annotated

from langchain_core.tools import tool


def _http(method: str, url: str, **kw):
    """requests wrapper with a verify fallback for VPN TLS interception."""
    import requests
    try:
        return requests.request(method, url, timeout=kw.pop("timeout", 25), **kw)
    except requests.exceptions.SSLError:
        warnings.filterwarnings("ignore")
        try:
            import urllib3
            urllib3.disable_warnings()
        except Exception:
            pass
        return requests.request(method, url, timeout=25, verify=False, **kw)


# ═══════════════════════════════════════════════════════════════════════════════
#  MESSAGING / NOTIFICATIONS
# ═══════════════════════════════════════════════════════════════════════════════
@tool
def send_discord(
    message: Annotated[str, "The message text to post."],
    webhook_url: Annotated[str, "Discord webhook URL. Empty = use DISCORD_WEBHOOK_URL from .env."] = "",
) -> str:
    """إرسال رسالة إلى قناة Discord عبر Webhook (إشعارات، تنبيهات، نتائج المهام)."""
    url = webhook_url or os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if not url:
        return ("❌ لا يوجد Discord webhook.\n"
                "   أنشئ واحداً: إعدادات القناة → Integrations → Webhooks → New Webhook،\n"
                "   ثم ضع الرابط في .env:  DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...")
    try:
        r = _http("POST", url, json={"content": message[:1900]})
        if r.status_code in (200, 204):
            return "✅ تم إرسال الرسالة إلى Discord."
        return f"❌ Discord رفض الطلب ({r.status_code}): {r.text[:200]}"
    except Exception as e:
        return f"❌ خطأ في الإرسال: {e}"


@tool
def send_slack(
    message: Annotated[str, "The message text to post."],
    webhook_url: Annotated[str, "Slack webhook URL. Empty = use SLACK_WEBHOOK_URL from .env."] = "",
) -> str:
    """إرسال رسالة إلى قناة Slack عبر Incoming Webhook."""
    url = webhook_url or os.getenv("SLACK_WEBHOOK_URL", "").strip()
    if not url:
        return ("❌ لا يوجد Slack webhook.\n"
                "   أنشئه من https://api.slack.com/messaging/webhooks، ثم في .env:\n"
                "   SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...")
    try:
        r = _http("POST", url, json={"text": message[:3000]})
        if r.status_code == 200:
            return "✅ تم إرسال الرسالة إلى Slack."
        return f"❌ Slack رفض الطلب ({r.status_code}): {r.text[:200]}"
    except Exception as e:
        return f"❌ خطأ في الإرسال: {e}"


@tool
def telegram_bot_send(
    text: Annotated[str, "Message text to send."],
    chat_id: Annotated[str, "Target chat id/username. Empty = use TELEGRAM_CHAT_ID from .env."] = "",
) -> str:
    """إرسال رسالة عبر بوت Telegram (يستخدم TELEGRAM_BOT_TOKEN). مفيد للإشعارات لنفسك."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return ("❌ لا يوجد TELEGRAM_BOT_TOKEN في .env.\n"
                "   أنشئ بوتاً عبر @BotFather واحصل على التوكن.")
    cid = chat_id or os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not cid:
        return ("❌ لا يوجد chat_id. أرسل رسالة لبوتك أولاً، ثم احصل على معرّفك من\n"
                "   https://api.telegram.org/bot<TOKEN>/getUpdates، وضعه في TELEGRAM_CHAT_ID.")
    try:
        r = _http("POST", f"https://api.telegram.org/bot{token}/sendMessage",
                  json={"chat_id": cid, "text": text[:4000]})
        if r.status_code == 200 and r.json().get("ok"):
            return "✅ تم إرسال الرسالة عبر بوت Telegram."
        return f"❌ Telegram رفض الطلب ({r.status_code}): {r.text[:200]}"
    except Exception as e:
        return f"❌ خطأ في الإرسال: {e}"


# ═══════════════════════════════════════════════════════════════════════════════
#  EMAIL (SMTP)
# ═══════════════════════════════════════════════════════════════════════════════
@tool
def send_email(
    to: Annotated[str, "Recipient email (or comma-separated list)."],
    subject: Annotated[str, "Email subject."],
    body: Annotated[str, "Email body (plain text)."],
    attachments: Annotated[str, "Optional comma-separated file paths to attach."] = "",
) -> str:
    """إرسال بريد إلكتروني عبر SMTP (مع مرفقات اختيارية).

    الإعداد في .env (مثال Gmail — استخدم App Password وليس كلمة مرورك العادية):
        SMTP_HOST=smtp.gmail.com
        SMTP_PORT=587
        SMTP_USER=you@gmail.com
        SMTP_PASS=app_password_16_chars
    """
    host = os.getenv("SMTP_HOST", "").strip()
    user = os.getenv("SMTP_USER", "").strip()
    pwd = os.getenv("SMTP_PASS", "").strip()
    port = int(os.getenv("SMTP_PORT", "587") or 587)
    if not (host and user and pwd):
        return ("❌ إعداد SMTP ناقص في .env. أضِف:\n"
                "   SMTP_HOST=smtp.gmail.com\n   SMTP_PORT=587\n"
                "   SMTP_USER=you@gmail.com\n   SMTP_PASS=app_password\n"
                "   (لـ Gmail: فعّل التحقق بخطوتين ثم أنشئ App Password)")
    try:
        import smtplib
        from email.message import EmailMessage
        msg = EmailMessage()
        msg["From"] = user
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        for path in [p.strip() for p in attachments.split(",") if p.strip()]:
            fp = Path(path)
            if fp.is_file():
                data = fp.read_bytes()
                msg.add_attachment(data, maintype="application", subtype="octet-stream",
                                   filename=fp.name)
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls()
            s.login(user, pwd)
            s.send_message(msg)
        return f"✅ تم إرسال البريد إلى {to}" + (
            f" مع {len([p for p in attachments.split(',') if p.strip()])} مرفق" if attachments.strip() else "")
    except Exception as e:
        return f"❌ فشل إرسال البريد: {e}"


# ═══════════════════════════════════════════════════════════════════════════════
#  NOTION
# ═══════════════════════════════════════════════════════════════════════════════
@tool
def notion_create_page(
    title: Annotated[str, "Page title."],
    content: Annotated[str, "Page body (plain text; each line becomes a paragraph)."],
    parent_page_id: Annotated[str, "Parent page id. Empty = use NOTION_PARENT_PAGE_ID from .env."] = "",
) -> str:
    """إنشاء صفحة جديدة في Notion تحت صفحة أب.

    الإعداد: أنشئ Integration من https://www.notion.so/my-integrations، شاركها مع
    صفحتك، ثم في .env:  NOTION_API_KEY=secret_...   NOTION_PARENT_PAGE_ID=<page_id>
    """
    key = os.getenv("NOTION_API_KEY", "").strip()
    if not key:
        return ("❌ لا يوجد NOTION_API_KEY في .env.\n"
                "   أنشئ Integration من https://www.notion.so/my-integrations وضع المفتاح.")
    parent = parent_page_id or os.getenv("NOTION_PARENT_PAGE_ID", "").strip()
    if not parent:
        return ("❌ لا يوجد parent_page_id. افتح صفحة في Notion، شاركها مع الـ Integration،\n"
                "   وانسخ معرّفها من الرابط، ضعه في NOTION_PARENT_PAGE_ID.")
    try:
        headers = {"Authorization": f"Bearer {key}",
                   "Content-Type": "application/json",
                   "Notion-Version": "2022-06-28"}
        children = [{"object": "block", "type": "paragraph",
                     "paragraph": {"rich_text": [{"type": "text", "text": {"content": line[:1900]}}]}}
                    for line in content.split("\n") if line.strip()]
        payload = {"parent": {"page_id": parent},
                   "properties": {"title": [{"type": "text", "text": {"content": title}}]},
                   "children": children}
        r = _http("POST", "https://api.notion.com/v1/pages", headers=headers, json=payload)
        if r.status_code == 200:
            return f"✅ تم إنشاء صفحة Notion: «{title}»"
        return f"❌ Notion رفض الطلب ({r.status_code}): {r.text[:250]}"
    except Exception as e:
        return f"❌ خطأ: {e}"


# ═══════════════════════════════════════════════════════════════════════════════
#  GENERAL PURPOSE — call ANY API, plus zero-config live data
# ═══════════════════════════════════════════════════════════════════════════════
@tool
def http_request(
    method: Annotated[str, "HTTP method: GET, POST, PUT, DELETE, PATCH."],
    url: Annotated[str, "Full URL of the API endpoint."],
    headers: Annotated[str, "Optional JSON object of headers, e.g. '{\"Authorization\":\"Bearer X\"}'."] = "",
    json_body: Annotated[str, "Optional JSON body for POST/PUT/PATCH."] = "",
) -> str:
    """استدعاء أي واجهة REST API (GET/POST/...). أداة عامة لربط الوكيل بأي خدمة ويب.

    مثال: http_request(method='GET', url='https://api.github.com/repos/python/cpython')
    """
    import json as _json
    try:
        hdrs = _json.loads(headers) if headers.strip() else {}
    except Exception:
        return "❌ headers يجب أن تكون JSON صحيحاً."
    body = None
    if json_body.strip():
        try:
            body = _json.loads(json_body)
        except Exception:
            return "❌ json_body يجب أن يكون JSON صحيحاً."
    try:
        r = _http(method.upper(), url, headers=hdrs, json=body)
        text = r.text
        if len(text) > 3000:
            text = text[:3000] + f"\n…[مقتطع، الإجمالي {len(r.text)} حرف]"
        return f"📡 {method.upper()} {url}\nالحالة: {r.status_code}\n\n{text}"
    except Exception as e:
        return f"❌ فشل الطلب: {e}"


@tool
def get_weather(
    city: Annotated[str, "City name, e.g. 'Riyadh', 'Cairo', 'London'."],
) -> str:
    """حالة الطقس الحالية لأي مدينة (بدون مفتاح API — عبر wttr.in)."""
    try:
        r = _http("GET", f"https://wttr.in/{city}?format=j1")
        if r.status_code != 200:
            return f"❌ تعذّر جلب الطقس ({r.status_code})."
        d = r.json()
        cur = d["current_condition"][0]
        area = d.get("nearest_area", [{}])[0]
        place = area.get("areaName", [{}])[0].get("value", city)
        desc = cur["weatherDesc"][0]["value"]
        return (f"🌤️ الطقس في {place}:\n"
                f"   الحرارة: {cur['temp_C']}°م (إحساس {cur['FeelsLikeC']}°م)\n"
                f"   الحالة: {desc}\n"
                f"   الرطوبة: {cur['humidity']}% | الرياح: {cur['windspeedKmph']} كم/س")
    except Exception as e:
        return f"❌ خطأ في جلب الطقس: {e}"


@tool
def get_crypto_price(
    symbol: Annotated[str, "Crypto symbol, e.g. 'bitcoin', 'ethereum', 'solana'."] = "bitcoin",
) -> str:
    """السعر اللحظي لعملة رقمية مقابل USD (بدون مفتاح — عبر CoinGecko)."""
    try:
        s = symbol.lower().strip()
        r = _http("GET", "https://api.coingecko.com/api/v3/simple/price",
                  params={"ids": s, "vs_currencies": "usd", "include_24hr_change": "true"})
        d = r.json()
        if s not in d:
            return f"ℹ️ عملة غير معروفة: «{symbol}». جرّب bitcoin / ethereum / solana..."
        price = d[s]["usd"]
        chg = d[s].get("usd_24h_change", 0)
        arrow = "🟢▲" if chg >= 0 else "🔴▼"
        return f"💰 {symbol.capitalize()}: ${price:,} ({arrow} {chg:.2f}% خلال 24س)"
    except Exception as e:
        return f"❌ خطأ في جلب السعر: {e}"
