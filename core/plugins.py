"""
Plugin System — load custom tool modules from the plugins/ directory.

Each plugin is a .py file in the plugins/ directory that exposes a
``TOOLS`` list of LangChain ``BaseTool`` instances.

Example plugin (plugins/my_plugin.py):

    from langchain_core.tools import tool

    @tool
    def my_custom_tool(query: str) -> str:
        \"\"\"Do something custom.\"\"\"
        return f"Result: {query}"

    TOOLS = [my_custom_tool]
    PLUGIN_NAME = "My Custom Plugin"
    PLUGIN_DESCRIPTION = "A custom plugin that does something."

Usage from app.py:
    /plugins           — list loaded plugins
    /plugins reload    — reload all plugins
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent
_PLUGINS_DIR = _ROOT / "plugins"

# Registry of loaded plugins
_loaded_plugins: dict[str, dict[str, Any]] = {}
_plugin_tools: list[BaseTool] = []


def _ensure_plugins_dir() -> Path:
    """Create the plugins directory if it doesn't exist."""
    _PLUGINS_DIR.mkdir(exist_ok=True)
    init_file = _PLUGINS_DIR / "__init__.py"
    if not init_file.exists():
        init_file.write_text("")

    # Create example plugin if directory is empty
    example = _PLUGINS_DIR / "_example_plugin.py"
    if not example.exists():
        example.write_text(
            '"""\n'
            "Example Plugin — rename this file and customize.\n\n"
            "To create your own plugin:\n"
            "  1. Create a .py file in this plugins/ directory\n"
            "  2. Define your tools using @tool decorator\n"
            "  3. Export them in a TOOLS list\n"
            '"""\n\n'
            "from langchain_core.tools import tool\n\n\n"
            "# Plugin metadata (optional but recommended)\n"
            'PLUGIN_NAME = "Example Plugin"\n'
            'PLUGIN_DESCRIPTION = "مثال على إضافة مخصصة — قم بتعديله حسب حاجتك"\n\n\n'
            "# Define your tools\n"
            "# @tool\n"
            "# def my_tool(query: str) -> str:\n"
            '#     """وصف الأداة بالعربية أو الإنجليزية."""\n'
            '#     return f"Result: {query}"\n\n\n'
            "# Export tools list (REQUIRED)\n"
            "TOOLS: list = []  # Add your tools here: TOOLS = [my_tool]\n"
        )

    return _PLUGINS_DIR


def load_plugins() -> dict[str, dict[str, Any]]:
    """
    Scan the plugins/ directory and load all .py files that export TOOLS.

    Returns a dict of plugin_name -> {name, description, tools, path, error}.
    """
    global _loaded_plugins, _plugin_tools

    _loaded_plugins = {}
    _plugin_tools = []

    plugins_dir = _ensure_plugins_dir()

    for py_file in sorted(plugins_dir.glob("*.py")):
        if py_file.name.startswith("_") or py_file.name == "__init__.py":
            continue

        plugin_id = py_file.stem
        try:
            spec = importlib.util.spec_from_file_location(
                f"plugins.{plugin_id}", str(py_file)
            )
            if spec is None or spec.loader is None:
                continue

            module = importlib.util.module_from_spec(spec)
            sys.modules[f"plugins.{plugin_id}"] = module
            spec.loader.exec_module(module)

            tools = getattr(module, "TOOLS", [])
            name = getattr(module, "PLUGIN_NAME", plugin_id)
            description = getattr(module, "PLUGIN_DESCRIPTION", "")

            valid_tools = [t for t in tools if isinstance(t, BaseTool)]

            _loaded_plugins[plugin_id] = {
                "name": name,
                "description": description,
                "tools": valid_tools,
                "tool_count": len(valid_tools),
                "path": str(py_file),
                "error": None,
            }
            _plugin_tools.extend(valid_tools)

            if valid_tools:
                logger.info(
                    "Loaded plugin '%s' with %d tool(s)", name, len(valid_tools)
                )

        except Exception as exc:
            logger.warning("Failed to load plugin '%s': %s", plugin_id, exc)
            _loaded_plugins[plugin_id] = {
                "name": plugin_id,
                "description": "",
                "tools": [],
                "tool_count": 0,
                "path": str(py_file),
                "error": str(exc),
            }

    return _loaded_plugins


def get_plugin_tools() -> list[BaseTool]:
    """Return all tools from loaded plugins."""
    return list(_plugin_tools)


def reload_plugins() -> dict[str, dict[str, Any]]:
    """Reload all plugins (clears cache and re-imports)."""
    # Remove cached plugin modules
    to_remove = [k for k in sys.modules if k.startswith("plugins.")]
    for k in to_remove:
        del sys.modules[k]
    return load_plugins()


def list_plugins_display() -> str:
    """Return a formatted string showing all plugins and their status."""
    if not _loaded_plugins:
        load_plugins()

    lines = ["# 🧩 الإضافات — Plugins\n"]

    if not _loaded_plugins:
        lines.append("📭 لا توجد إضافات محمّلة.")
        lines.append(f"\nلإضافة إضافة جديدة، أنشئ ملف `.py` في مجلد `plugins/`")
        lines.append(f"المسار: `{_PLUGINS_DIR}`")
    else:
        active_count = sum(1 for p in _loaded_plugins.values() if p["tool_count"] > 0)
        total_tools = sum(p["tool_count"] for p in _loaded_plugins.values())
        lines.append(
            f"**{len(_loaded_plugins)}** إضافة محمّلة · "
            f"**{active_count}** نشطة · "
            f"**{total_tools}** أداة إجمالاً\n"
        )

        for pid, info in _loaded_plugins.items():
            if info.get("error"):
                status = f"❌ خطأ: {info['error'][:80]}"
            elif info["tool_count"] > 0:
                status = f"✅ {info['tool_count']} أداة"
            else:
                status = "⚪ بدون أدوات"

            lines.append(f"  🧩 **{info['name']}** — {status}")
            if info["description"]:
                lines.append(f"     {info['description']}")
            if info["tools"]:
                tool_names = ", ".join(f"`{t.name}`" for t in info["tools"])
                lines.append(f"     الأدوات: {tool_names}")
            lines.append("")

    lines.append("---")
    lines.append("**الأوامر:**")
    lines.append("  • `/plugins` — عرض الإضافات المحمّلة")
    lines.append("  • `/plugins reload` — إعادة تحميل الإضافات")
    lines.append(f"\n**مجلد الإضافات:** `{_PLUGINS_DIR}`")

    return "\n".join(lines)
