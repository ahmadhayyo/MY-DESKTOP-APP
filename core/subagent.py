"""
core/subagent.py — spawn a focused, isolated sub-agent for a subtask.

Like Claude Code's Task tool, this lets the main agent delegate a self-contained
subtask (e.g. "find every place X is defined", "generate 5 test cases and run
them") to a fresh mini-agent that has its OWN short tool-loop and returns just a
summary. This keeps the main agent's context clean and its plan focused.

Design
------
A bounded ReAct loop over the real tool registry:
  system(sub-agent persona + task) → LLM proposes tool calls → execute → feed
  results back → repeat until the LLM answers or ``max_steps`` is hit → return
  the final text.

Safety
------
- Bounded steps (default 6) — cannot run away.
- Recursion guard (contextvar): a sub-agent cannot spawn another sub-agent, so
  there is no fork-bomb. Depth is capped at 1.
- The sub-agent's toolset excludes ``spawn_subagent`` itself.
"""

from __future__ import annotations

from contextvars import ContextVar

_depth: ContextVar[int] = ContextVar("hayo_subagent_depth", default=0)

_MAX_DEPTH = 1
_DEFAULT_MAX_STEPS = 6


def _text(content) -> str:
    """Normalise LLM content (Gemini/Anthropic can return a list of blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, str):
                parts.append(b)
            elif isinstance(b, dict) and b.get("text"):
                parts.append(str(b["text"]))
        return "\n".join(parts)
    return str(content) if content is not None else ""

_SUBAGENT_SYSTEM = (
    "أنت وكيل فرعي مركّز مهمتك تنفيذ مهمة فرعية واحدة محددة ثم تلخيص النتيجة. "
    "استخدم الأدوات المتاحة بكفاءة، لا تخرج عن نطاق المهمة، وعندما تنتهي اكتب ملخصاً "
    "موجزاً وواضحاً بالنتيجة النهائية (بلا خطوات إضافية). لا تطلب توضيحاً — نفّذ بأفضل "
    "تقدير ممكن. You are a focused sub-agent: do the one subtask, then summarize."
)


def _invoke_with_retry(llm, messages, max_retries: int = 4):
    """Invoke the sub-agent LLM, retrying on transient rate-limit (429) errors
    with exponential backoff — so a busy provider (e.g. OpenAI's low TPM tier)
    doesn't abort the whole sub-agent on a momentary limit. Returns the response,
    or an error STRING for unrecoverable failures."""
    import time as _t
    delay = 3.0
    for attempt in range(max_retries + 1):
        try:
            return llm.invoke(messages)
        except Exception as exc:
            msg = str(exc).lower()
            transient = ("429" in msg or "rate limit" in msg or "rate_limit" in msg
                         or "overloaded" in msg or "timeout" in msg or "503" in msg)
            if transient and attempt < max_retries:
                _t.sleep(delay)
                delay = min(delay * 2, 30)
                continue
            return f"❌ sub-agent: خطأ في النموذج: {exc}"


def _subagent_tools():
    """Provider-appropriate tool list, excluding spawn_subagent (no recursion).

    Uses the SAME provider-aware selection as the main worker
    (agent.nodes.tools_for_provider) so a sub-agent can never exceed a capped
    provider's hard tool-count limit (OpenAI/Groq/DeepSeek cap at 128 — binding
    all ~264 tools unconditionally used to throw a 400 error on those providers).
    """
    from tools.registry import ALL_TOOLS
    from agent.nodes import tools_for_provider
    candidates = [t for t in ALL_TOOLS if getattr(t, "name", "") != "spawn_subagent"]
    return tools_for_provider(candidates)


def run_subagent(task: str, max_steps: int = _DEFAULT_MAX_STEPS,
                 context: str = "") -> str:
    """Run a bounded tool-loop for `task` and return the final summary text."""
    if not task or not task.strip():
        return "❌ sub-agent: مهمة فارغة."

    if _depth.get() >= _MAX_DEPTH:
        return ("❌ sub-agent: لا يمكن للوكيل الفرعي أن يستدعي وكيلاً فرعياً آخر "
                "(حماية من التكرار). نفّذ هذه المهمة مباشرةً.")

    from langchain_core.messages import (
        SystemMessage, HumanMessage, AIMessage, ToolMessage,
    )
    from agent.nodes import _get_main_llm
    from tools.registry import TOOLS_BY_NAME

    try:
        llm = _get_main_llm().bind_tools(_subagent_tools())
    except Exception as exc:
        return f"❌ sub-agent: تعذّر تجهيز النموذج: {exc}"

    prompt = task if not context else f"{task}\n\nسياق مفيد:\n{context}"
    messages: list = [
        SystemMessage(content=_SUBAGENT_SYSTEM),
        HumanMessage(content=prompt),
    ]

    steps = max(1, min(int(max_steps or _DEFAULT_MAX_STEPS), 15))
    token = _depth.set(_depth.get() + 1)
    try:
        for _ in range(steps):
            resp = _invoke_with_retry(llm, messages)
            if isinstance(resp, str):   # unrecoverable error message
                return resp
            messages.append(resp)

            tool_calls = getattr(resp, "tool_calls", None) or []
            if not tool_calls:
                text = _text(resp.content)
                return text.strip() or "(الوكيل الفرعي لم يُنتج ملخصاً)"

            for tc in tool_calls:
                name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "")
                args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
                tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", "")
                tool = TOOLS_BY_NAME.get(name)
                if tool is None:
                    result = f"❌ أداة غير معروفة: {name}"
                else:
                    try:
                        result = tool.invoke(args or {})
                    except Exception as exc:
                        result = f"❌ خطأ في تنفيذ {name}: {exc}"
                messages.append(ToolMessage(
                    content=str(result)[:4000], tool_call_id=tc_id or name,
                ))

        # Ran out of steps — ask for a final summary in one more call.
        messages.append(HumanMessage(
            content="انتهت خطوات الوكيل الفرعي. اكتب الآن ملخصاً نهائياً موجزاً بما توصّلت إليه."))
        try:
            final = _get_main_llm().invoke(messages)
            text = _text(final.content)
            return (text.strip() or "(انتهت خطوات الوكيل الفرعي دون ملخص)")
        except Exception:
            return "(انتهت خطوات الوكيل الفرعي دون ملخص نهائي)"
    finally:
        _depth.reset(token)


if __name__ == "__main__":  # import-only smoke test (no network)
    print("max depth:", _MAX_DEPTH, "| default steps:", _DEFAULT_MAX_STEPS)
    # depth guard check
    t = _depth.set(1)
    r = run_subagent("test")
    assert "تكرار" in r or "recursion" in r.lower(), r
    _depth.reset(t)
    print("subagent depth-guard OK")
