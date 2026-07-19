"""
Coding tools: create projects, run scripts, edit files precisely.

These tools help the agent create programming projects, run code,
and make precise edits to source files.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Annotated

from langchain_core.tools import tool

from config import DESKTOP_DIR


def _resolve_path(p: str) -> Path:
    """Expand ~, env vars, and resolve to absolute Path.

    Relative paths resolve against the active workspace (the user's project
    folder) when one is set — so run_script('main.py') means
    '<workspace>/main.py', NOT '<app-dir>/main.py'.
    """
    expanded = os.path.expandvars(os.path.expanduser(p))
    if not os.path.isabs(expanded):
        try:
            from core.workspace_state import get_workspace
            ws = get_workspace()
            if ws:
                return Path(os.path.join(ws, expanded)).resolve()
        except Exception:
            pass
    return Path(expanded).resolve()


# ── Project templates ─────────────────────────────────────────────────────────

_TEMPLATES: dict[str, dict[str, str]] = {
    "python": {
        "main.py": '"""Main entry point."""\n\n\ndef main():\n    print("Hello from {name}!")\n\n\nif __name__ == "__main__":\n    main()\n',
        "requirements.txt": "# Add your dependencies here\n",
        "README.md": "# {name}\n\nA Python project.\n\n## Usage\n\n```bash\npython main.py\n```\n",
        ".gitignore": "__pycache__/\n*.pyc\n.env\nvenv/\n.venv/\n",
    },
    "web": {
        "index.html": '<!DOCTYPE html>\n<html lang="en">\n<head>\n    <meta charset="UTF-8">\n    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n    <title>{name}</title>\n    <link rel="stylesheet" href="style.css">\n</head>\n<body>\n    <h1>Welcome to {name}</h1>\n    <script src="script.js"></script>\n</body>\n</html>\n',
        "style.css": "* {{\n    margin: 0;\n    padding: 0;\n    box-sizing: border-box;\n}}\n\nbody {{\n    font-family: Arial, sans-serif;\n    display: flex;\n    justify-content: center;\n    align-items: center;\n    min-height: 100vh;\n    background: #f0f0f0;\n}}\n\nh1 {{\n    color: #333;\n}}\n",
        "script.js": '// {name} - Main JavaScript\nconsole.log("{name} loaded!");\n',
    },
    "node": {
        "index.js": '// {name} - Main entry point\n\nconsole.log("Hello from {name}!");\n',
        "package.json": '{{\n  "name": "{name_lower}",\n  "version": "1.0.0",\n  "description": "{name}",\n  "main": "index.js",\n  "scripts": {{\n    "start": "node index.js",\n    "dev": "node --watch index.js"\n  }}\n}}\n',
        ".gitignore": "node_modules/\n.env\n",
    },
    "empty": {
        "README.md": "# {name}\n\nProject created by HAYO Agent.\n",
    },
}


@tool
def create_project(
    name: Annotated[str, "Project name (used as folder name)."],
    template: Annotated[str, "Template: 'python', 'web', 'node', or 'empty'. Default 'python'."] = "python",
    location: Annotated[str, "Parent folder. Default is Desktop."] = "",
) -> str:
    """Create a new project folder with template files. Templates: python, web, node, empty."""
    if not location:
        parent = DESKTOP_DIR
    else:
        parent = _resolve_path(location)

    project_dir = parent / name
    if project_dir.exists():
        return (
            f"[ERROR] Project already exists: {project_dir}\n"
            f"This project is ALREADY THERE — do NOT create it again.\n"
            f"To work on it, use these tools instead:\n"
            f"  • list_dir(path='{project_dir}')        → see its files\n"
            f"  • read_file(path='{project_dir}/<file>') → read the code\n"
            f"  • edit_file_replace(path=..., old_text=..., new_text=...) → fix it"
        )

    tmpl = _TEMPLATES.get(template, _TEMPLATES["empty"])

    try:
        project_dir.mkdir(parents=True, exist_ok=True)
        created_files = []
        for filename, content_template in tmpl.items():
            content = content_template.format(
                name=name,
                name_lower=name.lower().replace(" ", "-"),
            )
            file_path = project_dir / filename
            file_path.write_text(content, encoding="utf-8")
            created_files.append(filename)

        return (
            f"[OK] Project '{name}' created at {project_dir}\n"
            f"Template: {template}\n"
            f"Files: {', '.join(created_files)}"
        )
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def run_python(
    code: Annotated[str, "Python code to execute."],
    timeout: Annotated[int, "Max execution time in seconds. Default 30."] = 30,
    cwd: Annotated[str, "Working directory for execution. Pass the workspace path here. Default: Desktop."] = "",
) -> str:
    """Run Python code and return the output. Useful for calculations, data processing, testing.

    When working on a project, pass cwd=<workspace path> so imports and file paths
    resolve relative to the project directory instead of the Desktop.
    """
    if cwd.strip():
        work_dir = _resolve_path(cwd)
    else:
        # Default to the active workspace if set, else Desktop.
        try:
            from core.workspace_state import get_workspace
            _ws = get_workspace()
        except Exception:
            _ws = ""
        work_dir = Path(_ws) if _ws else DESKTOP_DIR
    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(work_dir),
        )
        output = result.stdout.strip()
        if result.stderr.strip():
            output += f"\n[STDERR] {result.stderr.strip()}"
        if result.returncode != 0:
            output = f"[EXIT CODE {result.returncode}]\n{output}"
        return output or "[OK] Code executed (no output)"
    except subprocess.TimeoutExpired:
        return f"[ERROR] Code execution timed out after {timeout}s"
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def run_script(
    path: Annotated[str, "Path to the script file to run."],
    script_args: Annotated[str, "Command-line arguments (space-separated). Default empty."] = "",
    timeout: Annotated[int, "Max execution time in seconds. Default 60."] = 60,
) -> str:
    """Run a script file (Python, Node.js, batch, PowerShell) and return output.

    Use this to TEST code after editing it — it reports stdout, stderr and exit code.
    """
    # NOTE: the parameter is `script_args`, never `args` — pydantic/langchain mangle
    # a field named `args` into `v__args`, which makes every call raise TypeError.
    target = _resolve_path(path)
    if not target.exists():
        return f"[ERROR] File not found: {target}"

    ext = target.suffix.lower()
    if ext == ".py":
        cmd = [sys.executable, str(target)]
    elif ext == ".js":
        cmd = ["node", str(target)]
    elif ext == ".bat" or ext == ".cmd":
        cmd = ["cmd.exe", "/c", str(target)]
    elif ext == ".ps1":
        cmd = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(target)]
    elif ext == ".sh":
        cmd = ["bash", str(target)]
    else:
        cmd = [str(target)]

    if script_args:
        cmd.extend(script_args.split())

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(target.parent),
        )
        output = result.stdout.strip()
        if result.stderr.strip():
            output += f"\n[STDERR] {result.stderr.strip()}"
        if result.returncode != 0:
            output = f"[EXIT CODE {result.returncode}]\n{output}"
        return output or "[OK] Script executed (no output)"
    except subprocess.TimeoutExpired:
        return f"[ERROR] Script timed out after {timeout}s"
    except FileNotFoundError as exc:
        return f"[ERROR] Runtime not found: {exc}. Make sure the interpreter is installed."
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def edit_file_lines(
    path: Annotated[str, "Path to the file to edit."],
    start_line: Annotated[int, "First line number to replace (1-based)."],
    end_line: Annotated[int, "Last line number to replace (1-based, inclusive)."],
    new_content: Annotated[str, "New text to insert in place of the removed lines."],
    encoding: Annotated[str, "Text encoding."] = "utf-8",
) -> str:
    """Replace specific lines in a file. Lines are 1-based. Useful for precise code edits."""
    target = _resolve_path(path)
    if not target.exists():
        return f"[ERROR] File not found: {target}"

    try:
        lines = target.read_text(encoding=encoding, errors="replace").splitlines(keepends=True)
        total = len(lines)

        if start_line < 1 or end_line < start_line:
            return f"[ERROR] Invalid line range: {start_line}-{end_line}"
        if start_line > total + 1:
            return f"[ERROR] start_line {start_line} > total lines {total}"

        # Adjust to 0-based
        s = start_line - 1
        e = min(end_line, total)

        # Ensure new_content ends with newline if replacing whole lines
        if new_content and not new_content.endswith("\n"):
            new_content += "\n"

        new_lines = lines[:s] + [new_content] + lines[e:]
        target.write_text("".join(new_lines), encoding=encoding)

        replaced_count = e - s
        return (
            f"[OK] Replaced lines {start_line}-{end_line} ({replaced_count} lines) in {target}\n"
            f"File now has {len(new_lines)} lines."
        )
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"


@tool
def edit_file_replace(
    path: Annotated[str, "Path to the file to edit."],
    old_text: Annotated[str, "The exact existing text to find and replace. Must match exactly."],
    new_text: Annotated[str, "The text to replace it with. Use empty string to delete."],
    encoding: Annotated[str, "Text encoding."] = "utf-8",
) -> str:
    """Find exact text in a file and replace it. More reliable than line-number editing.

    The old_text must appear EXACTLY once in the file (including whitespace/indentation).
    Use read_file first to see the exact content, then copy the section you want to change.

    Examples:
      edit_file_replace(path='app.py', old_text='def old_func():', new_text='def new_func():')
      edit_file_replace(path='config.json', old_text='"port": 3000', new_text='"port": 8080')
    """
    target = _resolve_path(path)
    if not target.exists():
        return f"[ERROR] File not found: {target}"

    try:
        content = target.read_text(encoding=encoding, errors="replace")
        count = content.count(old_text)

        if count == 0:
            snippet = old_text[:100].replace('\n', '\\n')
            return (
                f"[ERROR] Text not found in {target.name}.\n"
                f"Searched for: \"{snippet}{'...' if len(old_text) > 100 else ''}\"\n"
                f"⚠️ MANDATORY NEXT STEP: read_file(path='{target}') — read the ACTUAL content,\n"
                f"then copy old_text EXACTLY from the output (same whitespace/indentation)."
            )
        if count > 1:
            return (
                f"[ERROR] Found {count} matches — must be unique.\n"
                f"Include more surrounding context in old_text to make it unique."
            )

        new_content = content.replace(old_text, new_text, 1)
        target.write_text(new_content, encoding=encoding)

        old_lines = old_text.count('\n') + 1
        new_lines = new_text.count('\n') + 1
        return (
            f"[OK] Replaced {old_lines} line(s) with {new_lines} line(s) in {target.name}\n"
            f"File size: {len(new_content)} chars."
        )
    except Exception as exc:
        return f"[ERROR] {type(exc).__name__}: {exc}"
