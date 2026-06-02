"""
Integrations Hub — manage connections to external services.

Stores integration configs in integrations.json next to the .env file.
Supports built-in services (GitHub, Google Drive, Telegram, etc.) and
user-defined custom integrations (webhooks, APIs, websites).

Usage from app.py:
    /integrations          — list all integrations with status
    /connect <service>     — configure a service
    /disconnect <service>  — remove a service connection
    /connect custom        — add a custom integration manually
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _ROOT / "integrations.json"


# ── Built-in integration definitions ─────────────────────────────────────────
BUILTIN_INTEGRATIONS: dict[str, dict[str, Any]] = {
    "github": {
        "name": "GitHub",
        "icon": "🐙",
        "description": "إدارة المستودعات، الأكواد، والمشاريع",
        "description_en": "Manage repos, code, and projects",
        "category": "development",
        "config_keys": ["GITHUB_TOKEN"],
        "setup_url": "https://github.com/settings/tokens",
        "setup_hint": "أنشئ Personal Access Token من GitHub Settings → Developer settings → Tokens",
        "tools": ["github_clone", "github_status", "github_commit_push", "github_pull", "github_create_repo", "github_branch"],
    },
    "gdrive": {
        "name": "Google Drive",
        "icon": "📁",
        "description": "رفع وتحميل وإدارة الملفات على Google Drive",
        "description_en": "Upload, download, and manage files on Google Drive",
        "category": "storage",
        "config_keys": ["GDRIVE_CREDENTIALS"],
        "setup_url": "https://console.cloud.google.com/apis/credentials",
        "setup_hint": "أنشئ OAuth 2.0 Client ID واحفظ الملف كـ credentials.json",
        "tools": ["gdrive_list", "gdrive_download", "gdrive_upload"],
    },
    "telegram": {
        "name": "Telegram Bot",
        "icon": "✈️",
        "description": "إرسال واستقبال الرسائل عبر بوت Telegram",
        "description_en": "Send and receive messages via Telegram bot",
        "category": "messaging",
        "config_keys": ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"],
        "setup_url": "https://t.me/BotFather",
        "setup_hint": "أنشئ بوت جديد عبر @BotFather واحصل على التوكن",
        "tools": [],
    },
    "slack": {
        "name": "Slack",
        "icon": "💬",
        "description": "إرسال إشعارات ورسائل إلى قنوات Slack",
        "description_en": "Send notifications and messages to Slack channels",
        "category": "messaging",
        "config_keys": ["SLACK_WEBHOOK_URL"],
        "setup_url": "https://api.slack.com/messaging/webhooks",
        "setup_hint": "أنشئ Incoming Webhook من Slack API",
        "tools": [],
    },
    "notion": {
        "name": "Notion",
        "icon": "📝",
        "description": "إنشاء وتحديث الصفحات وقواعد البيانات في Notion",
        "description_en": "Create and update pages and databases in Notion",
        "category": "productivity",
        "config_keys": ["NOTION_API_KEY"],
        "setup_url": "https://www.notion.so/my-integrations",
        "setup_hint": "أنشئ Integration جديد من Notion Settings",
        "tools": [],
    },
    "trello": {
        "name": "Trello",
        "icon": "📋",
        "description": "إدارة البطاقات واللوحات في Trello",
        "description_en": "Manage cards and boards in Trello",
        "category": "productivity",
        "config_keys": ["TRELLO_API_KEY", "TRELLO_TOKEN"],
        "setup_url": "https://trello.com/app-key",
        "setup_hint": "احصل على API Key و Token من Trello Developer",
        "tools": [],
    },
    "discord": {
        "name": "Discord",
        "icon": "🎮",
        "description": "إرسال رسائل وإشعارات إلى سيرفرات Discord",
        "description_en": "Send messages and notifications to Discord servers",
        "category": "messaging",
        "config_keys": ["DISCORD_WEBHOOK_URL"],
        "setup_url": "https://discord.com/developers/applications",
        "setup_hint": "أنشئ Webhook في إعدادات القناة → التكاملات",
        "tools": [],
    },
    "webhook": {
        "name": "Webhook (عام)",
        "icon": "🔗",
        "description": "إرسال بيانات إلى أي URL عبر HTTP POST",
        "description_en": "Send data to any URL via HTTP POST",
        "category": "custom",
        "config_keys": ["WEBHOOK_URL"],
        "setup_url": "",
        "setup_hint": "أدخل رابط الـ Webhook الخاص بك",
        "tools": [],
    },
}


def _load_config() -> dict[str, Any]:
    """Load the integrations config file."""
    if _CONFIG_PATH.exists():
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"integrations": {}, "custom": []}


def _save_config(data: dict[str, Any]) -> None:
    """Persist the integrations config to disk."""
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def list_integrations() -> str:
    """Return a formatted string showing all integrations and their status."""
    config = _load_config()
    connected = config.get("integrations", {})

    lines = ["# 🔌 مركز التكاملات — Integrations Hub\n"]

    # Group by category
    categories = {
        "development": ("💻 التطوير", []),
        "storage": ("☁️ التخزين", []),
        "messaging": ("💬 المراسلة", []),
        "productivity": ("📊 الإنتاجية", []),
        "custom": ("🔧 مخصص", []),
    }

    for key, info in BUILTIN_INTEGRATIONS.items():
        cat = info.get("category", "custom")
        is_connected = key in connected and connected[key].get("enabled", False)

        # Check if keys are set in environment
        has_env_keys = all(
            bool(os.getenv(k, "").strip())
            for k in info.get("config_keys", [])
            if k != "GDRIVE_CREDENTIALS"
        )
        # Special check for gdrive credentials file
        if key == "gdrive":
            creds_path = _ROOT / "credentials.json"
            has_env_keys = creds_path.exists()

        if is_connected or has_env_keys:
            status = "✅ متصل"
        else:
            status = "⚪ غير متصل"

        tool_count = len(info.get("tools", []))
        tools_note = f" · {tool_count} أداة" if tool_count > 0 else ""

        entry = f"  {info['icon']} **{info['name']}** — {status}{tools_note}\n     {info['description']}"
        categories[cat][1].append(entry)

    # Add custom integrations
    for custom in config.get("custom", []):
        status = "✅ متصل" if custom.get("enabled", False) else "⚪ غير متصل"
        icon = custom.get("icon", "🔗")
        entry = f"  {icon} **{custom['name']}** — {status}\n     {custom.get('description', '')}"
        categories["custom"][1].append(entry)

    for cat_key, (cat_label, entries) in categories.items():
        if entries:
            lines.append(f"### {cat_label}")
            lines.extend(entries)
            lines.append("")

    lines.append("---")
    lines.append("**الأوامر:**")
    lines.append("  • `/connect <اسم>` — ربط خدمة (مثال: `/connect github`)")
    lines.append("  • `/disconnect <اسم>` — فصل خدمة")
    lines.append("  • `/connect custom` — إضافة تكامل مخصص يدوياً")
    lines.append(f"\n**الخدمات المتاحة:** {', '.join(f'`{k}`' for k in BUILTIN_INTEGRATIONS.keys())}")

    return "\n".join(lines)


def connect_integration(service: str) -> str:
    """Return setup instructions for connecting a service."""
    service = service.lower().strip()

    if service == "custom":
        return (
            "# 🔧 إضافة تكامل مخصص\n\n"
            "لإضافة تكامل مخصص، استخدم الأمر:\n"
            "`/connect custom <الاسم> <الرابط> [الوصف]`\n\n"
            "**مثال:**\n"
            "```\n"
            "/connect custom MyAPI https://api.example.com/webhook واجهة API للمتجر\n"
            "```\n\n"
            "أو يمكنك تحرير ملف `integrations.json` مباشرة."
        )

    if service not in BUILTIN_INTEGRATIONS:
        available = ", ".join(f"`{k}`" for k in BUILTIN_INTEGRATIONS.keys())
        return f"❌ خدمة غير معروفة: `{service}`\n\nالخدمات المتاحة: {available}, `custom`"

    info = BUILTIN_INTEGRATIONS[service]

    lines = [
        f"# {info['icon']} ربط {info['name']}\n",
        f"{info['description']}\n",
        "---\n",
        "### خطوات الإعداد:\n",
    ]

    # Step 1: Get credentials
    if info.get("setup_url"):
        lines.append(f"**1.** افتح: [{info['setup_url']}]({info['setup_url']})")
    lines.append(f"**2.** {info['setup_hint']}")

    # Step 2: Add to .env
    if info.get("config_keys"):
        lines.append("\n**3.** أضف المفاتيح في ملف `.env`:")
        lines.append("```")
        for key in info["config_keys"]:
            lines.append(f"{key}=your_value_here")
        lines.append("```")

    # Step 3: Restart
    lines.append("\n**4.** أعد تشغيل الوكيل\n")

    # Check current status
    has_keys = all(
        bool(os.getenv(k, "").strip())
        for k in info.get("config_keys", [])
        if k != "GDRIVE_CREDENTIALS"
    )
    if service == "gdrive":
        has_keys = (_ROOT / "credentials.json").exists()

    if has_keys:
        lines.append("✅ **الحالة الحالية:** المفاتيح موجودة — الخدمة جاهزة للاستخدام!")
        # Mark as connected
        config = _load_config()
        config["integrations"][service] = {"enabled": True}
        _save_config(config)
    else:
        lines.append("⚪ **الحالة الحالية:** المفاتيح غير موجودة — يرجى إكمال الخطوات أعلاه")

    # Show available tools
    if info.get("tools"):
        lines.append(f"\n**الأدوات المتاحة بعد الربط:** {', '.join(f'`{t}`' for t in info['tools'])}")

    return "\n".join(lines)


def add_custom_integration(name: str, url: str, description: str = "") -> str:
    """Add a custom integration (webhook, API, etc.)."""
    config = _load_config()
    custom_list = config.get("custom", [])

    # Check for duplicate
    for existing in custom_list:
        if existing.get("name", "").lower() == name.lower():
            return f"❌ تكامل مخصص بنفس الاسم موجود بالفعل: `{name}`"

    new_integration = {
        "name": name,
        "icon": "🔗",
        "url": url,
        "description": description or f"تكامل مخصص: {name}",
        "enabled": True,
        "type": "custom",
    }

    custom_list.append(new_integration)
    config["custom"] = custom_list
    _save_config(config)

    return (
        f"✅ **تم إضافة التكامل المخصص بنجاح!**\n\n"
        f"  🔗 **{name}**\n"
        f"  📎 الرابط: `{url}`\n"
        f"  📝 {description or '—'}\n\n"
        "يمكنك الآن استخدام هذا الرابط مع أدوات المتصفح أو الشبكة."
    )


def disconnect_integration(service: str) -> str:
    """Remove a service connection."""
    service = service.lower().strip()
    config = _load_config()

    # Check builtin
    if service in BUILTIN_INTEGRATIONS:
        if service in config.get("integrations", {}):
            del config["integrations"][service]
            _save_config(config)
            name = BUILTIN_INTEGRATIONS[service]["name"]
            return f"✅ تم فصل **{name}** بنجاح.\n\n⚠️ ملاحظة: المفاتيح لا تزال في `.env` — احذفها يدوياً إذا أردت."
        return f"ℹ️ **{BUILTIN_INTEGRATIONS[service]['name']}** غير متصل أصلاً."

    # Check custom
    custom_list = config.get("custom", [])
    for i, c in enumerate(custom_list):
        if c.get("name", "").lower() == service:
            removed = custom_list.pop(i)
            config["custom"] = custom_list
            _save_config(config)
            return f"✅ تم حذف التكامل المخصص **{removed['name']}** بنجاح."

    available = ", ".join(f"`{k}`" for k in BUILTIN_INTEGRATIONS.keys())
    return f"❌ خدمة غير معروفة: `{service}`\n\nالخدمات المتاحة: {available}"
