"""
Browser tools — Playwright with a persistent profile.

Why persistent context (not headless launch):
  - Cookies and logged-in sessions survive between agent runs (Gmail, banking,
    GitHub, etc. won't ask for 2FA on every task).
  - The profile is stored under .browser_profile/ inside the project dir.

Headful by default — the user wants to SEE the agent driving the browser.
Set BROWSER_HEADLESS=true in .env to flip.

The browser is a process-wide singleton (one window across the whole agent run).
Closing happens at agent shutdown via close_browser().
"""

from __future__ import annotations

import asyncio
import json as _json
import threading
from typing import Annotated, Optional

from langchain_core.tools import tool

from config import BROWSER_HEADLESS, BROWSER_USER_DATA_DIR, DOWNLOADS_DIR

# ── Module-level singletons ──────────────────────────────────────────────────
_loop: Optional[asyncio.AbstractEventLoop] = None
_loop_thread: Optional[threading.Thread] = None
_browser = None  # playwright BrowserContext (persistent)
_page = None  # active Page
_playwright = None
_init_lock = threading.Lock()


def _ensure_loop() -> asyncio.AbstractEventLoop:
    """
    Run an asyncio loop in a background thread so sync tools can call async
    Playwright APIs via asyncio.run_coroutine_threadsafe.
    """
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

    _loop_thread = threading.Thread(target=runner, daemon=True, name="playwright-loop")
    _loop_thread.start()
    started.wait(timeout=5.0)
    assert _loop is not None
    return _loop


def _run(coro):
    """Submit a coroutine to the background loop and wait for the result."""
    loop = _ensure_loop()
    fut = asyncio.run_coroutine_threadsafe(coro, loop)
    return fut.result(timeout=120)


async def _ensure_browser():
    global _browser, _page, _playwright
    if _page is not None and not _page.is_closed():
        return
    if _playwright is None:
        from playwright.async_api import async_playwright

        _playwright = await async_playwright().start()
    if _browser is None:
        BROWSER_USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
        DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
        _browser = await _playwright.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_USER_DATA_DIR),
            headless=BROWSER_HEADLESS,
            accept_downloads=True,
            viewport={"width": 1280, "height": 800},
            args=["--start-maximized"],
        )
    if not _browser.pages:
        _page = await _browser.new_page()
    else:
        _page = _browser.pages[0]


@tool
def browser_open(
    url: Annotated[str, "Full URL including http(s)://"],
) -> str:
    """Open a URL in the persistent browser. The same window is reused across calls."""
    with _init_lock:

        async def _do():
            await _ensure_browser()
            await _page.goto(url, wait_until="domcontentloaded", timeout=45000)
            return _page.url

        try:
            final_url = _run(_do())
            return f"[OK] Loaded {final_url}"
        except Exception as exc:
            return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def browser_get_text(
    selector: Annotated[
        str, "CSS selector. Use 'body' for the whole page text."
    ] = "body",
    max_chars: Annotated[int, "Cap returned text length."] = 6000,
) -> str:
    """Read visible text from the current page (or a specific element)."""

    async def _do():
        await _ensure_browser()
        try:
            text = await _page.inner_text(selector, timeout=10000)
        except Exception:
            text = await _page.content()
        return text

    try:
        text = _run(_do())
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"
    if len(text) > max_chars:
        return text[:max_chars] + f"\n\n...[truncated, total={len(text)} chars]"
    return text


