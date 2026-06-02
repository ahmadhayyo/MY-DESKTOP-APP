"""
Replit-specific automation tools for HAYO AI Agent.

Allows the agent to:
  - Open Replit projects
  - Upload/download files
  - Run projects
  - Manage git sync
  - View file contents
  - Edit files
"""

from __future__ import annotations

import os
import subprocess
import json
from pathlib import Path
from typing import Annotated, Optional

from langchain_core.tools import tool


@tool
def replit_open_project(
    project_name: Annotated[str, "Name or URL of the Replit project"],
) -> str:
    """
    Open a Replit project in the default browser.

    Examples:
      replit_open_project('my-python-project')
      replit_open_project('https://replit.com/@user/project-name')
    """
    try:
        # If it's a full URL, use it directly
        if project_name.startswith("http"):
            url = project_name
        # If it's just a project name, try to construct the URL
        elif "/" in project_name:
            # Assume format: username/project
            url = f"https://replit.com/@{project_name}"
        else:
            # Just the project name - user needs to provide more info
            return "[ERROR] Please provide full project URL or username/project format"

        # Open in browser
        import webbrowser

        webbrowser.open(url)
        return f"[OK] Opened Replit project: {url}"

    except Exception as exc:
        return f"[ERROR] Could not open project: {exc}"


@tool
def replit_list_files(
    project_path: Annotated[str, "Local path to cloned Replit project"] = ".",
    filter_ext: Annotated[str, "Optional file extension to filter (e.g., 'py', 'js')"] = "",
) -> str:
    """
    List files in a Replit project directory.

    Examples:
      replit_list_files('.')                    # List all files
      replit_list_files('.', 'py')              # List Python files only
      replit_list_files('C:/Projects/my-repl')
    """
    try:
        path = Path(project_path).expanduser()

        if not path.exists():
            return f"[ERROR] Path not found: {path}"

        if not path.is_dir():
            return f"[ERROR] Not a directory: {path}"

        files = []
        for item in sorted(path.rglob("*")):
            if item.is_file():
                # Skip hidden files and common unimportant dirs
                if any(part.startswith(".") for part in item.parts):
                    continue

                rel_path = item.relative_to(path)
                size = item.stat().st_size

                if filter_ext:
                    if item.suffix.lstrip(".") != filter_ext:
                        continue

                files.append(f"{rel_path} ({size:,} bytes)")

        if not files:
            return f"[OK] No files found in {path}"

        return "[OK] Files:\n" + "\n".join(files[:100])

    except Exception as exc:
        return f"[ERROR] {exc}"


@tool
def replit_read_file(
    file_path: Annotated[str, "Path to file in Replit project"],
) -> str:
    """
    Read the contents of a file in the Replit project.

    Examples:
      replit_read_file('main.py')
      replit_read_file('src/app.js')
      replit_read_file('C:/Projects/my-repl/index.html')
    """
    try:
        path = Path(file_path).expanduser()

        if not path.exists():
            return f"[ERROR] File not found: {path}"

        if not path.is_file():
            return f"[ERROR] Not a file: {path}"

        content = path.read_text(encoding="utf-8", errors="replace")

        # Limit output to 5000 chars
        if len(content) > 5000:
            return f"[OK] File content (truncated, {len(content)} total chars):\n\n{content[:5000]}...\n\n[Use replit_read_file for smaller ranges or specific line numbers]"

        return f"[OK] File content ({len(content)} chars):\n\n{content}"

    except Exception as exc:
        return f"[ERROR] Could not read file: {exc}"


@tool
def replit_update_file(
    file_path: Annotated[str, "Path to file in Replit project"],
    content: Annotated[str, "New content for the file"],
    create_if_missing: Annotated[bool, "Create file if it doesn't exist"] = True,
) -> str:
    """
    Create or update a file in the Replit project.

    Examples:
      replit_update_file('main.py', 'print("Hello World")')
      replit_update_file('config.json', '{"debug": true}')
      replit_update_file('src/new_file.js', 'console.log("test");')
    """
    try:
        path = Path(file_path).expanduser()

        # Create directories if needed
        path.parent.mkdir(parents=True, exist_ok=True)

        if path.exists() or create_if_missing:
            path.write_text(content, encoding="utf-8")
            return f"[OK] Updated file: {path} ({len(content)} bytes)"
        else:
            return f"[ERROR] File does not exist and create_if_missing=False: {path}"

    except Exception as exc:
        return f"[ERROR] Could not update file: {exc}"


