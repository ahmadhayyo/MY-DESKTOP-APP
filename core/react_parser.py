"""
ReAct Text Parser — Enables tool calling for LLMs without native tool-call support.

When an Ollama model (like tinyllama) doesn't support the OpenAI-style
tool_calls format, the agent falls back to ReAct-style text parsing:

1. Tools are described as text in the system prompt (not via bind_tools).
2. The LLM outputs text like:
       Action: tool_name
       Action Input: {"arg1": "value1", "arg2": "value2"}
3. This module parses that text and constructs synthetic tool_calls.

This allows ANY Ollama model to work as an agent, even without native tool calling.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)


def build_react_tool_prompt(tools: list[BaseTool]) -> str:
    """Build a text description of all tools for ReAct-style prompting."""
    lines = [
        "You have access to the following tools. To use a tool, output EXACTLY this format:",
        "",
        "Thought: (your reasoning about what to do next)",
        "Action: tool_name",
        'Action Input: {"param1": "value1", "param2": "value2"}',
        "",
        "After the tool runs, you will see:",
        "Observation: (tool result)",
        "",
        "Then continue with another Thought/Action or finish with:",
        "Thought: Task is complete.",
        "Final Answer: (summary of what was accomplished)",
        "",
        "IMPORTANT RULES:",
        "- You MUST call at least one tool per turn. Do NOT just describe what you would do.",
        "- Action must be EXACTLY one of the tool names listed below (case-sensitive).",
        "- Action Input must be valid JSON with the correct parameter names.",
        "- Do NOT output multiple Actions in one turn. One Action per turn only.",
        "",
        "Available tools:",
        "=" * 60,
    ]

    for t in tools:
        lines.append(f"\nTool: {t.name}")
        desc = t.description or ""
        if desc:
            lines.append(f"  Description: {desc[:200]}")

        # Extract parameter info from the tool's args_schema
        if hasattr(t, "args_schema") and t.args_schema is not None:
            schema = t.args_schema.schema() if hasattr(t.args_schema, "schema") else {}
            props = schema.get("properties", {})
            required = set(schema.get("required", []))
            if props:
                lines.append("  Parameters:")
                for pname, pinfo in props.items():
                    ptype = pinfo.get("type", "string")
                    pdesc = pinfo.get("description", "")
                    req = " (required)" if pname in required else " (optional)"
                    lines.append(f"    - {pname}: {ptype}{req} — {pdesc[:100]}")

    lines.append("\n" + "=" * 60)
    return "\n".join(lines)


# Regex patterns for parsing ReAct output
_RE_ACTION = re.compile(
    r"Action\s*:\s*(.+?)(?:\n|$)", re.IGNORECASE
)
_RE_ACTION_INPUT = re.compile(
    r"Action\s+Input\s*:\s*(.+?)(?:\n(?:Thought|Action|Observation|Final Answer)|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_RE_FINAL_ANSWER = re.compile(
    r"Final\s+Answer\s*:\s*(.+)",
    re.IGNORECASE | re.DOTALL,
)


def _parse_json_flexible(text: str) -> dict[str, Any]:
    """Try to parse JSON from text, with fallback for common LLM mistakes."""
    text = text.strip()

    # Direct JSON parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting JSON from markdown code block
    md_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if md_match:
        try:
            return json.loads(md_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try extracting anything between { and }
    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    # Last resort: if it looks like a single string argument, wrap it
    if not text.startswith("{"):
        return {"input": text}

    return {}


def parse_react_output(
    response: AIMessage,
    tools_by_name: dict[str, BaseTool],
) -> AIMessage:
    """
    Parse a ReAct-formatted text response and inject synthetic tool_calls.

    If the response contains Action/Action Input, constructs proper tool_calls
    on the AIMessage so the worker_node can execute them normally.

    If no Action is found but there's a Final Answer, returns as-is (conversation).
    """
    content = response.content if isinstance(response.content, str) else ""

    if not content.strip():
        return response

    # Check for Final Answer first (task complete, no tool call needed)
    final_match = _RE_FINAL_ANSWER.search(content)
    action_match = _RE_ACTION.search(content)

    if not action_match:
        # No action found — return as conversational response
        return response

    tool_name = action_match.group(1).strip()

    # Clean up tool name (remove quotes, extra spaces)
    tool_name = tool_name.strip("'\"` ")

    # Parse Action Input
    input_match = _RE_ACTION_INPUT.search(content)
    if input_match:
        raw_input = input_match.group(1).strip()
        tool_args = _parse_json_flexible(raw_input)
    else:
        tool_args = {}

    # Validate tool name exists
    if tool_name not in tools_by_name:
        # Try fuzzy match (case-insensitive)
        lower_map = {k.lower(): k for k in tools_by_name}
        if tool_name.lower() in lower_map:
            tool_name = lower_map[tool_name.lower()]
        else:
            logger.warning("ReAct parser: unknown tool '%s'", tool_name)
            return AIMessage(
                content=(
                    f"[ReAct] Tool '{tool_name}' not found. "
                    f"Available: {', '.join(list(tools_by_name.keys())[:20])}..."
                )
            )

    # Build synthetic tool_call
    tool_call_id = f"react_{uuid.uuid4().hex[:8]}"

    # Extract the thought/reasoning part for the message content
    thought_match = re.search(r"Thought\s*:\s*(.+?)(?:\nAction|\Z)", content, re.IGNORECASE | re.DOTALL)
    thought_text = thought_match.group(1).strip() if thought_match else ""

    # Create AIMessage with synthetic tool_calls
    new_response = AIMessage(
        content=thought_text,
        tool_calls=[
            {
                "id": tool_call_id,
                "name": tool_name,
                "args": tool_args,
            }
        ],
    )

    logger.info("ReAct parsed: %s(%s)", tool_name, json.dumps(tool_args, ensure_ascii=False)[:200])
    return new_response