@tool
def browser_click(
    selector: Annotated[str, "CSS or text= selector for the element to click."],
) -> str:
    """Click a button or link by selector. Use 'text=Submit' for text matching."""

    async def _do():
        await _ensure_browser()
        await _page.click(selector, timeout=15000)
        await _page.wait_for_load_state("domcontentloaded", timeout=15000)
        return _page.url

    try:
        url = _run(_do())
        return f"[OK] Clicked '{selector}'. Now at: {url}"
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def browser_fill(
    selector: Annotated[str, "CSS selector for an input."],
    value: Annotated[str, "Value to type."],
) -> str:
    """Fill an input or textarea."""

    async def _do():
        await _ensure_browser()
        await _page.fill(selector, value, timeout=15000)

    try:
        _run(_do())
        return f"[OK] Filled '{selector}'"
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def browser_press(
    key: Annotated[str, "Key to press, e.g. 'Enter', 'Escape', 'Tab', 'Control+a'."],
) -> str:
    """Send a single keystroke to the page."""

    async def _do():
        await _ensure_browser()
        await _page.keyboard.press(key)

    try:
        _run(_do())
        return f"[OK] Pressed {key}"
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def browser_screenshot(
    path: Annotated[
        str, "Where to save the PNG. Defaults to <Desktop>/agent_screenshot.png"
    ] = "",
    full_page: Annotated[bool, "Capture full scrollable page."] = False,
) -> str:
    """Save a screenshot of the current browser page."""
    from pathlib import Path

    from config import DESKTOP_DIR

    target = Path(path) if path else DESKTOP_DIR / "agent_screenshot.png"
    target.parent.mkdir(parents=True, exist_ok=True)

    async def _do():
        await _ensure_browser()
        await _page.screenshot(path=str(target), full_page=full_page)

    try:
        _run(_do())
        return f"[OK] Saved screenshot -> {target}"
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def browser_download_via_click(
    selector: Annotated[str, "Selector for the download button/link."],
    filename: Annotated[str, "Optional filename. Defaults to server-suggested name."] = "",
) -> str:
    """
    Click an element that triggers a file download, save to Downloads folder.
    Use this when the file isn't available as a direct URL (e.g. requires auth).
    """

    async def _do():
        await _ensure_browser()
        async with _page.expect_download(timeout=60000) as dl_info:
            await _page.click(selector)
        download = await dl_info.value
        suggested = download.suggested_filename
        target = DOWNLOADS_DIR / (filename or suggested)
        await download.save_as(str(target))
        return str(target)

    try:
        path = _run(_do())
        return f"[OK] Downloaded -> {path}"
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def browser_eval_js(
    expression: Annotated[str, "JavaScript expression to evaluate in the page context."],
) -> str:
    """Execute JS in the page and return the JSON-serializable result."""

    async def _do():
        await _ensure_browser()
        return await _page.evaluate(expression)

    try:
        result = _run(_do())
        return f"[OK] {result!r}"
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def browser_wait_for(
    selector: Annotated[str, "Selector that must appear before continuing."],
    timeout_ms: Annotated[int, "Max wait in milliseconds."] = 15000,
) -> str:
    """Wait for an element to appear in the DOM."""

    async def _do():
        await _ensure_browser()
        await _page.wait_for_selector(selector, timeout=timeout_ms)

    try:
        _run(_do())
        return f"[OK] Found '{selector}'"
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def browser_new_tab(
    url: Annotated[str, "URL to open in the new tab. Use 'about:blank' for empty."] = "about:blank",
) -> str:
    """Open a new browser tab and navigate to a URL. The new tab becomes the active page."""
    global _page

    async def _do():
        global _page
        await _ensure_browser()
        _page = await _browser.new_page()
        if url and url != "about:blank":
            await _page.goto(url, wait_until="domcontentloaded", timeout=45000)
        return f"tab_count={len(_browser.pages)}, url={_page.url}"

    try:
        info = _run(_do())
        return f"[OK] New tab opened. {info}"
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def browser_switch_tab(
    index: Annotated[int, "Tab index (0-based). Use -1 for last tab."] = -1,
) -> str:
    """Switch to a different browser tab by index."""
    global _page

    async def _do():
        global _page
        await _ensure_browser()
        pages = _browser.pages
        if not pages:
            return "[ERROR] No tabs open"
        idx = index if index >= 0 else len(pages) + index
        if idx < 0 or idx >= len(pages):
            return f"[ERROR] Tab index {index} out of range (0-{len(pages)-1})"
        _page = pages[idx]
        await _page.bring_to_front()
        return f"[OK] Switched to tab {idx}: {_page.url}"

    try:
        return _run(_do())
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def browser_list_tabs() -> str:
    """List all open browser tabs with their index and URL."""

    async def _do():
        await _ensure_browser()
        pages = _browser.pages
        if not pages:
            return "(no tabs open)"
        lines = []
        for i, p in enumerate(pages):
            active = " (active)" if p == _page else ""
            lines.append(f"  [{i}] {p.url}{active}")
        return f"{len(pages)} tab(s):\n" + "\n".join(lines)

    try:
        return _run(_do())
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def browser_close_tab(
    index: Annotated[int, "Tab index to close. Use -1 for current tab."] = -1,
) -> str:
    """Close a specific browser tab."""
    global _page

    async def _do():
        global _page
        await _ensure_browser()
        pages = _browser.pages
        if not pages:
            return "[ERROR] No tabs to close"
        idx = index if index >= 0 else pages.index(_page) if _page in pages else len(pages) - 1
        if idx < 0 or idx >= len(pages):
            return f"[ERROR] Tab index {index} out of range"
        await pages[idx].close()
        remaining = _browser.pages
        if remaining:
            _page = remaining[min(idx, len(remaining) - 1)]
        else:
            _page = await _browser.new_page()
        return f"[OK] Closed tab {idx}. Now on: {_page.url}"

    try:
        return _run(_do())
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def browser_login(
    url: Annotated[str, "Login page URL."],
    username: Annotated[str, "Username or email to enter."],
    password: Annotated[str, "Password to enter."],
    username_selector: Annotated[str, "CSS selector for username field."] = "input[type='email'], input[type='text'], input[name='username'], input[name='email'], #username, #email",
    password_selector: Annotated[str, "CSS selector for password field."] = "input[type='password'], #password",
    submit_selector: Annotated[str, "CSS selector for submit button."] = "button[type='submit'], input[type='submit'], button:has-text('Sign in'), button:has-text('Log in'), button:has-text('تسجيل الدخول')",
) -> str:
    """
    Automate login to a website. Navigate to the URL, fill credentials, and submit.
    The persistent browser profile keeps the session alive across agent runs.
    """

    async def _do():
        await _ensure_browser()
        await _page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await _page.wait_for_timeout(1500)

        # Fill username
        user_el = await _page.query_selector(username_selector)
        if not user_el:
            return "[ERROR] Could not find username field. Try a more specific selector."
        await user_el.click()
        await user_el.fill(username)
        await _page.wait_for_timeout(500)

        # Fill password
        pass_el = await _page.query_selector(password_selector)
        if not pass_el:
            return "[ERROR] Could not find password field. Try a more specific selector."
        await pass_el.click()
        await pass_el.fill(password)
        await _page.wait_for_timeout(500)

        # Submit
        submit_el = await _page.query_selector(submit_selector)
        if submit_el:
            await submit_el.click()
        else:
            await _page.keyboard.press("Enter")

        await _page.wait_for_load_state("domcontentloaded", timeout=30000)
        await _page.wait_for_timeout(2000)
        return f"[OK] Login submitted. Now at: {_page.url}"

    try:
        return _run(_do())
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def browser_download_to_desktop(
    url: Annotated[str, "Direct URL of the file to download."],
    filename: Annotated[str, "Filename to save as. Leave empty for server-suggested name."] = "",
) -> str:
    """
    Download a file through the browser (handles auth cookies, sessions, etc.)
    and save it to the Desktop. Use this when a direct httpx download would fail
    because the site requires a logged-in session.
    """
    from config import DESKTOP_DIR as _DESKTOP

    async def _do():
        await _ensure_browser()
        download_page = await _browser.new_page()
        try:
            async with download_page.expect_download(timeout=120000) as dl_info:
                await download_page.goto(url)
            download = await dl_info.value
            suggested = download.suggested_filename
            target = _DESKTOP / (filename or suggested)
            target.parent.mkdir(parents=True, exist_ok=True)
            await download.save_as(str(target))
            return f"[OK] Downloaded -> {target}"
        finally:
            await download_page.close()

    try:
        return _run(_do())
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def browser_get_cookies(
    domain: Annotated[str, "Domain filter (e.g. 'google.com'). Empty for all."] = "",
) -> str:
    """List browser cookies, optionally filtered by domain. Useful for debugging login issues."""

    async def _do():
        await _ensure_browser()
        cookies = await _browser.cookies()
        if domain:
            cookies = [c for c in cookies if domain.lower() in c.get("domain", "").lower()]
        if not cookies:
            return "(no cookies found)"
        lines = []
        for c in cookies[:50]:
            lines.append(f"  {c.get('domain', '?')} | {c.get('name', '?')} = {str(c.get('value', ''))[:40]}...")
        return f"{len(cookies)} cookie(s):\n" + "\n".join(lines)

    try:
        return _run(_do())
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def browser_react_fill(
    selector: Annotated[str, "CSS selector for the input element."],
    value: Annotated[str, "Value to set in the input."],
) -> str:
    """
    Fill a React / Vue / Angular controlled input using React's internal setter.

    Use this as a fallback when browser_fill does NOT trigger SPA state updates
    (e.g. Replit, GitHub, Google — any site built with a modern JS framework
    where the input stays empty or the form validation doesn't activate).

    Internally this:
      1. Uses the native HTMLInputElement value setter (bypasses React read-only guard)
      2. Dispatches 'input' and 'change' events with bubbles=true
         (React's synthetic event system listens to these)
      3. Falls back to Playwright's fill() if the JS injection fails
    """

    async def _do():
        await _ensure_browser()

        # Primary: React-aware value setter + synthetic events
        js = f"""
        (function() {{
            var sel = {_json.dumps(selector)};
            var val = {_json.dumps(value)};
            var el  = document.querySelector(sel);
            if (!el) return 'ELEMENT_NOT_FOUND:' + sel;

            // 1. Set value via the native setter so React's fiber sees the change
            var nativeSetter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value'
            ).set;
            nativeSetter.call(el, val);

            // 2. Trigger events React listens to
            el.dispatchEvent(new Event('input',  {{bubbles: true, cancelable: true}}));
            el.dispatchEvent(new Event('change', {{bubbles: true, cancelable: true}}));
            el.dispatchEvent(new KeyboardEvent('keyup', {{bubbles: true}}));

            return 'OK:' + val.length + ' chars set';
        }})()
        """
        result = await _page.evaluate(js)
        if result and result.startswith("ELEMENT_NOT_FOUND"):
            raise ValueError(result)

        # 3. Playwright focus to make sure cursor is in the field
        try:
            await _page.focus(selector, timeout=3000)
        except Exception:
            pass  # Non-fatal if element already focused

        return result

    try:
        res = _run(_do())
        return f"[OK] React-filled '{selector}': {res}"
    except Exception as exc:
        # Final fallback: standard Playwright fill
        try:
            async def _fallback():
                await _ensure_browser()
                await _page.fill(selector, value, timeout=10000)
            _run(_fallback())
            return f"[OK] Filled '{selector}' via fallback (playwright fill)"
        except Exception as exc2:
            return f"[ERROR] browser_react_fill failed: {exc} | fallback: {exc2}"


