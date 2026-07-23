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
        read_webpage,
    )
    return [
        browser_open, read_webpage, browser_get_text, browser_click, browser_fill,
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
# ANDROID (ADB device control)
# ═══════════════════════════════════════════════════════════
def _load_android():
    from tools.android_tools import (
        android_devices, android_device_info, android_screenshot,
        android_tap, android_swipe, android_input_text, android_key_event,
        android_list_apps, android_launch_app, android_install_apk,
        android_uninstall_app, android_push_file, android_pull_file,
        android_open_url, android_shell,
    )
    return [android_devices, android_device_info, android_screenshot,
            android_tap, android_swipe, android_input_text, android_key_event,
            android_list_apps, android_launch_app, android_install_apk,
            android_uninstall_app, android_push_file, android_pull_file,
            android_open_url, android_shell]

_import_category("android", _load_android)

# ═══════════════════════════════════════════════════════════
# API KEY & ENDPOINT VERIFICATION
# ═══════════════════════════════════════════════════════════
def _load_api_keys():
    from tools.api_key_tools import (
        test_api_key, test_env_api_keys, test_endpoint,
    )
    return [test_api_key, test_env_api_keys, test_endpoint]

_import_category("api_keys", _load_api_keys)

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
# POWERPOINT — full presentation creation & editing
# ═══════════════════════════════════════════════════════════
def _load_powerpoint():
    from tools.powerpoint_tools import (
        ppt_create, ppt_add_slide, ppt_add_bullets, ppt_add_image,
        ppt_add_table, ppt_add_chart, ppt_read, ppt_edit_text,
        ppt_set_theme, ppt_info, ppt_to_pdf,
    )
    return [ppt_create, ppt_add_slide, ppt_add_bullets, ppt_add_image,
            ppt_add_table, ppt_add_chart, ppt_read, ppt_edit_text,
            ppt_set_theme, ppt_info, ppt_to_pdf]

_import_category("powerpoint", _load_powerpoint)


# ═══════════════════════════════════════════════════════════
# EXCEL PRO — formatting, formulas, charts, conditional formatting
# ═══════════════════════════════════════════════════════════
def _load_excel_pro():
    from tools.excel_pro_tools import (
        excel_format_range, excel_set_formula, excel_add_total_row,
        excel_add_chart, excel_autofit, excel_freeze_header,
        excel_highlight, excel_add_sheet, excel_style_report,
    )
    return [excel_format_range, excel_set_formula, excel_add_total_row,
            excel_add_chart, excel_autofit, excel_freeze_header,
            excel_highlight, excel_add_sheet, excel_style_report]

_import_category("excel_pro", _load_excel_pro)


# ═══════════════════════════════════════════════════════════
# WORD PRO — headings, tables, images, lists, RTL
# ═══════════════════════════════════════════════════════════
def _load_word_pro():
    from tools.word_pro_tools import (
        word_add_heading, word_add_paragraph, word_add_table,
        word_add_image, word_add_list, word_add_page_break,
        word_set_header_footer, word_set_rtl,
    )
    return [word_add_heading, word_add_paragraph, word_add_table,
            word_add_image, word_add_list, word_add_page_break,
            word_set_header_footer, word_set_rtl]

_import_category("word_pro", _load_word_pro)

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
        create_project, run_python, run_script, edit_file_lines, edit_file_replace,
    )
    return [create_project, run_python, run_script, edit_file_lines, edit_file_replace]

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
        analyze_screen, analyze_image,
    )
    return [
        screen_read_text, screen_find_text, screen_find_and_click,
        screen_wait_for_text, screen_get_pixel_color,
        screen_capture_region, screen_compare_changes,
        analyze_screen, analyze_image,
    ]

_import_category("vision", _load_vision)

# ═══════════════════════════════════════════════════════════
# LOCATE — find any file/app anywhere on the computer (all drives)
# ═══════════════════════════════════════════════════════════
def _load_locate():
    from tools.locate_tools import find_on_computer
    return [find_on_computer]

_import_category("locate", _load_locate)

# ═══════════════════════════════════════════════════════════
# TODO — live self-updating task checklist (Claude-Code style)
# ═══════════════════════════════════════════════════════════
def _load_todo():
    from tools.todo_tools import todo_write, todo_read
    return [todo_write, todo_read]

_import_category("todo", _load_todo)

# ═══════════════════════════════════════════════════════════
# TERMINAL SESSION — persistent, stateful shell (cwd/env/venv persist)
# ═══════════════════════════════════════════════════════════
def _load_terminal():
    from tools.terminal_tools import terminal_run, terminal_reset
    return [terminal_run, terminal_reset]

