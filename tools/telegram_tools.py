"""
telegram_tools.py — Search Telegram groups/chats and download files (user account).

Uses Telethon (MTProto) with the USER's own account — unlike the bot integration,
this can search across all the user's groups/channels and download their files.

One-time setup (free):
  1. Get api_id + api_hash from https://my.telegram.org → API development tools.
  2. Put them in .env:  TELEGRAM_API_ID=...   TELEGRAM_API_HASH=...
  3. First run: telegram_login(phone='+9665...') → a code arrives in Telegram →
     telegram_verify_code(code='12345'). The session is saved to telegram_user.session
     so you never log in again.

Tools:
  • telegram_login(phone)               — start login (sends a code)
  • telegram_verify_code(code, password)— finish login (password = 2FA if enabled)
  • telegram_status()                   — am I logged in? which account?
  • telegram_list_chats(limit)          — list groups/channels/chats
  • telegram_search(query, chat, limit) — search messages (globally or in one chat)
  • telegram_search_files(query, file_type, chat, limit) — find documents/media
  • telegram_download(chat, message_id, dest) — download a file to the Desktop
"""
from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path
from typing import Annotated, Optional

from langchain_core.tools import tool

from config import DESKTOP_DIR

# ── credentials + session ─────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent
_SESSION = str(_ROOT / "telegram_user")  # Telethon appends .session

def _api_id() -> int:
    try:
        return int(os.getenv("TELEGRAM_API_ID", "0"))
    except (TypeError, ValueError):
        return 0

def _api_hash() -> str:
    return os.getenv("TELEGRAM_API_HASH", "").strip()


# ── async event loop bridge (sync tools → async Telethon) ─────────────────────
_loop: Optional[asyncio.AbstractEventLoop] = None
_loop_thread: Optional[threading.Thread] = None
_client = None  # Telethon TelegramClient (lives on _loop)
_lock = threading.Lock()


def _ensure_loop() -> asyncio.AbstractEventLoop:
    global _loop, _loop_thread
    if _loop is not None and _loop.is_running():
        return _loop
    started = threading.Event()

    def runner():
        global _loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _loop = loop
        started.set()
        loop.run_forever()

    _loop_thread = threading.Thread(target=runner, daemon=True, name="telegram-loop")
    _loop_thread.start()
    started.wait(timeout=5.0)
    assert _loop is not None
    return _loop


def _run(coro, timeout: int = 120):
    loop = _ensure_loop()
    fut = asyncio.run_coroutine_threadsafe(coro, loop)
    return fut.result(timeout=timeout)


async def _get_client():
    """Create (once) the Telethon client on the background loop. Does NOT log in."""
    global _client
    if _client is not None:
        return _client
    from telethon import TelegramClient
    if _api_id() == 0 or not _api_hash():
        raise RuntimeError(
            "TELEGRAM_API_ID / TELEGRAM_API_HASH غير مضبوطين في .env. "
            "احصل عليهما من https://my.telegram.org ثم أعد المحاولة."
        )
    _client = TelegramClient(_SESSION, _api_id(), _api_hash())
    await _client.connect()
    return _client


