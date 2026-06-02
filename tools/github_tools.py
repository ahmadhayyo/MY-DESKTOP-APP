"""
GitHub integration tools — clone, status, commit, push, pull, create repo.

Uses `git` CLI directly (no extra Python packages required).
Works with any git host, but tool names use "github_" for clarity.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Annotated

from langchain_core.tools import tool

from config import DESKTOP_DIR

_TIMEOUT = 120  # seconds for git operations
_MAX_OUTPUT = 6000


def _run_git(args: list[str], cwd: str | None = None) -> str:
    """Run a git command and return combined output."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
            shell=False,
        )
        output = result.stdout or ""
        if result.stderr:
            output += f"\n[STDERR] {result.stderr}"
        if len(output) > _MAX_OUTPUT:
            output = output[:_MAX_OUTPUT] + f"\n...[TRUNCATED]"
        return f"[exit={result.returncode}]\n{output}".strip()
    except subprocess.TimeoutExpired:
        return f"[ERROR] Git command timed out after {_TIMEOUT}s"
    except FileNotFoundError:
        return "[ERROR] git not found. Make sure git is installed."
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def github_clone(
    repo_url: Annotated[str, "Repository URL (e.g. https://github.com/user/repo.git)."],
    dest: Annotated[str, "Destination folder. Use 'desktop:' for Desktop. Leave empty for auto."] = "",
) -> str:
    """Clone a GitHub (or any git) repository to a local folder."""
    if not dest or dest.lower() in ("desktop:", "desktop"):
        repo_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
        target = DESKTOP_DIR / repo_name
    else:
        target = Path(os.path.expandvars(os.path.expanduser(dest))).resolve()

    if target.exists():
        return f"[ERROR] Destination already exists: {target}"

    return _run_git(["clone", repo_url, str(target)])


@tool
def github_status(
    repo_path: Annotated[str, "Path to the local git repository."],
) -> str:
    """Show git status of a local repository (changed files, branch, etc.)."""
    p = Path(os.path.expandvars(os.path.expanduser(repo_path))).resolve()
    if not (p / ".git").exists():
        return f"[ERROR] Not a git repository: {p}"

    branch = _run_git(["branch", "--show-current"], cwd=str(p))
    status = _run_git(["status", "--short"], cwd=str(p))
    log = _run_git(["log", "--oneline", "-5"], cwd=str(p))

    return f"Branch: {branch}\n\nStatus:\n{status}\n\nRecent commits:\n{log}"


@tool
def github_commit_push(
    repo_path: Annotated[str, "Path to the local git repository."],
    message: Annotated[str, "Commit message."],
    push: Annotated[bool, "Whether to push after committing."] = True,
) -> str:
    """Stage all changes, commit, and optionally push to the remote repository."""
    p = Path(os.path.expandvars(os.path.expanduser(repo_path))).resolve()
    if not (p / ".git").exists():
        return f"[ERROR] Not a git repository: {p}"

    # Stage all changes
    add_result = _run_git(["add", "-A"], cwd=str(p))

    # Check if there's anything to commit
    diff = _run_git(["diff", "--cached", "--stat"], cwd=str(p))
    if "exit=0" in diff and diff.strip().endswith("[exit=0]"):
        return "[INFO] Nothing to commit — working tree clean."

    # Commit
    commit_result = _run_git(["commit", "-m", message], cwd=str(p))

    if not push:
        return f"Staged & Committed:\n{commit_result}"

    # Push
    push_result = _run_git(["push"], cwd=str(p))
    return f"Staged & Committed:\n{commit_result}\n\nPush:\n{push_result}"


@tool
def github_pull(
    repo_path: Annotated[str, "Path to the local git repository."],
) -> str:
    """Pull latest changes from the remote repository."""
    p = Path(os.path.expandvars(os.path.expanduser(repo_path))).resolve()
    if not (p / ".git").exists():
        return f"[ERROR] Not a git repository: {p}"

    return _run_git(["pull"], cwd=str(p))


@tool
def github_create_repo(
    name: Annotated[str, "Repository name."],
    private: Annotated[bool, "Whether the repo should be private."] = True,
    description: Annotated[str, "Repository description."] = "",
    init_local: Annotated[str, "Local folder to init & push. Empty = create on GitHub only."] = "",
) -> str:
    """
    Create a new GitHub repository using the gh CLI (if available),
    or initialize a local git repo and set up the remote.
    """
    # Try gh CLI first
    try:
        visibility = "--private" if private else "--public"
        args = ["gh", "repo", "create", name, visibility]
        if description:
            args += ["--description", description]

        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=30,
            shell=False,
        )
        gh_output = result.stdout + result.stderr

        # If init_local is specified, clone into it
        if init_local and "exit=0" in f"exit={result.returncode}":
            local_path = Path(os.path.expandvars(os.path.expanduser(init_local))).resolve()
            local_path.mkdir(parents=True, exist_ok=True)
            _run_git(["init"], cwd=str(local_path))
            _run_git(["remote", "add", "origin", f"https://github.com/{name}.git"], cwd=str(local_path))

        return f"[exit={result.returncode}]\n{gh_output}"
    except FileNotFoundError:
        pass
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"

    # Fallback: init local repo if path provided
    if init_local:
        local_path = Path(os.path.expandvars(os.path.expanduser(init_local))).resolve()
        local_path.mkdir(parents=True, exist_ok=True)
        init_result = _run_git(["init"], cwd=str(local_path))
        return (
            f"[INFO] gh CLI not available. Initialized local repo:\n{init_result}\n"
            f"To push to GitHub, create the repo at https://github.com/new "
            f"and run: git remote add origin https://github.com/YOUR_USER/{name}.git && git push -u origin main"
        )

    return (
        "[ERROR] gh CLI not installed. "
        "Create the repo at https://github.com/new "
        "then clone it locally."
    )


@tool
def github_branch(
    repo_path: Annotated[str, "Path to the local git repository."],
    action: Annotated[str, "Action: 'list', 'create <name>', 'switch <name>', 'delete <name>'."],
) -> str:
    """Manage git branches — list, create, switch, or delete."""
    p = Path(os.path.expandvars(os.path.expanduser(repo_path))).resolve()
    if not (p / ".git").exists():
        return f"[ERROR] Not a git repository: {p}"

    parts = action.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if cmd == "list":
        return _run_git(["branch", "-a"], cwd=str(p))
    elif cmd == "create" and arg:
        return _run_git(["checkout", "-b", arg], cwd=str(p))
    elif cmd == "switch" and arg:
        return _run_git(["checkout", arg], cwd=str(p))
    elif cmd == "delete" and arg:
        return _run_git(["branch", "-d", arg], cwd=str(p))
    else:
        return "[ERROR] Invalid action. Use: list, create <name>, switch <name>, delete <name>"
