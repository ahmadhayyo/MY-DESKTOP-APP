"""
Offline Mode Detection — Checks internet connectivity and classifies tools.

When the user has no internet connection, tools that require network access
(browser, download, translation, etc.) are automatically disabled, and the
agent works with local-only tools.
"""

from __future__ import annotations

import logging
import socket
from functools import lru_cache
from typing import Set

logger = logging.getLogger(__name__)

# Tools that require internet to function
_ONLINE_TOOLS: Set[str] = {
    # Browser tools (all need internet)
    "browser_open", "browser_get_text", "browser_click", "browser_fill",
    "browser_react_fill", "browser_press", "browser_screenshot",
    "browser_download_via_click", "browser_download_to_desktop",
    "browser_eval_js", "browser_wait_for", "browser_login",
    "browser_new_tab", "browser_switch_tab", "browser_list_tabs",
    "browser_close_tab", "browser_get_cookies", "browser_close",
    "browser_scroll_page", "browser_select_option", "browser_upload_file",
    "browser_handle_dialog", "browser_get_links", "browser_get_page_info",
    # Download tools
    "download_file", "download_with_progress", "check_url_availability",
    "download_audio_by_search", "download_audio_from_url", "download_video_from_url",
    # Chrome management
    "chrome_search_and_open", "chrome_download_file_from_page",
    "chrome_extract_download_links", "chrome_handle_redirects",
    "chrome_search_media_file", "chrome_get_direct_download_url",
    # Network tools
    "get_public_ip", "ping_host", "dns_lookup", "check_port",
    # Translation (uses Google Translate API)
    "translate_text", "excel_clone_translated", "word_clone_translated",
    # Cloud integrations
    "gdrive_list", "gdrive_download", "gdrive_upload",
    "github_clone", "github_commit_push", "github_pull",
    "github_create_repo",
    # Replit
    "replit_open_project", "replit_list_files", "replit_read_file",
    "replit_update_file", "replit_git_commit", "replit_git_sync",
    "replit_run_project", "replit_create_project_structure",
}


def check_internet(timeout: float = 1.0) -> bool:
    """Quick check for internet connectivity (1 target, fast)."""
    try:
        sock = socket.create_connection(("8.8.8.8", 53), timeout=timeout)
        sock.close()
        return True
    except (socket.timeout, OSError):
        pass
    return False


_INTERNET_CACHE: bool | None = None

def clear_internet_cache() -> None:
    """Clear the cached internet status (call at start of each task)."""
    global _INTERNET_CACHE
    _INTERNET_CACHE = None

def is_online() -> bool:
    """Check if internet is available (uses cache within same task)."""
    global _INTERNET_CACHE
    if _INTERNET_CACHE is None:
        _INTERNET_CACHE = check_internet()
    return _INTERNET_CACHE


def is_tool_online_only(tool_name: str) -> bool:
    """Check if a tool requires internet to function."""
    return tool_name in _ONLINE_TOOLS


def filter_offline_tools(tools: list, online: bool | None = None) -> list:
    """
    Filter out online-only tools when offline.

    Args:
        tools: List of BaseTool instances
        online: Override for online status (None = auto-detect)

    Returns:
        Filtered list of tools that work in current connectivity state
    """
    if online is None:
        online = is_online()

    if online:
        return tools  # All tools available

    filtered = [t for t in tools if not is_tool_online_only(t.name)]
    removed_count = len(tools) - len(filtered)
    if removed_count > 0:
        logger.info(
            "Offline mode: disabled %d online-only tools. %d tools available.",
            removed_count, len(filtered),
        )
    return filtered


def get_offline_notice() -> str:
    """Return a notice message when working offline."""
    return (
        "⚡ **وضع عدم الاتصال** — الإنترنت غير متاح حالياً.\n"
        "الأدوات المحلية متاحة: ملفات، أوامر النظام، Office (Excel/Word/PDF)، "
        "سطح المكتب، التطبيقات، الحافظة، والمزيد.\n"
        "الأدوات المعطلة: المتصفح، التحميل، الترجمة، GitHub، Google Drive.\n\n"
        "عند عودة الاتصال، ستعود جميع الأدوات تلقائياً."
    )
