"""
Example Plugin — demonstrates how to create custom tools for HAYO AI Agent.

To create your own plugin:
1. Create a new .py file in this plugins/ directory
2. Define PLUGIN_NAME and PLUGIN_DESCRIPTION
3. Create tools using the @tool decorator
4. Export them in a TOOLS list

The agent will automatically load and use your tools!
"""

from langchain_core.tools import tool

PLUGIN_NAME = "Example Plugin"
PLUGIN_DESCRIPTION = "أدوات مثال توضيحي — يمكنك تعديلها أو إنشاء إضافات جديدة"


@tool
def hello_world(name: str = "World") -> str:
    """Say hello to someone. Use this to test that plugins are working."""
    return f"👋 مرحباً {name}! الإضافات تعمل بنجاح."


@tool
def calculate(expression: str) -> str:
    """Evaluate a simple math expression safely.

    Args:
        expression: A math expression like '2 + 2' or '10 * 5'
    """
    allowed = set("0123456789+-*/.() ")
    if not all(c in allowed for c in expression):
        return "❌ تعبير غير صالح. استخدم أرقام وعمليات حسابية فقط."
    try:
        result = eval(expression)  # noqa: S307 — safe: only digits & operators
        return f"🔢 {expression} = {result}"
    except Exception as exc:
        return f"❌ خطأ في الحساب: {exc}"


# This list is what the plugin system loads
TOOLS = [hello_world, calculate]