@tool
def browser_scroll_page(
    direction: Annotated[str, "Direction to scroll: 'down', 'up', 'bottom', 'top'."] = "down",
    amount: Annotated[int, "Pixels to scroll (ignored for 'top'/'bottom'). Default 500."] = 500,
) -> str:
    """Scroll the browser page. Use 'bottom' to jump to end, 'top' to jump to start."""

    async def _do():
        await _ensure_browser()
        if direction == "bottom":
            await _page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        elif direction == "top":
            await _page.evaluate("window.scrollTo(0, 0)")
        elif direction == "up":
            await _page.evaluate(f"window.scrollBy(0, -{amount})")
        else:
            await _page.evaluate(f"window.scrollBy(0, {amount})")
        scroll_y = await _page.evaluate("window.scrollY")
        total = await _page.evaluate("document.body.scrollHeight")
        return f"scrollY={int(scroll_y)}, pageHeight={int(total)}"

    try:
        info = _run(_do())
        return f"[OK] Scrolled {direction}. {info}"
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def browser_select_option(
    selector: Annotated[str, "CSS selector for the <select> element."],
    value: Annotated[str, "Option value, label text, or index (prefix with 'index:' for index)."],
) -> str:
    """Select an option from a dropdown <select> element."""

    async def _do():
        await _ensure_browser()
        if value.startswith("index:"):
            idx = int(value.removeprefix("index:"))
            await _page.select_option(selector, index=idx, timeout=10000)
        else:
            try:
                await _page.select_option(selector, value=value, timeout=5000)
            except Exception:
                await _page.select_option(selector, label=value, timeout=10000)

    try:
        _run(_do())
        return f"[OK] Selected '{value}' in '{selector}'"
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def browser_upload_file(
    selector: Annotated[str, "CSS selector for <input type='file'>."],
    file_path: Annotated[str, "Absolute path to the file to upload."],
) -> str:
    """Upload a file via a file input element."""

    async def _do():
        await _ensure_browser()
        await _page.set_input_files(selector, file_path, timeout=15000)

    try:
        _run(_do())
        return f"[OK] Uploaded '{file_path}' via '{selector}'"
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def browser_handle_dialog(
    action: Annotated[str, "'accept' or 'dismiss'. Default 'accept'."] = "accept",
    prompt_text: Annotated[str, "Text to enter for JS prompt() dialogs. Leave empty for alerts/confirms."] = "",
) -> str:
    """Handle the next JavaScript alert/confirm/prompt dialog that appears."""

    async def _do():
        await _ensure_browser()

        async def _on_dialog(dialog):
            if action == "dismiss":
                await dialog.dismiss()
            else:
                await dialog.accept(prompt_text)

        _page.on("dialog", _on_dialog)
        return "Handler registered"

    try:
        _run(_do())
        return f"[OK] Will {action} next dialog" + (f" with text '{prompt_text}'" if prompt_text else "")
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def browser_get_links(
    filter_text: Annotated[str, "Only return links containing this text (case-insensitive). Empty = all."] = "",
    max_links: Annotated[int, "Maximum number of links to return."] = 50,
) -> str:
    """Extract all links from the current page. Useful for finding download links, navigation, etc."""

    async def _do():
        await _ensure_browser()
        links = await _page.evaluate("""
            () => Array.from(document.querySelectorAll('a[href]')).map(a => ({
                text: (a.textContent || '').trim().substring(0, 80),
                href: a.href
            }))
        """)
        return links

    try:
        all_links = _run(_do())
        if filter_text:
            ft = filter_text.lower()
            all_links = [l for l in all_links if ft in l["text"].lower() or ft in l["href"].lower()]
        all_links = all_links[:max_links]
        if not all_links:
            return "(no links found)"
        lines = [f"  [{i}] {l['text']} → {l['href']}" for i, l in enumerate(all_links)]
        return f"{len(all_links)} link(s):\n" + "\n".join(lines)
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def browser_get_page_info() -> str:
    """Get current page title, URL, and basic metadata."""

    async def _do():
        await _ensure_browser()
        info = await _page.evaluate("""
            () => ({
                title: document.title,
                url: window.location.href,
                description: (document.querySelector('meta[name="description"]') || {}).content || '',
                forms: document.forms.length,
                inputs: document.querySelectorAll('input, textarea, select').length,
                images: document.images.length,
                links: document.links.length,
            })
        """)
        return info

    try:
        info = _run(_do())
        lines = [
            f"Title: {info['title']}",
            f"URL: {info['url']}",
        ]
        if info['description']:
            lines.append(f"Description: {info['description'][:200]}")
        lines.append(f"Forms: {info['forms']} | Inputs: {info['inputs']} | Images: {info['images']} | Links: {info['links']}")
        return "\n".join(lines)
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def browser_close() -> str:
    """Close the browser (use sparingly — the persistent context is fine to keep open)."""
    global _browser, _page, _playwright

    async def _do():
        global _browser, _page, _playwright
        if _browser:
            await _browser.close()
            _browser = None
            _page = None
        if _playwright:
            await _playwright.stop()
            _playwright = None

    try:
        _run(_do())
        return "[OK] Browser closed"
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"
