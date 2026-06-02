"""
Deduplication utilities for preventing repeated tool calls and duplicate messages.

Prevents:
  1. Calling the same tool with identical parameters multiple times
  2. Sending identical AI messages consecutively
  3. Tool call loops where the same action repeats endlessly
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from langchain_core.messages import AIMessage, BaseMessage


def _hash_content(content: str) -> str:
    """Create a hash of content for comparison."""
    return hashlib.md5(content.encode()).hexdigest()


def _normalize_args(args: dict) -> dict:
    """
    Strip falsy / default-equivalent values from args before comparison.

    Many tools have optional args with defaults (e.g. browser_screenshot has
    path='' and full_page=False).  When the LLM omits those args it sends {},
    but when it explicitly passes the default values it sends {"path": "",
    "full_page": false}.  Both calls are functionally identical, so after
    normalization both become {} and the duplicate-check fires correctly.

    We ONLY strip values that are clearly "no-op" defaults:
      None, empty string "", False, 0, empty list []
    We keep meaningful falsy values via a whitelist approach where needed.
    """
    return {
        k: v
        for k, v in args.items()
        if v is not None and v != "" and v is not False and v != 0 and v != []
    }


def is_duplicate_tool_call(
    tool_name: str,
    tool_args: dict,
    tool_history: list[dict],
    recent_count: int = 2,
) -> bool:
    """
    Check if this tool has been called with functionally-identical args in the
    last N calls.

    Uses _normalize_args() so that explicit defaults (path='', full_page=False)
    are treated as equivalent to omitted args ({}).  This is the key fix for
    browser_screenshot looping: {} and {"path":"","full_page":false} now match.

    Args:
        tool_name: Name of the tool being called
        tool_args: Arguments being passed (raw from LLM)
        tool_history: List of recent tool calls (from state)
        recent_count: How many recent calls to check (default 2)

    Returns:
        True if duplicate found, False otherwise
    """
    if not tool_history:
        return False

    # Normalize the incoming args once
    norm_new = _normalize_args(tool_args)

    # Get the last N tool calls
    recent_calls = tool_history[-recent_count:]

    for call in recent_calls:
        if call.get("name") == tool_name:
            # Compare normalized args (strips empty-string / False / None defaults)
            try:
                saved_args  = call.get("args", {})
                norm_saved  = _normalize_args(saved_args)
                if json.dumps(norm_new, sort_keys=True) == json.dumps(norm_saved, sort_keys=True):
                    return True
            except (TypeError, ValueError):
                # If we can't compare, consider it different
                pass

    return False


def is_duplicate_message(
    new_message: BaseMessage,
    recent_messages: list[BaseMessage],
    min_length: int = 10,
    similarity_threshold: float = 0.70,
) -> bool:
    """
    Check if this message is identical or very similar to a recent message.
    Uses both exact matching and semantic similarity.

    Args:
        new_message: The message to check
        recent_messages: List of recent messages to compare against (last 10)
        min_length: Minimum content length to consider (skip very short messages)
        similarity_threshold: How similar messages must be to count as duplicate (0.0-1.0)

    Returns:
        True if duplicate found, False otherwise
    """
    if not isinstance(new_message, AIMessage):
        return False

    new_content = new_message.content
    if isinstance(new_content, str) and len(new_content) < min_length:
        return False

    new_str = str(new_content).lower().strip()
    new_hash = _hash_content(new_str)

    # Check against last 5 AI messages
    for msg in recent_messages[-5:]:
        if isinstance(msg, AIMessage):
            old_content = msg.content
            if isinstance(old_content, str):
                old_str = str(old_content).lower().strip()
                old_hash = _hash_content(old_str)

                # Exact match
                if new_hash == old_hash:
                    return True

                # Semantic similarity (character overlap)
                if len(new_str) > min_length and len(old_str) > min_length:
                    # Calculate Jaccard similarity
                    similarity = _calculate_similarity(new_str, old_str)
                    if similarity >= similarity_threshold:
                        return True

    return False


def _calculate_similarity(text1: str, text2: str) -> float:
    """
    Calculate similarity between two texts using Jaccard similarity on bigrams.
    Returns value between 0.0 and 1.0.
    """
    # Create bigrams (2-char sequences)
    def get_bigrams(text: str) -> set[str]:
        return set(text[i:i+2] for i in range(len(text)-1))

    bigrams1 = get_bigrams(text1)
    bigrams2 = get_bigrams(text2)

    if not bigrams1 or not bigrams2:
        return 0.0

    # Jaccard similarity = intersection / union
    intersection = len(bigrams1 & bigrams2)
    union = len(bigrams1 | bigrams2)

    return intersection / union if union > 0 else 0.0


def record_tool_call(
    tool_name: str,
    tool_args: dict,
    result: str | None = None,
    tool_history: list[dict] | None = None,
    max_history: int = 20,
) -> list[dict]:
    """
    Record a tool call in the history (keeps last N calls).

    Args:
        tool_name: Name of the tool
        tool_args: Arguments passed
        result: The result (optional, for logging)
        tool_history: Existing history list (will be updated)
        max_history: Maximum calls to keep (default 20)

    Returns:
        Updated tool history (last N calls)
    """
    import time

    if tool_history is None:
        tool_history = []

    call_record = {
        "name": tool_name,
        "args": tool_args,
        "timestamp": time.time(),
        "result": result[:100] if result else None,  # Keep first 100 chars of result
    }

    # Add to history and keep only last N
    tool_history = list(tool_history) + [call_record]
    return tool_history[-max_history:]


def get_duplicate_prevention_status(
    state: dict,
) -> dict:
    """
    Analyze the state for duplicate patterns and return a summary.

    Returns:
        {
            "recent_tool": str,  # Last tool called
            "tool_calls_last_iteration": int,  # How many times called in last iteration
            "message_streak": int,  # How many identical messages in a row
            "is_at_risk": bool,  # True if patterns suggest looping
        }
    """
    tool_history = state.get("tool_call_history", [])
    messages = state.get("messages", [])
    last_tool = state.get("last_tool_name", "")

    # Count recent calls to same tool
    recent_count = 0
    if tool_history and last_tool:
        for call in tool_history[-5:]:
            if call.get("name") == last_tool:
                recent_count += 1

    # Count identical messages in a row
    message_streak = 0
    if len(messages) >= 2:
        for i in range(len(messages) - 1, 0, -1):
            if isinstance(messages[i], AIMessage) and isinstance(messages[i-1], AIMessage):
                if _hash_content(str(messages[i].content)) == _hash_content(str(messages[i-1].content)):
                    message_streak += 1
                else:
                    break

    return {
        "recent_tool": last_tool,
        "tool_calls_last_iteration": recent_count,
        "message_streak": message_streak,
        "is_at_risk": recent_count >= 2 or message_streak >= 2,
    }
