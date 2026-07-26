"""
core/compaction.py — Rolling tool-output pruning to protect the context window.

Ported and adapted from HackerAI's `lib/chat/compaction/prune-tool-outputs.ts`.

Problem this solves
-------------------
This agent has tools that emit very large outputs (scans, browser snapshots,
office/OCR extraction, directory listings). The existing `_summarize_old_messages`
condenses *whole messages* only once the count exceeds MAX_HISTORY, and a single
giant ToolMessage can blow the context window long before that.

Strategy (matches the reference)
--------------------------------
Keep a rolling *token budget* of the most recent tool outputs fully intact.
Walk the messages newest -> oldest; once the cumulative tool-output token count
exceeds the budget, replace the *older* tool outputs with a compact one-line
placeholder (preserving ``tool_call_id`` and ``name`` so tool/AI pairing — and
therefore provider API validity — is never broken).

Guards:
  - Protected tools (memory / notes / todo-style, which carry state the agent
    must reference later) are never pruned.
  - Pruning only happens if it saves at least ``min_savings`` tokens; otherwise
    the overhead is not worth it and the messages are returned unchanged.

The function is idempotent: once an output is a placeholder it is tiny and will
not be pruned again.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

try:
    from config import TOOL_OUTPUT_TOKEN_BUDGET, PRUNE_MIN_SAVINGS
except Exception:  # pragma: no cover - config import guard
    TOOL_OUTPUT_TOKEN_BUDGET = 40_000
    PRUNE_MIN_SAVINGS = 8_000

# Tools whose outputs hold state the agent needs to reference throughout the
# session and must never be pruned.
DEFAULT_PROTECTED_TOOLS = frozenset(
    {
        "recall_facts",
        "remember_fact",
        "list_memory",
        "save_memory",
        "read_memory",
        "list_notes",
        "create_note",
        "update_note",
        "delete_note",
        "todo_write",
        "list_scheduled_tasks",
    }
)

_PLACEHOLDER_TEMPLATE = "[⚠️ مخرجات سابقة مُقلَّمة لتوفير سياق النموذج — ~{tokens} رمز مُوفَّر]"

# Cache the tokenizer encoder once (tiktoken is optional).
_ENCODER = None
_ENCODER_TRIED = False


def estimate_tokens(text: str) -> int:
    """Best-effort token count. Uses tiktoken if available, else ~chars/4."""
    global _ENCODER, _ENCODER_TRIED
    if not text:
        return 0
    if not _ENCODER_TRIED:
        _ENCODER_TRIED = True
        try:
            import tiktoken

            _ENCODER = tiktoken.get_encoding("cl100k_base")
        except Exception:
            _ENCODER = None
    if _ENCODER is not None:
        try:
            return len(_ENCODER.encode(text))
        except Exception:
            pass
    return max(1, len(text) // 4)


@dataclass
class PruneResult:
    """Summary of a pruning pass, for logging/metrics."""

    pruned_count: int = 0
    tokens_saved: int = 0
    total_tool_output_tokens: int = 0
    tool_output_count: int = 0
    skip_reason: str | None = None  # "no-tool-outputs" | "within-budget" | "below-minimum-savings"


def _tool_content_str(msg: ToolMessage) -> str:
    content = msg.content
    if isinstance(content, str):
        return content
    # Multimodal / list content — stringify defensively for token accounting.
    return str(content)


def _build_id_to_tool_name(messages: Iterable[BaseMessage]) -> dict[str, str]:
    """Map each tool_call_id -> the tool name that produced it.

    ToolMessages in this codebase are created without a ``name`` field, so the
    tool name is recovered from the preceding AIMessage's ``tool_calls``.
    """
    mapping: dict[str, str] = {}
    for msg in messages:
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                if isinstance(tc, dict):
                    tid, name = tc.get("id"), tc.get("name")
                else:
                    tid, name = getattr(tc, "id", None), getattr(tc, "name", None)
                if tid and name:
                    mapping[tid] = name
    return mapping


def _already_placeholder(text: str) -> bool:
    return text.startswith("[⚠️ مخرجات سابقة مُقلَّمة")


def prune_tool_outputs(
    messages: list[BaseMessage],
    *,
    token_budget: int = TOOL_OUTPUT_TOKEN_BUDGET,
    min_savings: int = PRUNE_MIN_SAVINGS,
    protected_tools: frozenset[str] = DEFAULT_PROTECTED_TOOLS,
) -> tuple[list[BaseMessage], PruneResult]:
    """Prune old tool outputs beyond a rolling token budget.

    Returns the (possibly rewritten) message list and a :class:`PruneResult`.
    The input list is never mutated; a new list is returned when pruning occurs.
    """
    result = PruneResult()
    if not messages:
        result.skip_reason = "no-tool-outputs"
        return messages, result

    id_to_name = _build_id_to_tool_name(messages)

    # Identify eligible (non-protected, non-placeholder) tool outputs with tokens.
    eligible: list[tuple[int, int]] = []  # (index, tokens)
    for idx, msg in enumerate(messages):
        if not isinstance(msg, ToolMessage):
            continue
        result.tool_output_count += 1
        name = id_to_name.get(msg.tool_call_id, "")
        text = _tool_content_str(msg)
        if name in protected_tools or _already_placeholder(text):
            continue
        toks = estimate_tokens(text)
        result.total_tool_output_tokens += toks
        eligible.append((idx, toks))

    if not eligible:
        result.skip_reason = "no-tool-outputs"
        return messages, result

    # Walk newest -> oldest; keep within budget, mark the rest for pruning.
    cumulative = 0
    to_prune: list[tuple[int, int]] = []
    for idx, toks in reversed(eligible):
        if cumulative + toks <= token_budget:
            cumulative += toks
        else:
            to_prune.append((idx, toks))

    if not to_prune:
        result.skip_reason = "within-budget"
        return messages, result

    projected_savings = sum(toks for _, toks in to_prune)
    if projected_savings < min_savings:
        result.skip_reason = "below-minimum-savings"
        return messages, result

    prune_map = dict(to_prune)
    new_messages: list[BaseMessage] = []
    saved = 0
    for idx, msg in enumerate(messages):
        if idx in prune_map:
            toks = prune_map[idx]
            saved += toks
            new_messages.append(
                ToolMessage(
                    content=_PLACEHOLDER_TEMPLATE.format(tokens=toks),
                    tool_call_id=msg.tool_call_id,
                    name=getattr(msg, "name", None),
                )
            )
        else:
            new_messages.append(msg)

    result.pruned_count = len(to_prune)
    result.tokens_saved = saved
    return new_messages, result


if __name__ == "__main__":  # Lightweight smoke test (no pytest dependency).
    _u = "lorem ipsum dolor sit amet consectetur "
    big = _u * (80_000 // max(1, estimate_tokens(_u)) + 10)  # comfortably > budget
    msgs: list[BaseMessage] = [
        AIMessage(content="", tool_calls=[{"id": "1", "name": "run_powershell", "args": {}}]),
        ToolMessage(content=big, tool_call_id="1"),
        AIMessage(content="", tool_calls=[{"id": "2", "name": "run_powershell", "args": {}}]),
        ToolMessage(content="small recent output", tool_call_id="2"),
    ]
    out, res = prune_tool_outputs(msgs, token_budget=40_000, min_savings=8_000)
    assert res.pruned_count == 1, res
    assert isinstance(out[1], ToolMessage) and out[1].content.startswith("[⚠️"), out[1].content
    assert out[3].content == "small recent output", "recent output must stay intact"
    # Idempotent: second pass prunes nothing.
    _, res2 = prune_tool_outputs(out, token_budget=40_000, min_savings=8_000)
    assert res2.pruned_count == 0, res2
    print("compaction smoke test OK")