def _creds_missing_msg() -> str:
    return (
        "❌ بيانات Telegram API ناقصة.\n"
        "   1) افتح https://my.telegram.org → API development tools\n"
        "   2) أنشئ تطبيقاً واحصل على api_id و api_hash\n"
        "   3) أضِفهما إلى ملف .env:\n"
        "        TELEGRAM_API_ID=1234567\n"
        "        TELEGRAM_API_HASH=abcdef0123456789\n"
        "   4) ثم: telegram_login(phone='+9665XXXXXXXX')"
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  AUTH
# ═══════════════════════════════════════════════════════════════════════════════
@tool
def telegram_status() -> str:
    """التحقق من حالة تسجيل الدخول في Telegram وعرض الحساب النشط."""
    if _api_id() == 0 or not _api_hash():
        return _creds_missing_msg()

    async def _do():
        client = await _get_client()
        if await client.is_user_authorized():
            me = await client.get_me()
            name = " ".join(filter(None, [getattr(me, "first_name", ""), getattr(me, "last_name", "")]))
            return f"✅ مسجّل الدخول كـ «{name}» (@{getattr(me,'username',None) or '—'})."
        return "⚠️ غير مسجّل الدخول. استخدم telegram_login(phone='+9665...')."
    try:
        return _run(_do())
    except Exception as e:
        return f"❌ خطأ: {e}"


@tool
def telegram_login(
    phone: Annotated[str, "Your Telegram phone in international format, e.g. '+9665XXXXXXXX'."],
) -> str:
    """بدء تسجيل الدخول إلى Telegram بحسابك. يُرسل كود تحقق إلى تطبيق Telegram لديك.

    بعد وصول الكود، أكمل بـ telegram_verify_code(code='12345').
    """
    if _api_id() == 0 or not _api_hash():
        return _creds_missing_msg()

    async def _do():
        client = await _get_client()
        if await client.is_user_authorized():
            return "✅ أنت مسجّل الدخول بالفعل."
        sent = await client.send_code_request(phone)
        # remember phone + hash for the verify step
        globals()["_pending_phone"] = phone
        globals()["_pending_hash"] = sent.phone_code_hash
        return ("📲 أُرسل كود التحقق إلى تطبيق Telegram لديك.\n"
                "   أكمل بـ: telegram_verify_code(code='الكود')\n"
                "   إن كان لديك تحقق بخطوتين: telegram_verify_code(code='..', password='كلمة المرور').")
    try:
        return _run(_do())
    except Exception as e:
        return f"❌ خطأ في بدء الدخول: {e}"


@tool
def telegram_verify_code(
    code: Annotated[str, "The login code that arrived in your Telegram app."],
    password: Annotated[str, "Your 2FA password — only if two-step verification is enabled."] = "",
) -> str:
    """إكمال تسجيل الدخول بإدخال كود التحقق (وكلمة مرور التحقق بخطوتين إن وُجدت)."""

    async def _do():
        client = await _get_client()
        if await client.is_user_authorized():
            return "✅ مسجّل الدخول بالفعل."
        phone = globals().get("_pending_phone")
        phash = globals().get("_pending_hash")
        if not phone:
            return "❌ ابدأ بـ telegram_login(phone=...) أولاً."
        from telethon.errors import SessionPasswordNeededError
        try:
            await client.sign_in(phone=phone, code=code, phone_code_hash=phash)
        except SessionPasswordNeededError:
            if not password:
                return "🔐 الحساب محميّ بتحقق بخطوتين. أعد الاستدعاء مع password='كلمة المرور'."
            await client.sign_in(password=password)
        me = await client.get_me()
        return f"✅ تم تسجيل الدخول بنجاح كـ «{getattr(me,'first_name','')}». الجلسة محفوظة."
    try:
        return _run(_do())
    except Exception as e:
        return f"❌ فشل التحقق: {e}"


# ═══════════════════════════════════════════════════════════════════════════════
#  CHATS / SEARCH / DOWNLOAD
# ═══════════════════════════════════════════════════════════════════════════════
async def _require_auth(client) -> Optional[str]:
    if not await client.is_user_authorized():
        return "⚠️ غير مسجّل الدخول. استخدم telegram_login(phone='+9665...') أولاً."
    return None


@tool
def telegram_list_chats(limit: Annotated[int, "How many chats to list."] = 25) -> str:
    """عرض مجموعاتك وقنواتك ومحادثاتك في Telegram (الاسم + المعرّف + النوع)."""
    async def _do():
        client = await _get_client()
        err = await _require_auth(client)
        if err:
            return err
        lines = ["💬 محادثاتك في Telegram:"]
        async for dialog in client.iter_dialogs(limit=limit):
            kind = "قناة" if dialog.is_channel else ("مجموعة" if dialog.is_group else "خاص")
            lines.append(f"  • [{kind}] {dialog.name}  (id: {dialog.id})")
        return "\n".join(lines)
    try:
        return _run(_do())
    except Exception as e:
        return f"❌ خطأ: {e}"


@tool
def telegram_search(
    query: Annotated[str, "Text to search for in messages."],
    chat: Annotated[str, "Limit to one chat by name/username/id. Empty = search ALL your chats."] = "",
    limit: Annotated[int, "Max results."] = 20,
) -> str:
    """البحث عن رسائل في Telegram (في كل محادثاتك أو في مجموعة محددة).

    أمثلة:
      telegram_search(query='تطبيق المحاسبة')
      telegram_search(query='كتاب PDF', chat='مجموعة الكتب')
    """
    async def _do():
        client = await _get_client()
        err = await _require_auth(client)
        if err:
            return err
        results = []
        if chat:
            entity = await client.get_entity(chat)
            async for msg in client.iter_messages(entity, search=query, limit=limit):
                results.append((entity, msg))
        else:
            # global search across all dialogs
            async for msg in client.iter_messages(None, search=query, limit=limit):
                results.append((None, msg))
        if not results:
            return f"🔎 لا نتائج لـ «{query}»."
        lines = [f"🔎 نتائج البحث عن «{query}» ({len(results)}):"]
        for ent, msg in results:
            chat_name = ""
            try:
                ch = await msg.get_chat()
                chat_name = getattr(ch, "title", "") or getattr(ch, "first_name", "") or ""
            except Exception:
                pass
            has_file = "📎" if msg.media else "  "
            text = (msg.message or "").replace("\n", " ")[:90]
            lines.append(f"  {has_file} [{chat_name} | msg {msg.id}] {text}")
        lines.append("\n💡 لتنزيل ملف من نتيجة: telegram_download(chat='اسم المجموعة', message_id=رقم_msg)")
        return "\n".join(lines)
    try:
        return _run(_do(), timeout=180)
    except Exception as e:
        return f"❌ خطأ في البحث: {e}"


@tool
def telegram_search_files(
    query: Annotated[str, "Filename or keyword to find among shared files."],
    file_type: Annotated[str, "Filter: 'document'/'pdf'/'zip'/'apk'/'audio'/'video'/'photo'/'' (any)."] = "",
    chat: Annotated[str, "Limit to one chat. Empty = all your chats."] = "",
    limit: Annotated[int, "Max files to list."] = 20,
) -> str:
    """البحث عن ملفات/وسائط مُشاركة في Telegram حسب الاسم/النوع.

    يعرض الملفات المطابقة مع اسمها وحجمها والمجموعة ورقم الرسالة (للتنزيل لاحقاً).
    """
    async def _do():
        client = await _get_client()
        err = await _require_auth(client)
        if err:
            return err
        from telethon.tl.types import DocumentAttributeFilename
        ext = file_type.lower().lstrip(".")
        found = []
        targets = [await client.get_entity(chat)] if chat else None

        async def _scan(entity):
            async for msg in client.iter_messages(entity, search=query or "", limit=limit * 3):
                if not msg.media:
                    continue
                fname = ""
                if getattr(msg, "document", None):
                    for at in msg.document.attributes:
                        if isinstance(at, DocumentAttributeFilename):
                            fname = at.file_name
                size = getattr(getattr(msg, "document", None), "size", 0) or 0
                # type filter
                if ext and ext not in ("document",):
                    if ext not in (fname.lower() if fname else "") and ext not in (getattr(getattr(msg,'file',None),'ext','') or "").lower():
                        continue
                if query and fname and query.lower() not in fname.lower() and query.lower() not in (msg.message or "").lower():
                    continue
                ch = await msg.get_chat()
                cname = getattr(ch, "title", "") or getattr(ch, "first_name", "") or ""
                found.append((cname, msg.id, fname or "(بلا اسم)", size))
                if len(found) >= limit:
                    return True
            return False

        if targets:
            for t in targets:
                await _scan(t)
        else:
            async for dialog in client.iter_dialogs(limit=40):
                done = await _scan(dialog.entity)
                if len(found) >= limit:
                    break
        if not found:
            return f"🔎 لا ملفات مطابقة لـ «{query}»{' (' + file_type + ')' if file_type else ''}."
        lines = [f"📎 ملفات مطابقة ({len(found)}):"]
        for cname, mid, fname, size in found:
            mb = f"{size/1048576:.1f}م" if size else "?"
            lines.append(f"  • {fname} ({mb}) — [{cname} | msg {mid}]")
        lines.append("\n💡 للتنزيل: telegram_download(chat='اسم المجموعة', message_id=رقم)")
        return "\n".join(lines)
    try:
        return _run(_do(), timeout=240)
    except Exception as e:
        return f"❌ خطأ في البحث عن الملفات: {e}"


@tool
def telegram_download(
    chat: Annotated[str, "Chat name/username/id that contains the message."],
    message_id: Annotated[int, "The message id (shown as 'msg N' in search results)."],
    dest: Annotated[str, "Destination folder. Empty = Desktop."] = "",
) -> str:
    """تنزيل الملف/الوسائط من رسالة Telegram محددة إلى سطح المكتب (أو مجلد تختاره)."""
    async def _do():
        client = await _get_client()
        err = await _require_auth(client)
        if err:
            return err
        entity = await client.get_entity(chat)
        msg = await client.get_messages(entity, ids=int(message_id))
        if msg is None:
            return f"❌ لم أجد الرسالة {message_id} في «{chat}»."
        if not msg.media:
            return f"ℹ️ الرسالة {message_id} لا تحتوي ملفاً (نص فقط)."
        folder = Path(dest) if dest else Path(str(DESKTOP_DIR))
        folder.mkdir(parents=True, exist_ok=True)
        path = await client.download_media(msg, file=str(folder))
        if path:
            size = os.path.getsize(path) / 1048576
            return f"✅ تم التنزيل: {path} ({size:.1f} ميجابايت)"
        return "❌ تعذّر التنزيل."
    try:
        return _run(_do(), timeout=600)
    except Exception as e:
        return f"❌ خطأ في التنزيل: {e}"
