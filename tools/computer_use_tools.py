"""
computer_use_tools.py — High-level computer use tools.

Provides intelligent desktop control:
  • screen_describe()       — See what's on screen (OCR + window state)
  • app_interact()          — Smart click / type / scroll with auto-wait
  • open_app_and_login()    — Open any app/website and log in automatically
  • solve_text_captcha()    — Solve simple text/math CAPTCHAs via OCR
  • browser_interact_smart()— Smart browser actions with auto-wait + fallback

These tools replace manual sequences like:
  ❌ screenshot → OCR → find coords → click → wait → verify
  ✅ app_interact(action='click', target='Login')
"""
from __future__ import annotations

import re
import subprocess
import time

from langchain_core.tools import tool

# ── Dependency guards ─────────────────────────────────────────────────────────
try:
    import pyautogui
    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0.25
    _gui_ok = True
except ImportError:
    _gui_ok = False

# OCR: use the unified engine (native Windows OCR primary, tesseract fallback).
# This machine has NO tesseract.exe but IS Windows 11 with built-in OCR.
try:
    from tools.ocr_engine import (
        ocr_text as _engine_ocr_text,
        ocr_words as _engine_ocr_words,
        ocr_find as _engine_ocr_find,
        ocr_available as _engine_ocr_available,
    )
    _ocr_ok = _engine_ocr_available()
except Exception:
    _ocr_ok = False
    _engine_ocr_text = None
    _engine_ocr_words = None
    _engine_ocr_find = None

try:
    from PIL import Image  # noqa: F401 (used elsewhere)
except ImportError:
    pass

try:
    import pygetwindow as gw
    _win_ok = True
except ImportError:
    _win_ok = False


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _screenshot(region_str: str = ""):
    """Take screenshot, optionally cropped to region 'x,y,w,h'."""
    if not _gui_ok:
        return None
    if region_str:
        try:
            x, y, w, h = [int(v.strip()) for v in region_str.split(',')]
            return pyautogui.screenshot(region=(x, y, w, h))
        except Exception:
            pass
    return pyautogui.screenshot()


def _ocr_find(text_to_find: str, screenshot=None, confidence: int = 25):
    """Return (center_x, center_y) of first match for text_to_find, or None."""
    if not _gui_ok or _engine_ocr_find is None:
        return None
    try:
        if screenshot is None:
            screenshot = pyautogui.screenshot()
        return _engine_ocr_find(text_to_find, image=screenshot)
    except Exception:
        return None


def _engine_name_safe() -> str:
    """Return the active OCR engine name for diagnostics."""
    try:
        from tools.ocr_engine import ocr_engine_name
        return ocr_engine_name()
    except Exception:
        return "unknown"


def _ocr_words(screenshot=None) -> list:
    """Return word boxes [{'t','x','y','w','h'}, ...] from the screen."""
    if not _gui_ok or _engine_ocr_words is None:
        return []
    try:
        if screenshot is None:
            screenshot = pyautogui.screenshot()
        return _engine_ocr_words(screenshot)
    except Exception:
        return []


def _ocr_full_text(screenshot=None) -> str:
    """Return full OCR text of the screen (native Windows OCR)."""
    if not _gui_ok or _engine_ocr_text is None:
        return ""
    try:
        if screenshot is None:
            screenshot = pyautogui.screenshot()
        return _engine_ocr_text(screenshot)
    except Exception:
        return ""


