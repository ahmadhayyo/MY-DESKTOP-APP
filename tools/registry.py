"""
Single source of truth for all tools the agent can invoke.

Import ALL_TOOLS from here instead of importing from individual modules —
this guarantees a consistent ordering and lets you easily disable a category
in one place.

Each tool category is wrapped in try/except so a missing dependency
(e.g. playwright not installed) disables only that category instead of
crashing the entire application.
"""

from __future__ import annotations

import logging
from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)

# Collect tools with graceful degradation per category
_all_tools: list[BaseTool] = []
_failed_categories: list[str] = []


def _import_category(category: str, import_fn):
    """Try to import a tool category; log and skip on failure."""
    try:
        tools = import_fn()
        _all_tools.extend(tools)
    except Exception as exc:
        _failed_categories.append(category)
        logger.warning("⚠️ Tool category '%s' unavailable: %s", category, exc)


# ═══════════════════════════════════════════════════════════
# SHELL & SYSTEM
# ═══════════════════════════════════════════════════════════
def _load_system():
    from tools.system_tools import get_env, run_cmd, run_powershell
    return [run_powershell, run_cmd, get_env]

_import_category("system", _load_system)

def _load_process():
    from tools.process_tools import (
        get_system_info, kill_process, list_processes,
        manage_service, scheduled_task,
    )
    return [get_system_info, list_processes, kill_process, manage_service, scheduled_task]

_import_category("process", _load_process)

# ═══════════════════════════════════════════════════════════
# FILE SYSTEM
# ═══════════════════════════════════════════════════════════
def _load_files():
    from tools.file_tools import (
        append_file, copy_file, download_file, list_dir,
        make_dir, move_file, read_file, search_files, write_file,
    )
    return [read_file, write_file, append_file, list_dir, search_files,
            move_file, copy_file, download_file, make_dir]

_import_category("files", _load_files)

# ═══════════════════════════════════════════════════════════
# CLIPBOARD
# ═══════════════════════════════════════════════════════════
def _load_clipboard():
    from tools.clipboard_tools import clipboard_get, clipboard_set, clipboard_append
    return [clipboard_get, clipboard_set, clipboard_append]

_import_category("clipboard", _load_clipboard)

# ═══════════════════════════════════════════════════════════
# APPLICATIONS
# ═══════════════════════════════════════════════════════════
def _load_apps():
    from tools.app_tools import close_app, focus_window, list_running_apps, open_app
    return [open_app, close_app, list_running_apps, focus_window]

_import_category("apps", _load_apps)

# ═══════════════════════════════════════════════════════════
# BROWSER (Playwright persistent session)
# ═══════════════════════════════════════════════════════════
def _load_browser():
    from tools.browser_tools import (
        browser_click, browser_close, browser_close_tab,
        browser_download_to_desktop, browser_download_via_click,
        browser_eval_js, browser_fill, browser_get_cookies,
        browser_get_links, browser_get_page_info, browser_get_text,
        browser_handle_dialog, browser_list_tabs, browser_login,
        browser_new_tab, browser_open, browser_press, browser_react_fill,
        browser_screenshot, browser_scroll_page, browser_select_option,
        browser_switch_tab, browser_upload_file, browser_wait_for,
    )
    return [
        browser_open, browser_get_text, browser_click, browser_fill,
        browser_react_fill, browser_press, browser_screenshot,
        browser_download_via_click, browser_download_to_desktop,
        browser_eval_js, browser_wait_for, browser_login,
        browser_new_tab, browser_switch_tab, browser_list_tabs,
        browser_close_tab, browser_get_cookies, browser_scroll_page,
        browser_select_option, browser_upload_file, browser_handle_dialog,
        browser_get_links, browser_get_page_info, browser_close,
    ]

_import_category("browser", _load_browser)

# ═══════════════════════════════════════════════════════════
# DESKTOP GUI (pyautogui — pixel-level control)
# ═══════════════════════════════════════════════════════════
def _load_desktop():
    from tools.desktop_tools import (
        keyboard_hotkey, keyboard_type, list_windows,
        mouse_click, mouse_move, mouse_scroll,
        screen_screenshot, screen_size, wait,
    )
    return [screen_screenshot, screen_size, mouse_click, mouse_move,
            mouse_scroll, keyboard_type, keyboard_hotkey, list_windows, wait]