_import_category("terminal", _load_terminal)

# ═══════════════════════════════════════════════════════════
# SKILLS — reusable task methodologies (Claude-Code-style)
# ═══════════════════════════════════════════════════════════
def _load_skills():
    from tools.skill_tools import list_skills, load_skill
    return [list_skills, load_skill]

_import_category("skills", _load_skills)

# ═══════════════════════════════════════════════════════════
# SUB-AGENTS — delegate a focused subtask to an isolated mini-agent
# ═══════════════════════════════════════════════════════════
def _load_subagent():
    from tools.subagent_tools import spawn_subagent
    return [spawn_subagent]

_import_category("subagent", _load_subagent)

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
        launch_app_smart,
    )
    return [
        windows_search, window_manager, get_active_window,
        type_in_window, drag_and_drop, open_settings_page,
        power_action, manage_startup_apps, set_wallpaper,
        get_system_details, run_as_admin,
        windows_toast_notification, scroll_in_window, app_exists,
        launch_app_smart,
    ]

_import_category("windows", _load_windows)


# ═══════════════════════════════════════════════════════════
# Computer Use — High-level app/desktop interaction
# ═══════════════════════════════════════════════════════════
def _load_computer_use():
    from tools.computer_use_tools import (
        screen_describe,
        app_interact,
        open_app_and_login,
        solve_text_captcha,
        type_text_clipboard,
        handle_verification_screen,
    )
    return [
        screen_describe,
        app_interact,
        open_app_and_login,
        solve_text_captcha,
        type_text_clipboard,
        handle_verification_screen,
    ]

_import_category("computer_use", _load_computer_use)


# ═══════════════════════════════════════════════════════════
# WEB SEARCH — CAPTCHA-free, VPN-safe search (DuckDuckGo lite)
# ═══════════════════════════════════════════════════════════
def _load_web_search():
    from tools.web_search_tools import web_search, web_answer
    return [web_search, web_answer]

_import_category("web_search", _load_web_search)


# ═══════════════════════════════════════════════════════════
# LONG-TERM MEMORY — durable facts the agent remembers across sessions
# ═══════════════════════════════════════════════════════════
def _load_memory_facts():
    from tools.memory_facts_tools import (
        remember_fact, recall_facts, forget_fact, list_memory,
    )
    return [remember_fact, recall_facts, forget_fact, list_memory]

_import_category("memory_facts", _load_memory_facts)


# ═══════════════════════════════════════════════════════════
# SCHEDULER — recurring/one-off tasks that run through the agent
# ═══════════════════════════════════════════════════════════
def _load_scheduler():
    from tools.scheduler_tools import (
        schedule_task, list_scheduled_tasks,
        cancel_scheduled_task, toggle_scheduled_task,
    )
    return [schedule_task, list_scheduled_tasks,
            cancel_scheduled_task, toggle_scheduled_task]

_import_category("scheduler", _load_scheduler)


# ═══════════════════════════════════════════════════════════
# TELEGRAM (Telethon) — search groups/chats and download files
# ═══════════════════════════════════════════════════════════
def _load_telegram():
    from tools.telegram_tools import (
        telegram_status, telegram_login, telegram_verify_code,
        telegram_list_chats, telegram_search, telegram_search_files,
        telegram_download,
    )
    return [telegram_status, telegram_login, telegram_verify_code,
            telegram_list_chats, telegram_search, telegram_search_files,
            telegram_download]

_import_category("telegram", _load_telegram)


# ═══════════════════════════════════════════════════════════
# MARKETS — live data, technical analysis & charts (TwelveData)
# ═══════════════════════════════════════════════════════════
def _load_market():
    from tools.market_tools import (
        market_quote, market_timeseries, market_indicator,
        market_analyze, market_chart, market_news,
    )
    return [market_quote, market_timeseries, market_indicator,
            market_analyze, market_chart, market_news]

_import_category("market", _load_market)


# ═══════════════════════════════════════════════════════════
# INTEGRATIONS — real connectors (Discord/Slack/Telegram-bot/Email/Notion/HTTP/…)
# ═══════════════════════════════════════════════════════════
def _load_integrations():
    from tools.integration_tools import (
        send_discord, send_slack, telegram_bot_send, send_email,
        notion_create_page, http_request, get_weather, get_crypto_price,
    )
    return [send_discord, send_slack, telegram_bot_send, send_email,
            notion_create_page, http_request, get_weather, get_crypto_price]

_import_category("integrations", _load_integrations)