@tool
def replit_git_commit(
    project_path: Annotated[str, "Local path to cloned Replit project"],
    message: Annotated[str, "Commit message"],
    files_pattern: Annotated[str, "Files to commit (e.g., '*.py', '.', 'main.py')"] = ".",
) -> str:
    """
    Commit changes to git in the Replit project.

    Examples:
      replit_git_commit('.', 'Initial commit')
      replit_git_commit('C:/Projects/my-repl', 'Update main.py', 'main.py')
      replit_git_commit('.', 'Add features', '*.py')
    """
    try:
        project_path = Path(project_path).expanduser()

        if not (project_path / ".git").exists():
            return "[ERROR] Not a git repository. Initialize with 'git init' first."

        # Stage files
        stage_cmd = f'cd "{project_path}" && git add {files_pattern}'
        result = subprocess.run(stage_cmd, shell=True, capture_output=True, text=True, timeout=10)

        if result.returncode != 0:
            return f"[ERROR] Git add failed: {result.stderr}"

        # Commit
        commit_cmd = f'cd "{project_path}" && git commit -m "{message}"'
        result = subprocess.run(commit_cmd, shell=True, capture_output=True, text=True, timeout=10)

        if result.returncode != 0:
            return f"[ERROR] Git commit failed: {result.stderr}"

        return f"[OK] Committed: {message}\n{result.stdout}"

    except Exception as exc:
        return f"[ERROR] {exc}"


@tool
def replit_git_sync(
    project_path: Annotated[str, "Local path to cloned Replit project"],
    pull_first: Annotated[bool, "Pull changes before pushing"] = True,
) -> str:
    """
    Sync (push/pull) changes with Replit git remote.

    Examples:
      replit_git_sync('.')
      replit_git_sync('C:/Projects/my-repl', pull_first=True)
    """
    try:
        project_path = Path(project_path).expanduser()

        if not (project_path / ".git").exists():
            return "[ERROR] Not a git repository."

        commands = []

        if pull_first:
            commands.append(f'cd "{project_path}" && git pull')

        commands.append(f'cd "{project_path}" && git push')

        for cmd in commands:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)

            if result.returncode != 0:
                # Don't fail on "nothing to push" messages
                if "nothing to commit" not in result.stderr.lower():
                    return f"[ERROR] Git command failed: {result.stderr}"

        return f"[OK] Repository synced successfully"

    except Exception as exc:
        return f"[ERROR] {exc}"


@tool
def replit_run_project(
    project_path: Annotated[str, "Local path to Replit project"],
    run_command: Annotated[str, "Command to run (e.g., 'python main.py', 'node index.js')"],
    timeout_seconds: Annotated[int, "Max execution time"] = 30,
) -> str:
    """
    Run a Replit project locally.

    Examples:
      replit_run_project('.', 'python main.py')
      replit_run_project('C:/Projects/my-repl', 'npm start', timeout_seconds=60)
    """
    try:
        project_path = Path(run_command).expanduser()

        # Change to project directory and run command
        full_cmd = f'cd "{project_path}" && {run_command}'

        result = subprocess.run(
            full_cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )

        output = (result.stdout or "") + (result.stderr or "")

        if result.returncode != 0:
            return f"[ERROR] Exit code {result.returncode}\n{output[-2000:]}"  # Last 2000 chars

        return f"[OK] Execution completed\n\n{output[:3000]}"  # First 3000 chars

    except subprocess.TimeoutExpired:
        return f"[ERROR] Execution timed out after {timeout_seconds}s"
    except Exception as exc:
        return f"[ERROR] {exc}"


@tool
def replit_create_project_structure(
    project_path: Annotated[str, "Path where to create the project"],
    project_type: Annotated[str, "Project type: 'python', 'nodejs', 'web'"],
) -> str:
    """
    Create a basic Replit project structure.

    Examples:
      replit_create_project_structure('.', 'python')
      replit_create_project_structure('C:/Projects/new-app', 'nodejs')
    """
    try:
        project_path = Path(project_path).expanduser()
        project_path.mkdir(parents=True, exist_ok=True)

        # Create appropriate files based on project type
        if project_type.lower() == "python":
            (project_path / "main.py").write_text('print("Hello from Python!")')
            (project_path / "requirements.txt").write_text("# Add dependencies here\n")
            (project_path / ".gitignore").write_text("__pycache__/\n*.pyc\n")

        elif project_type.lower() == "nodejs":
            (project_path / "index.js").write_text('console.log("Hello from Node!");')
            (project_path / "package.json").write_text(
                json.dumps(
                    {
                        "name": "replit-nodejs",
                        "version": "1.0.0",
                        "main": "index.js",
                        "scripts": {"start": "node index.js"},
                    },
                    indent=2,
                )
            )
            (project_path / ".gitignore").write_text("node_modules/\n")

        elif project_type.lower() == "web":
            (project_path / "index.html").write_text(
                """<!DOCTYPE html>
<html>
<head>
    <title>Replit Web</title>
</head>
<body>
    <h1>Hello from HTML</h1>
</body>
</html>"""
            )
            (project_path / "style.css").write_text("body { font-family: Arial; }")
            (project_path / "script.js").write_text('console.log("Hello from JS!");')
            (project_path / ".gitignore").write_text("")

        # Initialize git
        subprocess.run(f'cd "{project_path}" && git init', shell=True, capture_output=True)

        return f"[OK] Created {project_type} project at {project_path}"

    except Exception as exc:
        return f"[ERROR] {exc}"
