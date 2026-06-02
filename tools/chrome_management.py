"""
Chrome-specific utilities for enhanced browser automation.

Provides workflows for:
  - Google Search integration
  - Direct file downloads from search results
  - Media file discovery and downloading
  - Browser session management
"""

from __future__ import annotations

from langchain_core.tools import tool


@tool
def chrome_search_and_open(
    query: str,
    open_first_result: bool = True,
) -> str:
    """
    Search Google for a query and optionally open the first result.

    Args:
        query: Search query (e.g., 'free mp3 download')
        open_first_result: Whether to click the first search result

    Returns:
        Status message with search results count or opened URL

    Workflow:
        1. Opens Google Search
        2. Types query in search box
        3. Presses Enter to search
        4. If open_first_result=True, clicks first search result
        5. Returns the URL of opened page

    Example:
        → chrome_search_and_open('Python documentation', open_first_result=True)
        → chrome_search_and_open('free music download sites')
    """
    # Note: This is a workflow tool that orchestrates browser_open, browser_fill,
    # browser_press, browser_click operations. The actual implementation delegates
    # to existing browser automation tools.
    return (
        "🌐 Chrome Search Workflow:\n"
        "1. browser_open('https://google.com')\n"
        "2. browser_fill(selector='[name=\"q\"]', value='{query}')\n"
        "3. browser_press(key='Enter')\n"
        "4. (if open_first_result) browser_click(selector='a h3')\n\n"
        "Use the individual browser tools above to implement this workflow."
    )


@tool
def chrome_download_file_from_page(
    url: str,
    selector: str = "a[href*='download']",
    wait_for_element: bool = True,
    timeout: int = 30,
) -> str:
    """
    Navigate to a URL and click a download link.

    Args:
        url: URL to navigate to
        selector: CSS selector for download link (default: first download link)
        wait_for_element: Wait for element to appear before clicking
        timeout: Max wait time in seconds

    Returns:
        Status message with download status

    Common selectors:
        • 'a[href*="download"]' - Any link with 'download' in href
        • 'button[data-action="download"]' - Download button with data attribute
        • '#download-btn' - Element with specific ID
        • '.download-link' - Element with CSS class

    Example:
        → chrome_download_file_from_page(
              'https://example.com/music.html',
              selector='a.download-btn'
          )
    """
    return (
        "📥 Download File Workflow:\n"
        f"1. browser_open('{url}')\n"
        f"2. If wait_for_element: browser_wait_for(selector='{selector}', timeout={timeout})\n"
        f"3. browser_screenshot() - to verify page loaded\n"
        f"4. browser_click(selector='{selector}')\n"
        f"5. Wait for download to complete\n\n"
        "Use the individual browser tools to implement this workflow."
    )


@tool
def chrome_extract_download_links(
    url: str,
    link_selector: str = "a[href*='download'], a[href$='.mp3'], a[href$='.pdf']",
) -> str:
    """
    Navigate to a URL and extract all downloadable links.

    Args:
        url: URL to navigate to
        link_selector: CSS selector for finding download links

    Returns:
        List of found download links

    Example selectors:
        • Links to audio files: 'a[href$=".mp3"], a[href$=".wav"], a[href$=".m4a"]'
        • Links to documents: 'a[href$=".pdf"], a[href$=".doc"], a[href$=".xlsx"]'
        • Links containing download: 'a[href*="download"], a.download-link'

    Example:
        → chrome_extract_download_links(
              'https://musicsite.com',
              link_selector='a[href$=".mp3"]'
          )
    """
    return (
        "🔍 Extract Links Workflow:\n"
        f"1. browser_open('{url}')\n"
        f"2. browser_eval_js(script='Array.from(document.querySelectorAll(\"{link_selector}\")).map(a => a.href)')\n"
        f"3. Parse results and return list of URLs\n\n"
        "Use browser_eval_js to extract links programmatically."
    )


@tool
def chrome_handle_redirects(
    initial_url: str,
    max_redirects: int = 5,
    timeout: int = 60,
) -> str:
    """
    Follow a URL through multiple redirects to find the final destination.

    Args:
        initial_url: Starting URL
        max_redirects: Maximum redirects to follow
        timeout: Total timeout in seconds

    Returns:
        Final URL after following all redirects

    Useful for:
        • Shortened URLs (bit.ly, tinyurl)
        • Download links with tracking redirects
        • URL shorteners used on websites

    Example:
        → chrome_handle_redirects('https://bit.ly/xyz123', max_redirects=3)
    """
    return (
        "🔄 Follow Redirects Workflow:\n"
        f"1. browser_open('{initial_url}')\n"
        f"2. Check current URL vs initial URL\n"
        f"3. If different, we've been redirected\n"
        f"4. Repeat up to {max_redirects} times\n"
        f"5. Return final URL\n\n"
        "Use browser screenshot or eval to get current URL after each navigation."
    )


@tool
def chrome_search_media_file(
    file_type: str = "mp3",
    search_query: str = "",
    site: str = "youtube.com",
) -> str:
    """
    Search for a specific media file type on a website.

    Args:
        file_type: File type ('mp3', 'mp4', 'pdf', etc.)
        search_query: What to search for
        site: Website to search in (default: youtube.com)

    Returns:
        Search results and workflow instructions

    Examples:
        • file_type='mp3', search_query='instrumental music'
        • file_type='mp4', search_query='tutorial'
        • file_type='pdf', search_query='research paper'

    Implementation Note:
        Different sites require different approaches:
        • YouTube: Use youtube.com/results?search_query=...
        • Google Drive: Use drive.google.com/drive/search?q=...
        • Archive.org: Use archive.org/?query=...
    """
    query_term = f" filetype:{file_type}" if file_type else ""
    search_url = f"https://www.google.com/search?q=site:{site} {search_query}{query_term}"

    return (
        f"🔎 Search {file_type.upper()} on {site}:\n"
        f"1. browser_open('{search_url}')\n"
        f"2. browser_get_text() - to see search results\n"
        f"3. browser_click() - to open relevant results\n"
        f"4. Use chrome_extract_download_links() to find download URLs\n\n"
        f"Or use site-specific search:\n"
        f"• YouTube: https://www.youtube.com/results?search_query={search_query}\n"
        f"• SoundCloud: https://soundcloud.com/search?q={search_query}\n"
    )


@tool
def chrome_get_direct_download_url(
    page_url: str,
    expected_file_type: str = "mp3",
) -> str:
    """
    Analyze a webpage to find direct download links for media files.

    Args:
        page_url: URL of the page containing download links
        expected_file_type: Expected file extension (mp3, mp4, pdf, etc.)

    Returns:
        Direct download URLs found on the page

    Strategy:
        1. Load the page
        2. Look for common download patterns:
           - href attributes with file extensions
           - Download buttons with data-href attributes
           - JavaScript download functions
        3. Return raw download URLs that can be used with download_file()

    Example:
        → chrome_get_direct_download_url(
              'https://example.com/song-page.html',
              expected_file_type='mp3'
          )
    """
    return (
        "🔗 Extract Direct Download URL:\n"
        f"1. browser_open('{page_url}')\n"
        f"2. browser_eval_js(script to find .{expected_file_type} links)\n"
        f"3. browser_click() on download button if no direct URL\n"
        f"4. Monitor network requests to capture download URL\n"
        f"5. Return URL suitable for download_file()\n\n"
        "Common download URL patterns:\n"
        "• https://host.com/download.php?id=123\n"
        "• https://host.com/files/song.mp3\n"
        "• Direct media URLs (can be used with download_file)"
    )