# ═══════════════════════════════════════════════════════════
# RAILWAY — manage deployments via the official GraphQL API
# ═══════════════════════════════════════════════════════════
def _load_railway():
    from tools.railway_tools import (
        railway_status, railway_projects, railway_services,
        railway_deployments, railway_logs, railway_redeploy,
        railway_variables, railway_graphql,
    )
    return [railway_status, railway_projects, railway_services,
            railway_deployments, railway_logs, railway_redeploy,
            railway_variables, railway_graphql]

_import_category("railway", _load_railway)


# ═══════════════════════════════════════════════════════════
# APP BUILDER — write code → lint → compile a Windows .exe (PyInstaller)
# ═══════════════════════════════════════════════════════════
def _load_app_builder():
    from tools.app_builder_tools import (
        list_build_tools, scaffold_desktop_app, lint_python,
        build_exe, build_desktop_app, run_executable,
    )
    return [list_build_tools, scaffold_desktop_app, lint_python,
            build_exe, build_desktop_app, run_executable]

_import_category("app_builder", _load_app_builder)


# ═══════════════════════════════════════════════════════════
# CAPABILITY FORGE — the agent writes & registers its own new tools at runtime
# ═══════════════════════════════════════════════════════════
def _load_forge():
    from tools.forge_tools import (
        forge_tool, list_forged_tools, inspect_forged_tool, remove_forged_tool,
    )
    return [forge_tool, list_forged_tools, inspect_forged_tool, remove_forged_tool]

_import_category("forge", _load_forge)


# ═══════════════════════════════════════════════════════════
# DYNAMIC / FORGED TOOLS — capabilities the agent built for itself
# Loaded from tools/dynamic/*.py so self-created tools persist across restarts.
# ═══════════════════════════════════════════════════════════
def _load_dynamic():
    import importlib
    import pkgutil
    from pathlib import Path
    dyn_dir = Path(__file__).resolve().parent / "dynamic"
    dyn_dir.mkdir(exist_ok=True)
    init = dyn_dir / "__init__.py"
    if not init.exists():
        init.write_text("", encoding="utf-8")
    collected: list[BaseTool] = []
    for mod in pkgutil.iter_modules([str(dyn_dir)]):
        if mod.name.startswith("_"):
            continue
        try:
            m = importlib.import_module(f"tools.dynamic.{mod.name}")
            for attr in vars(m).values():
                if isinstance(attr, BaseTool):
                    collected.append(attr)
        except Exception as exc:
            logger.warning("⚠️ forged tool '%s' failed to load: %s", mod.name, exc)
    return collected

_import_category("dynamic", _load_dynamic)


# ── Final exports ─────────────────────────────────────────────────────────────
ALL_TOOLS: list[BaseTool] = _all_tools
TOOLS_BY_NAME: dict[str, BaseTool] = {t.name: t for t in ALL_TOOLS}


def register_tool(tool_obj: BaseTool) -> bool:
    """
    Register a tool into the LIVE registry at runtime (used by the Capability
    Forge so a freshly-created tool is usable in the same session).

    Mutates ALL_TOOLS and TOOLS_BY_NAME in place — and because nodes.TOOL_MAP IS
    TOOLS_BY_NAME (same dict object), the worker can execute the new tool
    immediately. The caller is responsible for refreshing the LLM tool-binding so
    the model can also *choose* to call it.
    """
    if not isinstance(tool_obj, BaseTool):
        return False
    name = tool_obj.name
    if name in TOOLS_BY_NAME:
        # replace existing (hot-reload of a forged tool)
        try:
            idx = next(i for i, t in enumerate(ALL_TOOLS) if t.name == name)
            ALL_TOOLS[idx] = tool_obj
        except StopIteration:
            ALL_TOOLS.append(tool_obj)
    else:
        ALL_TOOLS.append(tool_obj)
    TOOLS_BY_NAME[name] = tool_obj
    return True


def unregister_tool(name: str) -> bool:
    """Remove a tool from the live registry by name."""
    if name not in TOOLS_BY_NAME:
        return False
    del TOOLS_BY_NAME[name]
    try:
        idx = next(i for i, t in enumerate(ALL_TOOLS) if t.name == name)
        ALL_TOOLS.pop(idx)
    except StopIteration:
        pass
    return True

if _failed_categories:
    logger.warning(
        "⚠️ %d tool category(ies) failed to load: %s. "
        "The agent will work with %d available tools.",
        len(_failed_categories), ", ".join(_failed_categories), len(ALL_TOOLS),
    )
else:
    logger.info("✅ All tool categories loaded successfully (%d tools)", len(ALL_TOOLS))
