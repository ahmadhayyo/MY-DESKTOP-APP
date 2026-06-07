"""
Vision Tools — Screen understanding for the HAYO agent.

Gives the agent "eyes" to read and understand what is currently on the screen:
  • screen_read_text      — OCR: extract all visible text from the screen or a region
  • screen_find_text      — locate where specific text appears on screen (x, y)
  • screen_find_and_click — find text on screen and click it
  • screen_describe_region — describe what is visible in a screen region
  • screen_wait_for_text  — wait until specific text appears on screen
  • screen_get_pixel_color — get color of a pixel (useful for state detection)
  • screen_compare        — compare two screenshots to detect changes
"""

from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Annotated, Optional

from langchain_core.tools import tool

# ── helpers ──────────────────────────────────────────────────────────────────

def _take_screenshot_pil(region: Optional[tuple] = None):
    """Return a PIL Image of the screen (or a region)."""
    import pyautogui
    if region:
        x, y, w, h = region
        return pyautogui.screenshot(region=(x, y, w, h))
    return pyautogui.screenshot()


def _pil_to_base64(img) -> str:
    """Convert PIL image to base64 PNG string."""
    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _ocr_image(img) -> str:
    """
    Run OCR on a PIL image using the unified engine.
    Primary: native Windows OCR (Windows.Media.Ocr). Fallback: tesseract.
    """
    try:
        from tools.ocr_engine import ocr_text
        text = ocr_text(img)
        if text and text.strip():
            return text.strip()
        return "[OCR: لم يُقرأ نص من الصورة]"
    except Exception as exc:
        return f"[OCR error: {exc}]"


def _cv2_find_text_coords(img_pil, text: str) -> Optional[tuple[int, int]]:
    """Find the center coords of text on screen via the unified OCR engine."""
    try:
        from tools.ocr_engine import ocr_find
        return ocr_find(text, image=img_pil)
    except Exception:
        return None


# ── tools ─────────────────────────────────────────────────────────────────────

@tool
def screen_read_text(
    region: Annotated[str, "Optional screen region as 'x,y,width,height'. Empty = full screen."] = "",
    language: Annotated[str, "OCR language: 'ara+eng' (Arabic+English), 'eng', 'ara'. Default: 'ara+eng'"] = "ara+eng",
) -> str:
    """
    Read all visible text from the screen using OCR.
    Use this to understand what is currently displayed — menus, dialogs, web pages, errors.
    Returns all text found on screen.
    """
    try:
        if region.strip():
            parts = [int(p.strip()) for p in region.split(",")]
            img = _take_screenshot_pil(tuple(parts))
        else:
            img = _take_screenshot_pil()

        text = _ocr_image(img)
        if not text:
            return "(No text found on screen)"
        # Truncate very long results
        if len(text) > 3000:
            text = text[:3000] + "\n...[truncated]"
        return f"[Screen text]\n{text}"
    except Exception as exc:
        return f"[ERROR] screen_read_text: {exc}"


@tool
def screen_find_text(
    text: Annotated[str, "The text to find on screen (case-insensitive)."],
    region: Annotated[str, "Optional region 'x,y,width,height'. Empty = full screen."] = "",
) -> str:
    """
    Find where specific text appears on screen and return its coordinates.
    Useful for locating buttons, labels, or messages before clicking them.
    Returns the center (x, y) coordinates of the found text.
    """
    try:
        if region.strip():
            parts = [int(p.strip()) for p in region.split(",")]
            img = _take_screenshot_pil(tuple(parts))
            offset_x, offset_y = parts[0], parts[1]
        else:
            img = _take_screenshot_pil()
            offset_x, offset_y = 0, 0

        coords = _cv2_find_text_coords(img, text)
        if coords:
            abs_x = coords[0] + offset_x
            abs_y = coords[1] + offset_y
            return f"[OK] Found '{text}' at screen coordinates: x={abs_x}, y={abs_y}"
        else:
            # Fallback: search in full OCR output
            full_text = _ocr_image(img)
            if text.lower() in full_text.lower():
                return f"[FOUND] '{text}' is visible on screen but exact coordinates unavailable. Use screen_read_text to get context."
            return f"[NOT FOUND] '{text}' is not currently visible on screen."
    except Exception as exc:
        return f"[ERROR] screen_find_text: {exc}"


