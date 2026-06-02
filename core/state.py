"""
AgentState — Shared state schema for the Ultimate Secure Local OS Executive Agent.

Every node in the LangGraph workflow reads from and writes to this TypedDict.
The `messages` field uses a custom reducer that appends messages while enforcing
a maximum history limit (default 300) to prevent memory exhaustion during long sessions.
"""

from typing import Annotated
from typing_extensions import TypedDict
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage


def _sanitize_tool_pairs(messages: list[BaseMessage]) -> list[BaseMessage]:
    """
    Enforce strict OpenAI-compatible tool message sequencing in the reducer itself.

    Guarantees that the stored state never contains:
      - Orphan ToolMessages (no matching AIMessage.tool_calls)
      - AIMessage.tool_calls without matching ToolMessage responses

    Without this, DeepSeek/OpenAI APIs return 400 errors like:
      "Messages with role 'tool' must be a response to a preceding message with 'tool_calls'"
      "An assistant message with 'tool_calls' must be followed by tool messages..."
    """
    if not messages:
        return messages

    # Index every ToolMessage by tool_call_id (last one wins on collision)
    tool_responses: dict[str, ToolMessage] = {}
    for msg in messages:
        if isinstance(msg, ToolMessage):
            tool_responses[msg.tool_call_id] = msg

    result: list[BaseMessage] = []
    for msg in messages:
        if isinstance(msg, ToolMessage):
            # Skip — will re-insert after the matching AIMessage
            continue

        result.append(msg)

        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            local_seen: set[str] = set()
            for tc in msg.tool_calls:
                tid = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
                if not tid or tid in local_seen:
                    continue
                local_seen.add(tid)
                if tid in tool_responses:
                    result.append(tool_responses[tid])
                else:
                    # Placeholder so the AIMessage tool_call is always answered
                    result.append(ToolMessage(
                        content="[Tool result missing — execution likely failed]",
                        tool_call_id=tid,
                    ))

    return result


def _add_messages_with_limit(left: list[BaseMessage], right: list[BaseMessage] | BaseMessage, max_messages: int = 300) -> list[BaseMessage]:
    """
    Custom reducer for messages that enforces a maximum limit AND tool-pair safety.

    Strategy:
    - Nodes return the FULL message list (history + their additions), not just deltas.
    - If right looks like a complete replacement (larger than left, OR contains a
      "Context summary" marker from _summarize_old_messages), use right as-is.
    - Otherwise append (standard LangGraph behavior for delta updates).
    - Always apply tool-pair sanitization at the end to prevent API 400 errors.
    - Keep first 50 (summaries) + last (max-50) recent if over the limit.

    CRITICAL: The "Context summary" check fixes the summarization bug where
    _summarize_old_messages shrinks 300 msgs → 21, causing right(23) < left(300)
    and the naive heuristic appending instead of replacing.
    """
    # Normalize right to list
    if isinstance(right, BaseMessage):
        right = [right]
    else:
        right = list(right)

    if not right:
        return _sanitize_tool_pairs(list(left))

    # Detect if this is an authoritative replacement (vs a delta append).
    # Case 1: right is larger — normal growth, clearly a replacement.
    # Case 2: right contains a "Context summary" — _summarize_old_messages ran
    #         and condensed old messages; the smaller right IS the full history.
    has_summary = any(
        isinstance(m, AIMessage) and "Context summary" in str(m.content)
        for m in right
    )
    is_replacement = (len(right) >= len(left) and len(right) > 2) or (has_summary and len(right) > 2)

    if is_replacement:
        combined = list(right)
    else:
        combined = list(left) + list(right)

    if len(combined) > max_messages:
        keep_old = 50
        combined = combined[:keep_old] + combined[-(max_messages - keep_old):]

    # Always sanitize the final result so the stored state is never broken
    return _sanitize_tool_pairs(combined)


def _add_messages(left: list[BaseMessage], right: list[BaseMessage] | BaseMessage) -> list[BaseMessage]:
    """Wrapper for the default add_messages behavior with limit enforcement."""
    return _add_messages_with_limit(left, right, max_messages=300)


class AgentState(TypedDict):
    # ── Conversation history ─────────────────────────────────────────────────
    # Uses custom _add_messages reducer: appends messages while enforcing max 300 limit.
    messages: Annotated[list[BaseMessage], _add_messages]

    # ── Execution plan ───────────────────────────────────────────────────────
    # Ordered list of steps generated by the PlannerNode.
    plan: list[str]

    # ── Progress tracking ────────────────────────────────────────────────────
    # Steps acknowledged as done by the ReviewerNode.
    completed_steps: list[str]

    # ── Working directory ────────────────────────────────────────────────────
    # Absolute path on the Windows machine the agent is operating in.
    workspace: str

    # ── Error log ────────────────────────────────────────────────────────────
    # Accumulates stderr / exception snippets for the ReviewerNode to analyse.
    error_logs: list[str]

    # ── Safety counter ───────────────────────────────────────────────────────
    # Incremented by WorkerNode each cycle. Graph halts at MAX_ITERATIONS.
    iteration_count: int

    # ── Human-in-the-Loop flags ──────────────────────────────────────────────
    # Set to True by WorkerNode when a destructive or CAPTCHA event is detected.
    # Cleared back to False after the user responds via Chainlit UI.
    requires_human_approval: bool

    # Holds the exact command / context string waiting for human review.
    pending_command: str

    # ── Deduplication tracking ───────────────────────────────────────────────
    # Prevents duplicate tool calls and identical messages
    tool_call_history: list[dict]  # Last 20 tool invocations with name, args, timestamp
    last_tool_name: str  # Name of the most recent tool called
    last_tool_args: dict  # Arguments of the most recent tool call
    last_message_content: str  # Hash of the last AI message to prevent exact duplicates
    task_id: str  # Unique ID for current task (changes when task is restarted)
