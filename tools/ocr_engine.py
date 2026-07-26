"""
ocr_engine.py — Unified OCR engine for the whole agent.

ROOT FIX: This machine has NO tesseract.exe installed, but it IS Windows 11
which ships a native OCR engine (Windows.Media.Ocr) supporting Arabic + English
with ZERO installation. This module uses that native engine as the PRIMARY OCR,
falling back to pytesseract only if the native path fails.

Public API:
    ocr_text(image)            → str   (image = file path OR PIL.Image)
    ocr_available()            → bool
    ocr_engine_name()          → str   ("windows-native" | "tesseract" | "none")

All other modules should import from here instead of calling pytesseract directly.
"""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import threading
import time

logger = logging.getLogger("hayo.ocr")

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PS_OCR_SCRIPT = os.path.join(_THIS_DIR, "win_ocr.ps1")

# ── Engine detection (cached) ────────────────────────────────────────────────
_engine_lock = threading.Lock()
_engine_checked = False
_native_ok = False
_tesseract_ok = False
_tesseract_cmd = None


def _detect_tesseract_path() -> str | None:
    """Find tesseract.exe in common install locations."""
    candidates = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Tesseract-OCR\tesseract.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Programs\Tesseract-OCR\tesseract.exe"),
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    # Check PATH
    try:
        import shutil
        found = shutil.which("tesseract")
        if found:
            return found
    except Exception:
        pass
    return None


def _detect_engines() -> None:
    """Detect available OCR engines once; cache the result."""
    global _engine_checked, _native_ok, _tesseract_ok, _tesseract_cmd
    with _engine_lock:
        if _engine_checked:
            return

        # 1. Native Windows OCR — check the DLL + the PS script exist
        try:
            dll_present = os.path.isfile(r"C:\Windows\System32\Windows.Media.Ocr.dll")
            script_present = os.path.isfile(_PS_OCR_SCRIPT)
            if dll_present and script_present:
                _native_ok = True
                logger.info("OCR engine: Windows native (Windows.Media.Ocr) ✅")
        except Exception as e:
            logger.warning("Native OCR detection failed: %s", e)

        # 2. Tesseract fallback
        try:
            _tesseract_cmd = _detect_tesseract_path()
            if _tesseract_cmd:
                import pytesseract
                pytesseract.pytesseract.tesseract_cmd = _tesseract_cmd
                _tesseract_ok = True
                logger.info("OCR engine fallback: tesseract @ %s", _tesseract_cmd)
        except Exception as e:
            logger.warning("Tesseract detection failed: %s", e)

        if not _native_ok and not _tesseract_ok:
            logger.error("⚠️ NO OCR ENGINE AVAILABLE — agent will be blind to screen text!")

        _engine_checked = True


def ocr_available() -> bool:
    _detect_engines()
    return _native_ok or _tesseract_ok


def ocr_engine_name() -> str:
    _detect_engines()
    if _native_ok:
        return "windows-native"
    if _tesseract_ok:
        return "tesseract"
    return "none"


def _to_temp_png(image) -> tuple[str, bool]:
    """
    Normalize input to a PNG file path.
    Returns (path, is_temp). If image is already a path, is_temp=False.
    """
    # Already a file path?
    if isinstance(image, str):
        if os.path.isfile(image):
            return image, False
        raise FileNotFoundError(f"OCR image path not found: {image}")

    # Assume PIL.Image — save to temp
    fd, tmp = tempfile.mkstemp(suffix=".png", prefix="hayo_ocr_")
    os.close(fd)
    try:
        image.save(tmp, "PNG")
    except Exception as e:
        raise ValueError(f"Could not save image for OCR: {e}")
    return tmp, True


def _ocr_native(image_path: str, timeout: int = 30) -> str:
    """Run native Windows OCR via the PowerShell bridge."""
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", _PS_OCR_SCRIPT, "-ImagePath", image_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        out = (completed.stdout or "").strip()
        if "__OCR_ERROR__" in out or "__OCR_ENGINE_NULL__" in out:
            logger.warning("Native OCR returned error marker: %s", out[:120])
            return ""
        return out
    except subprocess.TimeoutExpired:
        logger.warning("Native OCR timed out after %ds", timeout)
        return ""
    except Exception as e:
        logger.warning("Native OCR failed: %s", e)
        return ""


def _ocr_tesseract(image_path: str) -> str:
    """Run tesseract OCR (fallback)."""
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(image_path)
        return pytesseract.image_to_string(img, lang="ara+eng")
    except Exception as e:
        logger.warning("Tesseract OCR failed: %s", e)
        return ""