@tool
def screen_find_and_click(
    text: Annotated[str, "The text of the button/link/element to find and click."],
    double_click: Annotated[bool, "Whether to double-click. Default False."] = False,
) -> str:
    """
    Find text on screen and click it. Perfect for clicking buttons, menu items,
    or any UI element identified by its visible text label.
    Much more reliable than guessing coordinates.
    """
    try:
        import pyautogui

        img = _take_screenshot_pil()
        coords = _cv2_find_text_coords(img, text)

        if not coords:
            # Try full OCR to confirm visibility
            full = _ocr_image(img)
            if text.lower() not in full.lower():
                return f"[NOT FOUND] '{text}' not visible on screen. Take a screenshot first to see what's there."
            return f"[FOUND BUT NO COORDS] '{text}' is visible but OCR couldn't locate exact position. Try mouse_click with approximate coordinates."

        x, y = coords
        if double_click:
            pyautogui.doubleClick(x, y)
        else:
            pyautogui.click(x, y)
        time.sleep(0.5)
        return f"[OK] Clicked '{text}' at ({x}, {y})"
    except Exception as exc:
        return f"[ERROR] screen_find_and_click: {exc}"


@tool
def screen_wait_for_text(
    text: Annotated[str, "The text to wait for."],
    timeout_seconds: Annotated[int, "Max seconds to wait. Default 15."] = 15,
    check_interval: Annotated[float, "How often to check (seconds). Default 1.0."] = 1.0,
) -> str:
    """
    Wait until specific text appears on screen (up to timeout seconds).
    Useful after clicking a button to wait for a confirmation message or page load.
    """
    try:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            img = _take_screenshot_pil()
            coords = _cv2_find_text_coords(img, text)
            if coords:
                return f"[OK] '{text}' appeared at ({coords[0]}, {coords[1]}) after {timeout_seconds - (deadline - time.time()):.1f}s"
            full = _ocr_image(img)
            if text.lower() in full.lower():
                return f"[OK] '{text}' appeared on screen."
            time.sleep(check_interval)

        return f"[TIMEOUT] '{text}' did not appear within {timeout_seconds} seconds."
    except Exception as exc:
        return f"[ERROR] screen_wait_for_text: {exc}"


@tool
def screen_get_pixel_color(
    x: Annotated[int, "X coordinate of the pixel."],
    y: Annotated[int, "Y coordinate of the pixel."],
) -> str:
    """
    Get the color of a specific pixel on screen. Returns RGB values.
    Useful for detecting button states (e.g., active/inactive) or loading indicators.
    """
    try:
        import pyautogui
        color = pyautogui.pixel(x, y)
        r, g, b = color
        hex_color = f"#{r:02X}{g:02X}{b:02X}"
        return f"[OK] Pixel at ({x}, {y}): RGB={color}, HEX={hex_color}"
    except Exception as exc:
        return f"[ERROR] screen_get_pixel_color: {exc}"


@tool
def screen_capture_region(
    x: Annotated[int, "Left edge X coordinate."],
    y: Annotated[int, "Top edge Y coordinate."],
    width: Annotated[int, "Width of the region in pixels."],
    height: Annotated[int, "Height of the region in pixels."],
    save_path: Annotated[str, "Path to save the PNG. Leave empty for Desktop."] = "",
) -> str:
    """
    Capture a specific region of the screen and save it as PNG.
    Useful for capturing a specific window, dialog, or area for analysis.
    """
    try:
        from config import DESKTOP_DIR
        img = _take_screenshot_pil((x, y, width, height))
        out = Path(save_path) if save_path else DESKTOP_DIR / "region_capture.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(out))
        return f"[OK] Region ({x},{y},{width}x{height}) saved to: {out}"
    except Exception as exc:
        return f"[ERROR] screen_capture_region: {exc}"


@tool
def screen_compare_changes(
    interval_seconds: Annotated[float, "Wait this many seconds between captures. Default 2.0."] = 2.0,
    threshold: Annotated[int, "Pixel difference threshold (0-255). Default 30."] = 30,
) -> str:
    """
    Take two screenshots separated by a short interval and detect what changed.
    Useful for monitoring when a page finishes loading or a download completes.
    """
    try:
        import numpy as np
        import cv2

        img1 = _take_screenshot_pil()
        time.sleep(interval_seconds)
        img2 = _take_screenshot_pil()

        arr1 = np.array(img1)
        arr2 = np.array(img2)

        diff = cv2.absdiff(arr1, arr2)
        changed_pixels = int(np.sum(diff > threshold))
        total_pixels = arr1.shape[0] * arr1.shape[1]
        change_pct = (changed_pixels / total_pixels) * 100

        if change_pct < 0.1:
            return "[OK] Screen did NOT change — page/app appears static."
        elif change_pct < 5:
            return f"[OK] Minor change detected ({change_pct:.1f}% of pixels changed) — possibly a cursor or small update."
        else:
            return f"[OK] Significant change detected ({change_pct:.1f}% of pixels changed) — page/app has updated."
    except Exception as exc:
        return f"[ERROR] screen_compare_changes: {exc}"
