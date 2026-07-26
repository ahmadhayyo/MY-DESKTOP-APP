"""
core/workspace_state.py — Shared, process-wide "current workspace" base.

Why this exists:
  The file/coding tools resolve relative paths (e.g. read_file('main.py')).
  Without a workspace base, Path('main.py').resolve() resolves against the
  PROCESS working directory — which is the HAYO app folder, NOT the user's
  project. That made the agent read/edit files in the wrong folder whenever
  the model passed a relative path instead of a full absolute one.

  This module holds the active project folder. `_resolve_path` in the tools
  layer uses it as the base for RELATIVE paths, so 'main.py' correctly means
  '<workspace>/main.py'. Absolute paths (C:/...) are unaffected.

Thread-safe, dependency-free, and safe to import from anywhere.
"""
from __future__ import annotations

import os
import threading

_lock = threading.RLock()
_workspace: str = ""


def set_workspace(path: str) -> str:
    """Set the active workspace base. Only accepts an existing directory.

    Returns the normalised path that was stored (empty string if cleared or
    the path was invalid).
    """
    global _workspace
    with _lock:
        if not path or not str(path).strip():
            _workspace = ""
            return ""
        p = os.path.abspath(os.path.expandvars(os.path.expanduser(str(path).strip())))
        if os.path.isdir(p):
            _workspace = p
        return _workspace


def get_workspace() -> str:
    """Return the active workspace base, or '' if none is set."""
    with _lock:
        return _workspace


def clear_workspace() -> None:
    global _workspace
    with _lock:
        _workspace = ""
