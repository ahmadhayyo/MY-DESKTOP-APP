"""
Self-diagnostic tool — the agent can verify its OWN capabilities on request.

When the user asks "تأكد من قدراتك" / "run a self-check", the agent calls
self_diagnose() to actually TEST each core subsystem live (not claim it works)
and return a PASS/FAIL report — the same honesty principle Claude Code applies to
its own work.
"""

from __future__ import annotations

from langchain_core.tools import tool


def _run_checks() -> list[tuple[str, bool, str]]:
    """Run the fast capability checks. Returns (name, ok, detail) rows."""
    out: list[tuple[str, bool, str]] = []

    def _check(name, fn):
        try:
            out.append((name, True, fn() or ""))
        except Exception as exc:
            out.append((name, False, f"{type(exc).__name__}: {exc}"))

    def _tools():
        from tools.registry import ALL_TOOLS
        return f"{len(ALL_TOOLS)} أداة محمّلة"

    def _vision():
        from core import vision_analyze
        p = vision_analyze.available_vision_providers()
        assert p, "لا مزوّد رؤية"
        return f"مزوّدو الرؤية: {p}"

    def _skills():
        from core import skills
        n = [s.name for s in skills.load_all()]
        assert n, "لا مهارات"
        return f"{len(n)} مهارة"

    def _todo():
        from core import todo
        todo.clear_todos("_dx"); todo.write_todos("_dx", [{"id": "1", "content": "x", "status": "completed"}])
        ok = todo.progress("_dx") == (1, 1); todo.clear_todos("_dx")
        assert ok
        return "قائمة المهام الحيّة تعمل"

    def _terminal():
        from core import terminal_session
        terminal_session.reset_session("_dx")
        r = terminal_session.run_in_session("echo dx_ok", session_id="_dx", timeout=15)
        terminal_session.reset_session("_dx")
        assert r["output"] == "dx_ok"
        return "الجلسة الطرفية الدائمة تعمل"

    def _gates():
        from core.verify_gate import verification_pending
        assert verification_pending([{"name": "edit_file_replace", "args": {"path": "a.py"}, "result": "[OK]"}]).pending
        return "بوابات التحقق مسلّحة"

    def _search():
        from tools.locate_tools import find_on_computer
        assert isinstance(find_on_computer.invoke({"name": "python", "kind": "app", "deep": False, "max_results": 2}), str)
        return "البحث في كامل الحاسوب يعمل"

    def _provider():
        import os
        from agent.nodes import _build_llm
        prov = os.getenv("MODEL_PROVIDER", "google")
        _build_llm("main", prov)
        return f"المزوّد الحالي '{prov}' جاهز"

    _check("الأدوات (Tools)", _tools)
    _check("الرؤية الحقيقية (Vision)", _vision)
    _check("المهارات (Skills)", _skills)
    _check("قائمة المهام (Todo)", _todo)
    _check("الجلسة الطرفية (Terminal)", _terminal)
    _check("بوابات التحقق (Gates)", _gates)
    _check("البحث في الحاسوب (Search)", _search)
    _check("المزوّد النشط (Provider)", _provider)
    return out


@tool
def self_diagnose() -> str:
    """Run a live self-check of the agent's core capabilities and return a
    PASS/FAIL report. Use when asked to verify/confirm your own capabilities."""
    try:
        rows = _run_checks()
    except Exception as exc:
        return f"❌ self_diagnose: {exc}"
    npass = sum(1 for _, ok, _ in rows if ok)
    lines = [f"🩺 تشخيص ذاتي — {npass}/{len(rows)} قدرة تعمل:"]
    for name, ok, detail in rows:
        icon = "✅" if ok else "❌"
        lines.append(f"  {icon} {name}" + (f" — {detail}" if detail else ""))
    if npass == len(rows):
        lines.append("\nكل القدرات الأساسية جاهزة وتعمل. ✨")
    return "\n".join(lines)