_import_category("desktop", _load_desktop)

# ═══════════════════════════════════════════════════════════
# NETWORK
# ═══════════════════════════════════════════════════════════
def _load_network():
    from tools.network_tools import (
        check_port, dns_lookup, get_network_info,
        get_public_ip, ping_host, wifi_management,
    )
    return [get_network_info, get_public_ip, ping_host, check_port,
            wifi_management, dns_lookup]

_import_category("network", _load_network)

# ═══════════════════════════════════════════════════════════
# AUDIO & NOTIFICATIONS
# ═══════════════════════════════════════════════════════════
def _load_audio():
    from tools.audio_tools import (
        play_sound, show_notification, text_to_speech, volume_control,
    )
    return [volume_control, text_to_speech, show_notification, play_sound]

_import_category("audio", _load_audio)

# ═══════════════════════════════════════════════════════════
# OFFICE (Excel, Word, PDF)
# ═══════════════════════════════════════════════════════════
def _load_office():
    from tools.office_tools import (
        excel_create, excel_read, excel_edit, excel_add_rows,
        excel_add_column, excel_clone_translated, word_clone_translated,
        word_create, word_read, word_edit, pdf_read, pdf_create,
        pdf_merge, convert_excel_to_pdf, convert_word_to_pdf,
        translate_text, file_info, file_compare,
    )
    return [
        excel_create, excel_read, excel_edit, excel_add_rows,
        excel_add_column, excel_clone_translated, word_clone_translated,
        word_create, word_read, word_edit, pdf_read, pdf_create,
        pdf_merge, convert_excel_to_pdf, convert_word_to_pdf,
        translate_text, file_info, file_compare,
    ]

_import_category("office", _load_office)

# ═══════════════════════════════════════════════════════════
# ADVANCED DOWNLOAD (with progress, retry, integrity)
# ═══════════════════════════════════════════════════════════
def _load_advanced_download():
    from tools.advanced_download import (
        download_with_progress, check_url_availability, get_file_hash,
    )
    return [download_with_progress, check_url_availability, get_file_hash]

_import_category("advanced_download", _load_advanced_download)

# ═══════════════════════════════════════════════════════════
# CHROME MANAGEMENT (search, extract links, handle redirects)
# ═══════════════════════════════════════════════════════════
def _load_chrome():
    from tools.chrome_management import (
        chrome_search_and_open, chrome_download_file_from_page,
        chrome_extract_download_links, chrome_handle_redirects,
        chrome_search_media_file, chrome_get_direct_download_url,
    )
    return [chrome_search_and_open, chrome_download_file_from_page,
            chrome_extract_download_links, chrome_handle_redirects,
            chrome_search_media_file, chrome_get_direct_download_url]

_import_category("chrome", _load_chrome)

# ═══════════════════════════════════════════════════════════
# FILE CONVERSION (audio, video, docs, images)
# ═══════════════════════════════════════════════════════════
def _load_conversion():
    from tools.file_conversion import (
        convert_file, get_supported_formats, check_conversion_support,
    )
    return [convert_file, get_supported_formats, check_conversion_support]

_import_category("conversion", _load_conversion)

# ═══════════════════════════════════════════════════════════
# REPLIT INTEGRATION (project management, git sync, execution)
# ═══════════════════════════════════════════════════════════
def _load_replit():
    from tools.replit_tools import (
        replit_open_project, replit_list_files, replit_read_file,
        replit_update_file, replit_git_commit, replit_git_sync,
        replit_run_project, replit_create_project_structure,
    )
    return [replit_open_project, replit_list_files, replit_read_file,
            replit_update_file, replit_git_commit, replit_git_sync,
            replit_run_project, replit_create_project_structure]

_import_category("replit", _load_replit)

# ═══════════════════════════════════════════════════════════
# MEDIA — songs / videos from YouTube etc. via yt-dlp
# ═══════════════════════════════════════════════════════════
def _load_media():
    from tools.media_tools import (
        download_audio_by_search, download_audio_from_url,
        download_video_from_url,
    )
    return [download_audio_by_search, download_audio_from_url,
            download_video_from_url]

_import_category("media", _load_media)

