"""
Google Drive integration tools — upload, download, list files.

Uses the Google Drive API via google-api-python-client.
Requires a credentials.json or service account key in the project root.

If credentials are not configured, the tools will return helpful setup instructions.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

from langchain_core.tools import tool

from config import DESKTOP_DIR

# Lazy-loaded Drive service
_drive_service = None
_SCOPES = ["https://www.googleapis.com/auth/drive"]
_CREDS_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "credentials.json")
_TOKEN_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "gdrive_token.json")


def _get_drive_service():
    """Initialize and return the Google Drive API service."""
    global _drive_service
    if _drive_service is not None:
        return _drive_service

    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except ImportError:
        return None

    creds = None

    # Load existing token
    if os.path.exists(_TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(_TOKEN_PATH, _SCOPES)

    # Refresh or create new credentials
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        elif os.path.exists(_CREDS_PATH):
            flow = InstalledAppFlow.from_client_secrets_file(_CREDS_PATH, _SCOPES)
            creds = flow.run_local_server(port=0)
        else:
            return None

        # Save token for next time
        with open(_TOKEN_PATH, "w") as token:
            token.write(creds.to_json())

    _drive_service = build("drive", "v3", credentials=creds)
    return _drive_service


_SETUP_MSG = (
    "[INFO] Google Drive not configured yet.\n\n"
    "To set up Google Drive integration:\n"
    "1. Go to https://console.cloud.google.com/apis/credentials\n"
    "2. Create an OAuth 2.0 Client ID (Desktop application)\n"
    "3. Download the JSON file and save it as 'credentials.json' in the HAYO AI AGENT folder\n"
    "4. Install the required packages: pip install google-api-python-client google-auth-oauthlib\n"
    "5. Run any gdrive tool again — it will open a browser for authorization\n\n"
    "Alternatively, use run_powershell to interact with Google Drive via rclone."
)


@tool
def gdrive_list(
    folder_id: Annotated[str, "Google Drive folder ID. Use 'root' for the main drive."] = "root",
    query: Annotated[str, "Search query (e.g. 'name contains report'). Empty for all files."] = "",
    max_results: Annotated[int, "Maximum number of files to return."] = 30,
) -> str:
    """List files in Google Drive. Use folder_id='root' for the main drive."""
    service = _get_drive_service()
    if service is None:
        return _SETUP_MSG

    try:
        q_parts = [f"'{folder_id}' in parents", "trashed = false"]
        if query:
            q_parts.append(query)
        q = " and ".join(q_parts)

        results = service.files().list(
            q=q,
            pageSize=max_results,
            fields="files(id, name, mimeType, size, modifiedTime)",
            orderBy="modifiedTime desc",
        ).execute()

        files = results.get("files", [])
        if not files:
            return "(no files found)"

        lines = []
        for f in files:
            size = f.get("size", "—")
            if size != "—":
                size = f"{int(size) / 1024:.1f} KB"
            is_folder = "📁" if "folder" in f.get("mimeType", "") else "📄"
            lines.append(f"  {is_folder} {f['name']}  ({size})  ID: {f['id']}")

        return f"{len(files)} file(s):\n" + "\n".join(lines)
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def gdrive_download(
    file_id: Annotated[str, "Google Drive file ID."],
    dest: Annotated[str, "Destination path. Use 'desktop:' for Desktop."] = "desktop:",
    filename: Annotated[str, "Filename to save as. Empty = use original name."] = "",
) -> str:
    """Download a file from Google Drive to a local folder."""
    service = _get_drive_service()
    if service is None:
        return _SETUP_MSG

    try:
        from googleapiclient.http import MediaIoBaseDownload
        import io

        # Get file metadata
        file_meta = service.files().get(fileId=file_id, fields="name, mimeType, size").execute()
        original_name = file_meta.get("name", "downloaded_file")

        # Resolve destination
        if dest.lower() in ("desktop:", "desktop"):
            dest_dir = DESKTOP_DIR
        else:
            dest_dir = Path(os.path.expandvars(os.path.expanduser(dest))).resolve()

        dest_dir.mkdir(parents=True, exist_ok=True)
        target = dest_dir / (filename or original_name)

        # Check if it's a Google Docs file that needs export
        mime_type = file_meta.get("mimeType", "")
        if mime_type.startswith("application/vnd.google-apps."):
            export_map = {
                "application/vnd.google-apps.document": ("application/pdf", ".pdf"),
                "application/vnd.google-apps.spreadsheet": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
                "application/vnd.google-apps.presentation": ("application/pdf", ".pdf"),
            }
            export_mime, ext = export_map.get(mime_type, ("application/pdf", ".pdf"))
            if not target.suffix:
                target = target.with_suffix(ext)
            request = service.files().export_media(fileId=file_id, mimeType=export_mime)
        else:
            request = service.files().get_media(fileId=file_id)

        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

        with open(str(target), "wb") as f:
            f.write(fh.getvalue())

        return f"[OK] Downloaded '{original_name}' -> {target} ({len(fh.getvalue())} bytes)"
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def gdrive_upload(
    file_path: Annotated[str, "Local file path to upload."],
    folder_id: Annotated[str, "Google Drive folder ID to upload to. Use 'root' for main drive."] = "root",
) -> str:
    """Upload a local file to Google Drive."""
    service = _get_drive_service()
    if service is None:
        return _SETUP_MSG

    try:
        from googleapiclient.http import MediaFileUpload
        import mimetypes

        local = Path(os.path.expandvars(os.path.expanduser(file_path))).resolve()
        if not local.exists():
            return f"[ERROR] File not found: {local}"

        mime_type = mimetypes.guess_type(str(local))[0] or "application/octet-stream"
        file_metadata = {
            "name": local.name,
            "parents": [folder_id] if folder_id != "root" else [],
        }

        media = MediaFileUpload(str(local), mimetype=mime_type, resumable=True)
        uploaded = service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id, name, webViewLink",
        ).execute()

        return (
            f"[OK] Uploaded '{uploaded['name']}'\n"
            f"  File ID: {uploaded['id']}\n"
            f"  Link: {uploaded.get('webViewLink', 'N/A')}"
        )
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"