def ocr_text(image, timeout: int = 30) -> str:
    """
    Extract text from an image using the best available OCR engine.

    Args:
        image: a file path (str) OR a PIL.Image.Image object.
        timeout: max seconds for native OCR.

    Returns:
        Recognized text (may be empty string if nothing found / no engine).
    """
    _detect_engines()

    if not (_native_ok or _tesseract_ok):
        return ""

    path, is_temp = "", False
    try:
        path, is_temp = _to_temp_png(image)

        # Try native first
        if _native_ok:
            text = _ocr_native(path, timeout=timeout)
            if text.strip():
                return text
            # Native gave nothing — try tesseract if available
            if _tesseract_ok:
                return _ocr_tesseract(path)
            return text  # empty

        # Native not available — use tesseract
        if _tesseract_ok:
            return _ocr_tesseract(path)

        return ""
    finally:
        if is_temp and path and os.path.isfile(path):
            try:
                os.remove(path)
            except Exception:
                pass


def ocr_words(image, timeout: int = 30) -> list[dict]:
    """
    Extract words WITH bounding boxes.

    Returns a list of dicts: [{"t": word, "x": int, "y": int, "w": int, "h": int}, ...]
    where x,y is the top-left of the word box, w,h its size (image pixel coords).

    Uses native Windows OCR (word boxes). Falls back to tesseract image_to_data.
    """
    _detect_engines()
    path, is_temp = "", False
    try:
        path, is_temp = _to_temp_png(image)

        # Native words mode
        if _native_ok:
            words = _ocr_words_native(path, timeout=timeout)
            if words:
                return words
            # fall through to tesseract if native empty
        if _tesseract_ok:
            return _ocr_words_tesseract(path)
        return []
    except Exception as e:
        logger.warning("ocr_words failed: %s", e)
        return []
    finally:
        if is_temp and path and os.path.isfile(path):
            try:
                os.remove(path)
            except Exception:
                pass


def _ocr_words_native(image_path: str, timeout: int = 30) -> list[dict]:
    """Native Windows OCR in words mode → list of word boxes."""
    import json
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", _PS_OCR_SCRIPT, "-ImagePath", image_path, "-Mode", "words"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout,
        )
        out = (completed.stdout or "").strip()
        if not out or "__OCR_" in out:
            return []
        words = []
        for line in out.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                words.append(json.loads(line))
            except Exception:
                continue
        return words
    except Exception as e:
        logger.warning("Native OCR words failed: %s", e)
        return []


def _ocr_words_tesseract(image_path: str) -> list[dict]:
    """Tesseract fallback → list of word boxes."""
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(image_path)
        data = pytesseract.image_to_data(
            img, output_type=pytesseract.Output.DICT, lang="ara+eng"
        )
        words = []
        for i, txt in enumerate(data["text"]):
            if not txt.strip():
                continue
            try:
                conf = int(data["conf"][i])
            except Exception:
                conf = 0
            if conf < 20:
                continue
            words.append({
                "t": txt, "x": data["left"][i], "y": data["top"][i],
                "w": data["width"][i], "h": data["height"][i],
            })
        return words
    except Exception as e:
        logger.warning("Tesseract words failed: %s", e)
        return []


def ocr_find(text_to_find: str, image=None, timeout: int = 30) -> tuple | None:
    """
    Find the center (x, y) of the first word matching text_to_find.
    If image is None, screenshots the current screen.
    Returns (cx, cy) or None.
    """
    try:
        if image is None:
            import pyautogui
            image = pyautogui.screenshot()
        needle = text_to_find.lower().strip()
        words = ocr_words(image, timeout=timeout)
        for wd in words:
            if needle in str(wd.get("t", "")).lower():
                cx = int(wd["x"]) + int(wd["w"]) // 2
                cy = int(wd["y"]) + int(wd["h"]) // 2
                return (cx, cy)
        return None
    except Exception as e:
        logger.warning("ocr_find failed: %s", e)
        return None


# ── Convenience: OCR the current screen directly ─────────────────────────────
def ocr_screen(region: tuple | None = None, timeout: int = 30) -> str:
    """
    Screenshot the screen (or a region) and OCR it.
    region = (left, top, width, height) or None for full screen.
    """
    try:
        import pyautogui
        shot = pyautogui.screenshot(region=region) if region else pyautogui.screenshot()
        return ocr_text(shot, timeout=timeout)
    except Exception as e:
        logger.warning("ocr_screen failed: %s", e)
        return ""