# ═══════════════════════════════════════════════════════════
# MEMORY — recall past conversations across sessions
# ═══════════════════════════════════════════════════════════
def _load_memory():
    from tools.memory_tools import (
        list_past_conversations, search_past_conversations,
        recall_conversation_details,
    )
    return [list_past_conversations, search_past_conversations,
            recall_conversation_details]

_import_category("memory", _load_memory)

# ═══════════════════════════════════════════════════════════
# GITHUB — git operations (clone, commit, push, pull, branches)
# ═══════════════════════════════════════════════════════════
def _load_github():
    from tools.github_tools import (
        github_clone, github_status, github_commit_push,
        github_pull, github_create_repo, github_branch,
    )
    return [github_clone, github_status, github_commit_push,
            github_pull, github_create_repo, github_branch]

_import_category("github", _load_github)

# ═══════════════════════════════════════════════════════════
# GOOGLE DRIVE — upload, download, list files
# ═══════════════════════════════════════════════════════════
def _load_gdrive():
    from tools.gdrive_tools import gdrive_list, gdrive_download, gdrive_upload
    return [gdrive_list, gdrive_download, gdrive_upload]

_import_category("gdrive", _load_gdrive)

# ═══════════════════════════════════════════════════════════
# FILE VALIDATION & TESTING
# ═══════════════════════════════════════════════════════════
def _load_testing():
    from tools.testing_tools import (
        validate_document, run_executable_test, open_and_screenshot,
    )
    return [validate_document, run_executable_test, open_and_screenshot]

_import_category("testing", _load_testing)

# ═══════════════════════════════════════════════════════════
# CODING — project creation, script execution, precise file editing
# ═══════════════════════════════════════════════════════════
def _load_coding():
    from tools.coding_tools import (
        create_project, run_python, run_script, edit_file_lines,
    )
    return [create_project, run_python, run_script, edit_file_lines]

_import_category("coding", _load_coding)

# ═══════════════════════════════════════════════════════════
# ARCHIVE & FILE MANAGEMENT — zip, unzip, delete, size
# ═══════════════════════════════════════════════════════════
def _load_archive():
    from tools.archive_tools import zip_files, unzip_file, delete_path, get_file_size
    return [zip_files, unzip_file, delete_path, get_file_size]

_import_category("archive", _load_archive)

# ═══════════════════════════════════════════════════════════
# VISION — Screen reading & OCR (agent "eyes")
# ═══════════════════════════════════════════════════════════
def _load_vision():
    from tools.vision_tools import (
        screen_read_text, screen_find_text, screen_find_and_click,
        screen_wait_for_text, screen_get_pixel_color,
        screen_capture_region, screen_compare_changes,
    )
    return [
        screen_read_text, screen_find_text, screen_find_and_click,
        screen_wait_for_text, screen_get_pixel_color,
        screen_capture_region, screen_compare_changes,
    ]

_import_category("vision", _load_vision)

# ═══════════════════════════════════════════════════════════
# WINDOWS POWER — Deep Windows OS control
# ═══════════════════════════════════════════════════════════
def _load_windows():
    from tools.windows_tools import (
        windows_search, window_manager, get_active_window,
        type_in_window, drag_and_drop, open_settings_page,
        power_action, manage_startup_apps, set_wallpaper,
        get_system_details, run_as_admin,
        windows_toast_notification, scroll_in_window, app_exists,
    )
    return [
        windows_search, window_manager, get_active_window,
        type_in_window, drag_and_drop, open_settings_page,
        power_action, manage_startup_apps, set_wallpaper,
        get_system_details, run_as_admin,
        windows_toast_notification, scroll_in_window, app_exists,
    ]

_import_category("windows", _load_windows)


# ── Final exports ─────────────────────────────────────────────────────────────
ALL_TOOLS: list[BaseTool] = _all_tools
TOOLS_BY_NAME: dict[str, BaseTool] = {t.name: t for t in ALL_TOOLS}

if _failed_categories:
    logger.warning(
        "⚠️ %d tool category(ies) failed to load: %s. "
        "The agent will work with %d available tools.",
        len(_failed_categories), ", ".join(_failed_categories), len(ALL_TOOLS),
    )
else:
    logger.info("✅ All tool categories loaded successfully (%d tools)", len(ALL_TOOLS))