def _wait_for_text(text: str, timeout: int = 10) -> bool:
    """Poll screen until text appears or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if text.lower() in _ocr_full_text().lower():
            return True
        time.sleep(0.8)
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Tool 1: screen_describe
# ─────────────────────────────────────────────────────────────────────────────
@tool
def screen_describe(region: str = "") -> str:
    """
    Capture the current screen and return everything visible on it:
    text content, approximate positions of buttons/fields/menus, and open windows.

    Use this BEFORE interacting with any app to understand the current state.

    Parameters:
    - region: leave empty for full screen, or "x,y,width,height" to zoom in

    Returns: Structured description with clickable elements and their coordinates.
    """
    if not _gui_ok:
        return "❌ pyautogui غير متاح"
    try:
        shot = _screenshot(region)
        if shot is None:
            return "❌ فشل أخذ لقطة الشاشة"

        sw, sh = pyautogui.size()
        lines = [f"📺 الشاشة: {sw}×{sh} بكسل"]

        # Active window + window-title-based verification detection
        active = ""
        if _win_ok:
            try:
                active = gw.getActiveWindowTitle() or "(لا يوجد)"
                all_titles = [t for t in gw.getAllTitles() if t.strip()][:6]
                lines.append(f"🪟 النافذة النشطة: «{active}»")
                if all_titles:
                    lines.append(f"   النوافذ المفتوحة: {' | '.join(all_titles)}")
            except Exception:
                pass

        # ── Title-based Cloudflare/verification detection (works WITHOUT OCR) ──
        _title_lower = (active or "").lower()
        _title_all = " ".join([active] + [t for t in (all_titles if _win_ok else [])]).lower() if _win_ok else _title_lower
        _cf_title_hit = any(kw in _title_all for kw in [
            'لحظة', 'just a moment', 'checking your browser', 'moment...',
            'verifying', 'cloudflare',
        ])
        if _cf_title_hit:
            lines.append(
                "\n🛡️ شاشة تحقق Cloudflare مكتشفة من عنوان النافذة («لحظة…»)\n"
                "   → استدعِ handle_verification_screen(timeout_seconds=90) لحلها."
            )

        # OCR full text via native Windows OCR engine
        if not _ocr_ok:
            lines.append(f"⚠️ OCR غير متاح ({ _engine_name_safe() }) — تعذر قراءة نصوص الشاشة")
            return "\n".join(lines)

        try:
            words = _ocr_words(shot)

            # Collect words with position (native OCR gives top-left x,y,w,h)
            elements = []
            for wd in words:
                word = str(wd.get('t', '')).strip()
                if not word:
                    continue
                cx = int(wd['x']) + int(wd['w']) // 2
                cy = int(wd['y']) + int(wd['h']) // 2
                elements.append({'text': word, 'x': cx, 'y': cy, 'conf': 100})

            if not elements:
                lines.append("\n⚠️ لا توجد نصوص مقروءة (تطبيق رسومي بدون نص واضح)")
            else:
                # Group into rows (words within 15px vertical distance)
                elements.sort(key=lambda e: (e['y'], e['x']))
                rows: list[list[dict]] = []
                cur: list[dict] = []
                last_y = -99
                for el in elements:
                    if abs(el['y'] - last_y) > 15 and cur:
                        rows.append(cur)
                        cur = []
                    cur.append(el)
                    last_y = el['y']
                if cur:
                    rows.append(cur)

                lines.append(f"\n🔤 النصوص المرئية ({len(elements)} كلمة في {len(rows)} سطر):")
                for row in rows[:30]:  # limit output
                    row_txt = "  ".join([f"'{e['text']}'@({e['x']},{e['y']})" for e in row])
                    lines.append(f"  {row_txt}")

                # Identify likely buttons (short, near center or bottom)
                buttons = [
                    e for e in elements
                    if len(e['text']) <= 25 and (
                        e['text'].istitle() or e['text'].isupper() or
                        e['text'].lower() in (
                            'ok', 'yes', 'no', 'cancel', 'login', 'sign in', 'log in',
                            'submit', 'continue', 'next', 'back', 'close', 'save',
                            'send', 'confirm', 'create', 'new', 'open', 'start', 'run',
                            'موافق', 'إلغاء', 'تسجيل', 'دخول', 'متابعة', 'التالي',
                            'حفظ', 'إرسال', 'تأكيد', 'إنشاء', 'فتح', 'تشغيل',
                        )
                    )
                ]
                if buttons:
                    lines.append(f"\n🔘 عناصر قابلة للنقر (أزرار محتملة):")
                    for b in buttons[:12]:
                        lines.append(f"   • '{b['text']}' → ({b['x']}, {b['y']})")

            lines.append("\n💡 للتفاعل: app_interact(action='click', target='النص') أو app_interact(action='type', text='...')")

            # ── CAPTCHA detection ──────────────────────────────────────
            all_text_lower = " ".join(e['text'] for e in elements).lower()
            captcha_keywords = [
                'captcha', 'recaptcha', 'verify', "i'm not a robot",
                "i am not a robot", 'robot', 'human', 'challenge',
                'prove', 'تحقق', 'لست روبوتاً', 'لست آلة', 'بشري',
            ]
            captcha_found = [kw for kw in captcha_keywords if kw in all_text_lower]
            if captcha_found:
                lines.append(
                    f"\n🔒 CAPTCHA_DETECTED — تم اكتشاف CAPTCHA على الشاشة!\n"
                    f"   الكلمات المكتشفة: {', '.join(captcha_found)}\n"
                    f"   الإجراء المطلوب: يرجى حل الـ CAPTCHA يدوياً، ثم أبلغني لأكمل المهمة.\n"
                    f"   أو للحل التلقائي (CAPTCHA نصي فقط): solve_text_captcha()"
                )

        except Exception as e:
            lines.append(f"⚠️ خطأ في OCR: {e}")

        return "\n".join(lines)

    except Exception as e:
        return f"❌ خطأ في screen_describe: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# Tool 2: app_interact
# ─────────────────────────────────────────────────────────────────────────────
@tool
def app_interact(
    action: str,
    target: str = "",
    text: str = "",
    wait_for: str = "",
    timeout_seconds: int = 10,
    confirm_text: str = "",
) -> str:
    """
    Smart desktop interaction: find an element on screen → wait → act → confirm.
    One tool replaces the entire screenshot→OCR→find→click→verify sequence.

    Actions:
    - "click"          → find 'target' text on screen and left-click it
    - "double_click"   → find 'target' and double-click
    - "right_click"    → find 'target' and right-click
    - "type"           → type 'text' at current cursor position
    - "click_and_type" → click 'target' field, then type 'text'
    - "clear_and_type" → Ctrl+A then type 'text' in current field
    - "press"          → press a key: Enter, Tab, Escape, F5, space, ...
    - "hotkey"         → keyboard shortcut: 'ctrl+c', 'ctrl+v', 'alt+f4', ...
    - "scroll_down"    → scroll down
    - "scroll_up"      → scroll up

    Parameters:
    - action: One of the actions above
    - target: Text to find on screen (for click/double_click/right_click/click_and_type)
    - text: Text to type or key(s) to press
    - wait_for: Optional — wait for this text to appear before acting
    - timeout_seconds: How long to wait (default 10s)
    - confirm_text: Optional — verify this text appears AFTER the action

    Returns: Success/failure with details
    """
    if not _gui_ok:
        return "❌ pyautogui غير متاح"

    try:
        # ── Optional: wait for screen text before acting ──────────────────
        if wait_for:
            if not _wait_for_text(wait_for, timeout_seconds):
                shot_text = _ocr_full_text()[:300]
                return (
                    f"⏰ انتهت المهلة ({timeout_seconds}ث) — لم يظهر '{wait_for}' على الشاشة\n"
                    f"النص المرئي حالياً: {shot_text}"
                )

        # ── Perform the action ─────────────────────────────────────────────
        result = ""

        if action in ("click", "double_click", "right_click"):
            if not target:
                return f"❌ '{action}' يحتاج 'target'"
            pos = _ocr_find(target)
            if pos is None:
                # Retry once with fresh screenshot
                time.sleep(0.5)
                pos = _ocr_find(target)
            if pos is None:
                return (
                    f"⚠️ لم أجد '{target}' على الشاشة.\n"
                    f"جرّب: screen_describe() لرؤية ما هو متاح للنقر."
                )
            time.sleep(0.1)
            if action == "click":
                pyautogui.click(*pos)
                result = f"✅ نقر على '{target}' في ({pos[0]}, {pos[1]})"
            elif action == "double_click":
                pyautogui.doubleClick(*pos)
                result = f"✅ نقر مزدوج على '{target}' في ({pos[0]}, {pos[1]})"
            elif action == "right_click":
                pyautogui.rightClick(*pos)
                result = f"✅ نقر يمين على '{target}' في ({pos[0]}, {pos[1]})"

        elif action == "type":
            if not text:
                return "❌ 'type' يحتاج 'text'"
            # Use clipboard for non-ASCII (Arabic, etc.) to avoid encoding issues
            if any(ord(c) > 127 for c in text):
                import pyperclip
                pyperclip.copy(text)
                pyautogui.hotkey('ctrl', 'v')
            else:
                pyautogui.write(text, interval=0.04)
            result = f"✅ كتابة: '{text[:60]}'" + ("..." if len(text) > 60 else "")

        elif action == "click_and_type":
            if target:
                pos = _ocr_find(target)
                if pos:
                    pyautogui.click(*pos)
                    time.sleep(0.3)
                else:
                    return f"⚠️ لم أجد حقل '{target}'"
            if text:
                if any(ord(c) > 127 for c in text):
                    import pyperclip
                    pyperclip.copy(text)
                    pyautogui.hotkey('ctrl', 'v')
                else:
                    pyautogui.write(text, interval=0.04)
            result = f"✅ نقر على '{target}' وكتابة '{text[:40]}'"

        elif action == "clear_and_type":
            pyautogui.hotkey('ctrl', 'a')
            time.sleep(0.15)
            if text:
                if any(ord(c) > 127 for c in text):
                    import pyperclip
                    pyperclip.copy(text)
                    pyautogui.hotkey('ctrl', 'v')
                else:
                    pyautogui.write(text, interval=0.04)
            result = f"✅ مسح الحقل وكتابة '{text[:40]}'"

        elif action == "press":
            key = (text or target).lower().strip()
            if not key:
                return "❌ 'press' يحتاج 'text' (مفتاح: enter, tab, escape, f5, space...)"
            pyautogui.press(key)
            result = f"✅ ضغط مفتاح: {key}"

        elif action == "hotkey":
            combo = (text or target).strip()
            if not combo:
                return "❌ 'hotkey' يحتاج 'text' (مثل: ctrl+c, ctrl+v, alt+f4)"
            keys = [k.strip() for k in combo.replace('+', ',').split(',')]
            pyautogui.hotkey(*keys)
            result = f"✅ اختصار: {combo}"

        elif action in ("scroll_down", "scroll_up"):
            amount = 5 if action == "scroll_down" else -5
            pyautogui.scroll(amount)
            result = f"✅ تمرير {'أسفل' if action == 'scroll_down' else 'أعلى'}"

        else:
            return (
                f"❌ إجراء غير معروف: '{action}'\n"
                "المتاح: click | double_click | right_click | type | click_and_type | "
                "clear_and_type | press | hotkey | scroll_down | scroll_up"
            )

        time.sleep(0.4)

        # ── Optional: confirm outcome ──────────────────────────────────────
        if confirm_text:
            time.sleep(1.2)
            if _wait_for_text(confirm_text, timeout=8):
                result += f"\n✅ تأكيد: ظهر '{confirm_text}' على الشاشة"
            else:
                result += f"\n⚠️ لم يظهر النص المتوقع '{confirm_text}' — تحقق يدوياً"

        return result

    except Exception as e:
        return f"❌ خطأ في app_interact: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# Tool 3: open_app_and_login
# ─────────────────────────────────────────────────────────────────────────────
@tool
def open_app_and_login(
    app_or_url: str,
    username: str = "",
    password: str = "",
    username_hint: str = "Email",
    password_hint: str = "Password",
    submit_hint: str = "Sign in",
    success_hint: str = "",
    timeout_seconds: int = 30,
) -> str:
    """
    Open any desktop app or website and log in automatically.

    Works for:
    - Desktop apps: "Replit", "Slack", "Discord", "VS Code", etc.
    - Web apps: "https://replit.com", "https://github.com", etc.

    The tool:
    1. Opens the app/URL
    2. Waits for the login form to appear
    3. Fills username and password via OCR-guided clicks
    4. Clicks the submit button (or presses Enter)
    5. Verifies successful login via 'success_hint' text
    6. Returns CAPTCHA_DETECTED if a CAPTCHA is blocking

    Parameters:
    - app_or_url: App name (e.g., "Replit") or URL (e.g., "https://replit.com")
    - username: Email or username to enter
    - password: Password to enter
    - username_hint: Text label near the username field (default: "Email")
    - password_hint: Text label near the password field (default: "Password")
    - submit_hint: Text on the login/submit button (default: "Sign in")
    - success_hint: Text that appears after successful login (e.g., "Dashboard")
    - timeout_seconds: Max wait time in seconds (default: 30)

    Returns: Step-by-step log of what happened, or CAPTCHA_DETECTED if needed.
    """
    if not _gui_ok:
        return "❌ pyautogui غير متاح"

    log = []

    try:
        # ── Step 1: Open the app/URL ───────────────────────────────────────
        is_url = app_or_url.startswith("http://") or app_or_url.startswith("https://")
        if is_url:
            subprocess.Popen(["cmd", "/c", "start", "", app_or_url], shell=False)
            log.append(f"✅ فتح الرابط: {app_or_url}")
        else:
            pyautogui.hotkey('win', 's')
            time.sleep(0.6)
            pyautogui.write(app_or_url, interval=0.08)
            time.sleep(1.0)
            pyautogui.press('enter')
            log.append(f"✅ فتح التطبيق: {app_or_url}")

        time.sleep(3)  # let the app/page load

        # ── Step 2: Find and fill username ────────────────────────────────
        if username and _ocr_ok:
            # Wait for the login form
            deadline = time.time() + timeout_seconds
            filled = False
            while time.time() < deadline and not filled:
                shot = pyautogui.screenshot()
                page_text = _ocr_full_text(shot).lower()

                # CAPTCHA detection (early)
                if any(w in page_text for w in ['captcha', 'recaptcha', 'i am not a robot', 'لست روبوتاً']):
                    log.append("🔒 تم اكتشاف CAPTCHA")
                    return "\n".join(log) + "\nCAPTCHA_DETECTED: يرجى حل الـ CAPTCHA يدوياً ثم اكتب 'استمر'"

                # Look for the username field
                pos = _ocr_find(username_hint, shot)
                if pos:
                    # Click slightly below the label (usually the input is below)
                    pyautogui.click(pos[0], pos[1] + 25)
                    time.sleep(0.4)
                    pyautogui.hotkey('ctrl', 'a')
                    # Use clipboard for safe Unicode input
                    try:
                        import pyperclip
                        pyperclip.copy(username)
                        pyautogui.hotkey('ctrl', 'v')
                    except ImportError:
                        pyautogui.write(username, interval=0.05)
                    filled = True
                    log.append(f"✅ إدخال اسم المستخدم '{username}' في حقل '{username_hint}'")
                time.sleep(0.8)

            if not filled:
                log.append(f"⚠️ لم أجد حقل '{username_hint}' — جاري المحاولة بـ Tab")
                pyautogui.hotkey('ctrl', 'a')
                try:
                    import pyperclip
                    pyperclip.copy(username)
                    pyautogui.hotkey('ctrl', 'v')
                except ImportError:
                    pyautogui.write(username, interval=0.05)

        # ── Step 3: Fill password ──────────────────────────────────────────
        if password:
            time.sleep(0.3)
            # Try to find password field, or just Tab to it
            if _ocr_ok:
                pos = _ocr_find(password_hint)
                if pos:
                    pyautogui.click(pos[0], pos[1] + 25)
                    time.sleep(0.3)
                else:
                    pyautogui.press('tab')
                    time.sleep(0.2)
            else:
                pyautogui.press('tab')
                time.sleep(0.2)

            try:
                import pyperclip
                pyperclip.copy(password)
                pyautogui.hotkey('ctrl', 'v')
            except ImportError:
                pyautogui.write(password, interval=0.05)
            log.append("✅ إدخال كلمة المرور")

        # ── Step 4: Submit ─────────────────────────────────────────────────
        time.sleep(0.4)
        button_found = False
        if _ocr_ok:
            pos = _ocr_find(submit_hint)
            if pos:
                pyautogui.click(*pos)
                button_found = True
                log.append(f"✅ نقر زر '{submit_hint}'")

        if not button_found:
            pyautogui.press('enter')
            log.append("✅ ضغط Enter للتسجيل")

        time.sleep(2)

        # ── Step 5: CAPTCHA check after submit ────────────────────────────
        if _ocr_ok:
            page_text = _ocr_full_text().lower()
            if any(w in page_text for w in ['captcha', 'recaptcha', 'i am not a robot', 'لست روبوتاً']):
                log.append("🔒 ظهر CAPTCHA بعد الإرسال")
                return "\n".join(log) + "\nCAPTCHA_DETECTED: يرجى حل الـ CAPTCHA يدوياً ثم اكتب 'استمر'"

        # ── Step 6: Verify success ─────────────────────────────────────────
        if success_hint:
            if _wait_for_text(success_hint, timeout=timeout_seconds):
                log.append(f"✅ تسجيل دخول ناجح — ظهر '{success_hint}'")
            else:
                current_text = _ocr_full_text()[:200]
                log.append(f"⚠️ انتهت المهلة — لم يظهر '{success_hint}'\nالشاشة الحالية: {current_text}")
        else:
            log.append("✅ تم إرسال بيانات الدخول — تحقق من الشاشة")

        return "\n".join(log)

    except Exception as e:
        return "\n".join(log) + f"\n❌ خطأ: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# Tool 4: solve_text_captcha
# ─────────────────────────────────────────────────────────────────────────────
@tool
def solve_text_captcha(region: str = "") -> str:
    """
    Read a CAPTCHA visible on screen and return the answer.

    Handles:
    - Text/number CAPTCHAs (e.g., "X8K3P2") → OCR reads the characters
    - Math CAPTCHAs (e.g., "5 + 7 = ?") → calculates the answer

    Does NOT work for:
    - Google reCAPTCHA (image grid) → needs manual solving
    - hCaptcha → needs manual solving

    Parameters:
    - region: Leave empty to scan full screen, or "x,y,width,height" to zoom into
              the specific CAPTCHA area (more accurate)

    Returns: The CAPTCHA answer to type, or instructions for manual solving.
    """
    if not _ocr_ok or not _gui_ok:
        return "❌ OCR/pyautogui غير متاح"

    try:
        shot = _screenshot(region)
        if shot is None:
            return "❌ فشل أخذ لقطة الشاشة"

        # Native OCR: get word boxes + full text, build candidates
        candidates = []
        try:
            full = _ocr_full_text(shot)
            for chunk in re.split(r'\s+', full):
                c = chunk.strip()
                if len(c) >= 3:
                    candidates.append(c)
            # Also the whole text collapsed (for math like "5 + 3")
            collapsed = re.sub(r'\s+', '', full)
            if len(collapsed) >= 3:
                candidates.append(collapsed)
        except Exception:
            pass

        if not candidates:
            return (
                "⚠️ OCR لم يتمكن من قراءة الـ CAPTCHA.\n"
                "نصيحة: مرّر الـ 'region' (x,y,width,height) لتضييق منطقة البحث\n"
                "أو قم بحل الـ CAPTCHA يدوياً."
            )

        best = max(candidates, key=len)

        # Check for math CAPTCHA  e.g. "5+3" or "12 - 4"
        math = re.search(r'(\d+)\s*([+\-×x*/÷])\s*(\d+)', best)
        if math:
            a, op, b = int(math.group(1)), math.group(2), int(math.group(3))
            if op == '+':
                answer = str(a + b)
            elif op == '-':
                answer = str(a - b)
            elif op in ('*', '×', 'x'):
                answer = str(a * b)
            elif op in ('/', '÷'):
                answer = str(a // b) if b != 0 else "0"
            else:
                answer = None
            if answer:
                return f"✅ CAPTCHA رياضي: {best!r} → الجواب: {answer}"

        return (
            f"✅ CAPTCHA مقروء: «{best}»\n"
            "اكتب هذا النص في حقل الـ CAPTCHA باستخدام:\n"
            f"  app_interact(action='click_and_type', target='CAPTCHA', text='{best}')"
        )

    except Exception as e:
        return f"❌ خطأ في solve_text_captcha: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# Tool 5: type_text_clipboard (reliable Unicode typing)
# ─────────────────────────────────────────────────────────────────────────────
@tool
def type_text_clipboard(text: str, clear_first: bool = False) -> str:
    """
    Type any text (Arabic or English) into the currently focused field
    using the clipboard. More reliable than keyboard_type for non-ASCII text.

    Parameters:
    - text: Text to type (supports Arabic, Emoji, special characters)
    - clear_first: If True, press Ctrl+A before pasting to replace existing text

    Returns: Success message
    """
    if not _gui_ok:
        return "❌ pyautogui غير متاح"
    try:
        import pyperclip
        old_clipboard = ""
        try:
            old_clipboard = pyperclip.paste()
        except Exception:
            pass

        pyperclip.copy(text)
        time.sleep(0.1)

        if clear_first:
            pyautogui.hotkey('ctrl', 'a')
            time.sleep(0.1)

        pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.2)

        preview = text[:60] + ("..." if len(text) > 60 else "")
        return f"✅ تم لصق النص: «{preview}»"

    except ImportError:
        # Fallback: pyautogui direct typing (less reliable for Arabic)
        try:
            if clear_first:
                pyautogui.hotkey('ctrl', 'a')
                time.sleep(0.1)
            pyautogui.write(text, interval=0.04)
            return f"✅ تم كتابة النص: «{text[:60]}»"
        except Exception as e2:
            return f"❌ خطأ: {e2}"
    except Exception as e:
        return f"❌ خطأ في type_text_clipboard: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# Tool 6: handle_verification_screen
# ─────────────────────────────────────────────────────────────────────────────
@tool
def handle_verification_screen(
    timeout_seconds: int = 25,
    captcha_region: str = "",
) -> str:
    """
    Detect and handle ANY verification/CAPTCHA screen automatically.

    Handles all common types:
    ✅ Cloudflare "Just a moment..." / "لحظة..."  → waits for auto-resolve (most common)
    ✅ Cloudflare "Verify you are human" checkbox → clicks it automatically
    ✅ Simple text/number CAPTCHA (e.g. "X8K3") → reads with OCR and types answer
    ✅ Math CAPTCHA (e.g. "3 + 7 = ?")           → calculates and types answer
    ✅ "I am not a robot" checkbox                → clicks it
    ⚠️ Google reCAPTCHA image grid               → reports to user (needs manual)
    ⚠️ hCaptcha image challenges                 → reports to user (needs manual)
    ⚠️ Email/SMS verification code               → reports to user

    Call this after opening any app or website if you see:
    - "Just a moment" / "لحظة" in the window title or screen
    - CAPTCHA_DETECTED in a previous tool result
    - The screen is stuck on a verification page

    Parameters:
    - timeout_seconds: How long to wait for auto-resolve (default 25s)
    - captcha_region: "x,y,w,h" to focus on a specific screen area

    Returns: Result of the verification attempt + screenshot description.
    """
    if not _gui_ok:
        return "❌ pyautogui غير متاح"

    try:
        log = []
        log.append("🔍 فحص شاشة التحقق...")

        # ── Step 1: Take initial screenshot and analyze ────────────────────
        shot = _screenshot(captcha_region)
        if shot is None:
            return "❌ فشل أخذ لقطة الشاشة"

        screen_text = _ocr_full_text(shot).lower()
        if not screen_text.strip():
            # Wait a moment and try again
            time.sleep(2)
            shot = _screenshot(captcha_region)
            screen_text = _ocr_full_text(shot).lower()

        # ── Window-title signal (reliable even when OCR is empty) ───────────
        _win_title = ""
        _win_titles_all = ""
        if _win_ok:
            try:
                _win_title = (gw.getActiveWindowTitle() or "").lower()
                _win_titles_all = " ".join(
                    t for t in gw.getAllTitles() if t.strip()
                ).lower()
            except Exception:
                pass
        # Combined detection surface: OCR text + window titles
        _detect_surface = f"{screen_text} {_win_title} {_win_titles_all}"

        # ── Detect verification type (OCR text OR window title) ─────────────
        is_cloudflare = any(kw in _detect_surface for kw in [
            'just a moment', 'لحظة', 'checking your browser',
            'please wait', 'ddos', 'cloudflare', 'ray id', 'moment...',
            'verifying',
        ])
        is_checkbox = any(kw in screen_text for kw in [
            "i'm not a robot", "i am not a robot", "verify you are human",
            "لست روبوتاً", "تحقق", "أنا لست روبوتاً",
        ])
        is_recaptcha = 'recaptcha' in screen_text
        is_hcaptcha  = 'hcaptcha' in screen_text
        is_email_verify = any(kw in screen_text for kw in [
            'verification code', 'enter code', 'check your email',
            'verify your email', 'رمز التحقق', 'تحقق من بريدك',
        ])
        is_text_captcha = any(kw in screen_text for kw in [
            'enter the characters', 'type the letters', 'captcha',
            'أدخل الأحرف', 'اكتب الكود',
        ])

        log.append(f"📋 ما تم اكتشافه على الشاشة:")
        if is_cloudflare:   log.append("   🛡️ Cloudflare 'Just a moment...' verification")
        if is_checkbox:     log.append("   ☑️ 'I am not a robot' checkbox")
        if is_recaptcha:    log.append("   🔒 Google reCAPTCHA")
        if is_hcaptcha:     log.append("   🔒 hCaptcha")
        if is_email_verify: log.append("   📧 Email/SMS verification")
        if is_text_captcha: log.append("   🔤 Text CAPTCHA")
        if not any([is_cloudflare, is_checkbox, is_recaptcha, is_hcaptcha,
                    is_email_verify, is_text_captcha]):
            log.append("   ℹ️ لم يُكتشف نوع محدد — سيتم الانتظار والمحاولة")

        # ══════════════════════════════════════════════════════════════════
        # CASE 1: Cloudflare "Just a moment" — wait for auto-resolve
        # ══════════════════════════════════════════════════════════════════
        if is_cloudflare:
            log.append(f"⏳ Cloudflare — انتظار حل تلقائي (حد أقصى {timeout_seconds}ث)...")

            # ── CRITICAL: Focus window so Cloudflare JS runs ───────────────
            # Cloudflare Turnstile requires the window to be in the FOREGROUND
            # for its JavaScript challenge to complete automatically.
            if _win_ok:
                try:
                    import pygetwindow as _gw2
                    _cf_kws = ['moment', 'لحظة', 'just a moment', 'cloudflare',
                               'replit', 'checking']
                    all_wins = _gw2.getAllWindows()
                    cf_win = next(
                        (w for w in all_wins
                         if any(kw in w.title.lower() for kw in _cf_kws)
                         and w.visible),
                        None
                    )
                    if cf_win:
                        cf_win.activate()
                        time.sleep(0.6)
                        # Click center to ensure the window receives input events
                        import pyautogui as _pa0
                        _pa0.click(cf_win.centerx, cf_win.centery)
                        time.sleep(0.4)
                        log.append(f"🎯 تم تركيز النافذة: «{cf_win.title}» + نقرة تفعيل")
                    else:
                        log.append("⚠️ لم يُعثر على نافذة Cloudflare للتركيز عليها")
                except Exception as _fe:
                    log.append(f"⚠️ خطأ في التركيز: {_fe}")

            deadline = time.time() + timeout_seconds
            resolved = False
            _click_attempts = 0
            while time.time() < deadline:
                time.sleep(2)
                current_text = _ocr_full_text().lower()
                still_cloudflare = any(kw in current_text for kw in [
                    'just a moment', 'لحظة', 'checking your browser', 'please wait',
                ])
                # Also check window title
                if _win_ok:
                    try:
                        import pygetwindow as _gw
                        title = (_gw.getActiveWindowTitle() or "").lower()
                        still_cloudflare = still_cloudflare or ('moment' in title or 'لحظة' in title)
                    except Exception:
                        pass

                if not still_cloudflare:
                    resolved = True
                    log.append("✅ Cloudflare تم تجاوزه تلقائياً!")
                    break

                # Re-focus window every 10s to keep it active
                _click_attempts += 1
                if _click_attempts % 5 == 0 and _win_ok:
                    try:
                        import pygetwindow as _gw3
                        _cf_kws2 = ['moment', 'لحظة', 'replit', 'checking']
                        _w = next((w for w in _gw3.getAllWindows()
                                   if any(kw in w.title.lower() for kw in _cf_kws2)
                                   and w.visible), None)
                        if _w:
                            _w.activate()
                            import pyautogui as _pa2
                            _pa2.click(_w.centerx, _w.centery)
                            log.append(f"♻️ إعادة تركيز النافذة... ({int(deadline-time.time())}ث متبقية)")
                    except Exception:
                        pass

                # Check if a checkbox appeared
                if any(kw in current_text for kw in ["i'm not a robot", "verify", "تحقق"]):
                    log.append("☑️ ظهر checkbox — سيتم النقر عليه...")
                    pos = _ocr_find("Verify") or _ocr_find("verify") or _ocr_find("تحقق")
                    if pos:
                        import pyautogui as _pa
                        _pa.click(*pos)
                        time.sleep(2)
                        log.append(f"🖱️ نقر على checkbox عند {pos}")
                        resolved = True
                        break

            if not resolved:
                log.append(f"⚠️ Cloudflare لم يُحل تلقائياً بعد {timeout_seconds}ث")
                log.append("💡 جرّب: انتظر أكثر أو حل يدوياً")

        # ══════════════════════════════════════════════════════════════════
        # CASE 2: Checkbox "I am not a robot"
        # ══════════════════════════════════════════════════════════════════
        elif is_checkbox:
            log.append("☑️ محاولة النقر على checkbox 'I am not a robot'...")
            click_targets = [
                "I'm not a robot", "I am not a robot", "Verify",
                "لست روبوتاً", "تحقق", "أنا لست روبوتاً",
            ]
            clicked = False
            for target in click_targets:
                pos = _ocr_find(target)
                if pos:
                    import pyautogui as _pa
                    _pa.click(*pos)
                    time.sleep(2.5)
                    log.append(f"✅ نقر على '{target}' في {pos}")
                    clicked = True
                    break

            if not clicked:
                # Try clicking center of screen (where checkbox often is)
                import pyautogui as _pa
                sw, sh = _pa.size()
                _pa.click(sw // 2, sh // 2)
                time.sleep(2)
                log.append("🖱️ نقر في مركز الشاشة (checkbox قد يكون هناك)")

        # ══════════════════════════════════════════════════════════════════
        # CASE 3: reCAPTCHA / hCaptcha (image challenges)
        # ══════════════════════════════════════════════════════════════════
        elif is_recaptcha or is_hcaptcha:
            captcha_name = "Google reCAPTCHA" if is_recaptcha else "hCaptcha"
            log.append(f"🔒 {captcha_name} مكتشف — يتطلب حلاً يدوياً")
            log.append("📋 التعليمات:")
            log.append("   1. انقر على الصور المطلوبة في نافذة CAPTCHA")
            log.append("   2. بعد النجاح، أبلغني بكلمة 'استمر' أو 'تم'")
            return "\n".join(log) + "\nCAPTCHA_MANUAL_REQUIRED: يرجى حل reCAPTCHA يدوياً"

        # ══════════════════════════════════════════════════════════════════
        # CASE 4: Email/SMS verification code
        # ══════════════════════════════════════════════════════════════════
        elif is_email_verify:
            log.append("📧 تحقق عبر البريد/الهاتف مطلوب")
            log.append("📋 التعليمات:")
            log.append("   1. افتح بريدك الإلكتروني أو الرسائل")
            log.append("   2. انسخ رمز التحقق")
            log.append("   3. أبلغني بالرمز وسأدخله تلقائياً")
            return "\n".join(log) + "\nVERIFICATION_CODE_NEEDED: أرسل لي رمز التحقق"

        # ══════════════════════════════════════════════════════════════════
        # CASE 5: Text/Math CAPTCHA
        # ══════════════════════════════════════════════════════════════════
        elif is_text_captcha:
            log.append("🔤 محاولة حل CAPTCHA نصي بـ OCR...")
            captcha_result = solve_text_captcha.invoke(
                {"region": captcha_region} if captcha_region else {}
            )
            log.append(f"📖 نتيجة OCR: {captcha_result}")
            if "✅" in captcha_result:
                answer = captcha_result.split(":")[-1].strip().split("\n")[0].strip()
                if answer:
                    import pyautogui as _pa
                    _pa.hotkey('ctrl', 'a')
                    time.sleep(0.1)
                    try:
                        import pyperclip
                        pyperclip.copy(answer)
                        _pa.hotkey('ctrl', 'v')
                    except ImportError:
                        _pa.write(answer, interval=0.05)
                    time.sleep(0.5)
                    _pa.press('enter')
                    log.append(f"✅ تم إدخال الحل: '{answer}'")

        # ══════════════════════════════════════════════════════════════════
        # CASE 6: Unknown — wait and check again
        # ══════════════════════════════════════════════════════════════════
        else:
            log.append("⏳ نوع التحقق غير محدد — انتظار 5 ثوانٍ...")
            time.sleep(5)

        # ── Final verification screenshot ──────────────────────────────────
        time.sleep(1.5)
        shot_after = _screenshot()
        text_after = _ocr_full_text(shot_after)
        text_after_l = text_after.lower()

        # Get current window title FIRST — it's the most reliable signal
        if _win_ok:
            try:
                import pygetwindow as _gw
                active_title = _gw.getActiveWindowTitle() or ""
                all_titles_l = " ".join(
                    t for t in _gw.getAllTitles() if t.strip()
                ).lower()
            except Exception:
                active_title = ""
                all_titles_l = ""
        else:
            active_title = ""
            all_titles_l = ""

        _stuck_keywords = [
            'just a moment', 'لحظة', 'captcha', 'recaptcha', 'hcaptcha',
            'verify you are human', "i'm not a robot", 'checking your browser',
        ]
        # CRITICAL: check BOTH OCR text AND window title (title works even if OCR fails)
        stuck_by_text  = any(kw in text_after_l for kw in _stuck_keywords)
        stuck_by_title = any(kw in active_title.lower() for kw in _stuck_keywords)
        stuck_by_anytitle = any(kw in all_titles_l for kw in _stuck_keywords)
        still_stuck = stuck_by_text or stuck_by_title or stuck_by_anytitle

        # Screen description (native OCR — no tesseract dependency)
        if text_after.strip():
            clean = "\n".join(l for l in text_after.splitlines() if l.strip())[:500]
        else:
            clean = f"(لم يُقرأ نص — محرك OCR: {_engine_name_safe()})"

        log.append(f"\n📸 لقطة ما بعد التحقق:")
        log.append(f"   النافذة: «{active_title}»")
        log.append(f"   الشاشة:\n{clean}")

        if still_stuck:
            reason = []
            if stuck_by_title or stuck_by_anytitle:
                reason.append("عنوان النافذة لا يزال «لحظة…»/Cloudflare")
            if stuck_by_text:
                reason.append("نص التحقق ظاهر على الشاشة")
            log.append(
                f"\n⚠️ لا يزال التحقق قائماً ({' + '.join(reason)})."
                f"\n   CAPTCHA_MANUAL_REQUIRED — قد يحتاج تدخلاً يدوياً، "
                f"أو أعد المحاولة بـ handle_verification_screen(timeout_seconds=90)."
            )
        else:
            log.append("\n✅ تم تجاوز شاشة التحقق بنجاح! العنوان لم يعد يحتوي إشارات تحقق.")

        return "\n".join(log)

    except Exception as e:
        return f"❌ خطأ في handle_verification_screen: {e}"
