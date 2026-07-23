"""
Phase 1 robustness tests — run with:  python -m unittest tests.test_phase1_robustness

Covers core/loop_detection.py and core/compaction.py. Uses stdlib unittest only
(no pytest dependency).
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage  # noqa: E402

from core.loop_detection import (  # noqa: E402
    detect_loop,
    detect_error_thrash,
    generate_loop_nudge,
)
from core.compaction import prune_tool_outputs, estimate_tokens  # noqa: E402
from core.verify_gate import verification_pending, generate_verify_nudge  # noqa: E402
from core.verify_gate import (  # noqa: E402
    visual_verification_pending, generate_visual_nudge,
)
from core import todo as _todo_mod  # noqa: E402,F401  (exercised in TodoStoreTests)


def _hist(name, args, n):
    return [{"name": name, "args": dict(args)} for _ in range(n)]


class LoopDetectionTests(unittest.TestCase):
    def test_empty_history(self):
        self.assertEqual(detect_loop([]).severity, "none")
        self.assertEqual(detect_loop(None).severity, "none")

    def test_below_warning(self):
        self.assertEqual(detect_loop(_hist("run_cmd", {"command": "ls"}, 2)).severity, "none")

    def test_warning_at_three(self):
        r = detect_loop(_hist("run_cmd", {"command": "ls"}, 3))
        self.assertEqual(r.severity, "warning")
        self.assertEqual(r.count, 3)
        self.assertEqual(r.tool_names, ["run_cmd"])

    def test_halt_at_five(self):
        r = detect_loop(_hist("run_cmd", {"command": "ls"}, 5))
        self.assertEqual(r.severity, "halt")
        self.assertTrue(r.is_halt)

    def test_distinct_args_never_loop(self):
        hist = [
            {"name": "read_file", "args": {"path": "a"}},
            {"name": "read_file", "args": {"path": "b"}},
            {"name": "read_file", "args": {"path": "c"}},
            {"name": "read_file", "args": {"path": "d"}},
            {"name": "read_file", "args": {"path": "e"}},
        ]
        self.assertEqual(detect_loop(hist).severity, "none")

    def test_cosmetic_fields_stripped(self):
        # Same functional call, different 'brief' each time -> still a loop.
        hist = [
            {"name": "run_cmd", "args": {"command": "ls", "brief": f"listing #{i}"}}
            for i in range(5)
        ]
        self.assertEqual(detect_loop(hist).severity, "halt")

    def test_trailing_run_only(self):
        # Older identical calls broken by a different call -> count resets.
        hist = _hist("run_cmd", {"command": "ls"}, 4)
        hist.append({"name": "read_file", "args": {"path": "x"}})
        self.assertEqual(detect_loop(hist).severity, "none")

    def test_nudge_mentions_tool_and_count(self):
        r = detect_loop(_hist("run_cmd", {"command": "ls"}, 3))
        nudge = generate_loop_nudge(r)
        self.assertIn("run_cmd", nudge)
        self.assertIn("3", nudge)
        self.assertIn("LOOP DETECTED", nudge)

    def test_unhashable_args_do_not_crash(self):
        hist = [{"name": "t", "args": {"nested": {"a": [1, 2]}}} for _ in range(5)]
        self.assertEqual(detect_loop(hist).severity, "halt")


class ErrorThrashTests(unittest.TestCase):
    def test_thrash_with_failing_results_warns(self):
        # Same tool, DIFFERENT args, results keep failing -> warning (never halt).
        hist = [
            {"name": "edit_file_replace", "args": {"old_text": "a"}, "result": "❌ Text not found"},
            {"name": "edit_file_replace", "args": {"old_text": "b"}, "result": "❌ Text not found"},
            {"name": "edit_file_replace", "args": {"old_text": "c"}, "result": "Error: not found"},
            {"name": "edit_file_replace", "args": {"old_text": "d"}, "result": "❌ Text not found"},
        ]
        r = detect_error_thrash(hist)
        self.assertEqual(r.severity, "warning")
        self.assertEqual(r.reason, "error_thrash")
        self.assertEqual(r.tool_names, ["edit_file_replace"])

    def test_thrash_never_halts(self):
        hist = [
            {"name": "edit_file_replace", "args": {"old_text": str(i)}, "result": "❌ failed"}
            for i in range(10)
        ]
        # Even with 10 failing calls, error-thrash stays at warning severity.
        self.assertEqual(detect_error_thrash(hist).severity, "warning")

    def test_successful_results_do_not_thrash(self):
        hist = [
            {"name": "write_file", "args": {"path": f"f{i}"}, "result": "[OK] Wrote"}
            for i in range(4)
        ]
        self.assertEqual(detect_error_thrash(hist).severity, "none")

    def test_identical_calls_left_to_detect_loop(self):
        # All-identical is detect_loop's job, not error-thrash.
        hist = [
            {"name": "run_cmd", "args": {"command": "x"}, "result": "❌ error"}
            for _ in range(4)
        ]
        self.assertEqual(detect_error_thrash(hist).severity, "none")

    def test_exploration_tools_excluded(self):
        hist = [
            {"name": "read_file", "args": {"path": f"f{i}"}, "result": "not found"}
            for i in range(4)
        ]
        self.assertEqual(detect_error_thrash(hist).severity, "none")

    def test_mixed_tools_do_not_thrash(self):
        hist = [
            {"name": "edit_file_replace", "args": {"old_text": "a"}, "result": "❌ failed"},
            {"name": "run_cmd", "args": {"command": "x"}, "result": "❌ failed"},
            {"name": "edit_file_replace", "args": {"old_text": "b"}, "result": "❌ failed"},
            {"name": "run_cmd", "args": {"command": "y"}, "result": "❌ failed"},
        ]
        self.assertEqual(detect_error_thrash(hist).severity, "none")

    def test_nudge_includes_last_error(self):
        r = detect_error_thrash([
            {"name": "edit_file_replace", "args": {"old_text": str(i)}, "result": "❌ Text not found"}
            for i in range(4)
        ])
        nudge = generate_loop_nudge(r, last_error="Text not found: 'def foo'")
        self.assertIn("REPEATED FAILURE", nudge)
        self.assertIn("Text not found: 'def foo'", nudge)


class CompactionTests(unittest.TestCase):
    def _big(self, tokens):
        # Build varied text sized to an ACTUAL measured token count, so the
        # fixture is independent of whether tiktoken (which compresses repeated
        # characters heavily) or the chars/4 fallback is in use. Measure the
        # per-unit cost ONCE, then build directly (avoid O(n^2) re-encoding).
        unit = "lorem ipsum dolor sit amet consectetur adipiscing elit "
        per_unit = max(1, estimate_tokens(unit))
        reps = tokens // per_unit + 2
        return unit * reps

    def test_estimate_tokens_nonzero(self):
        self.assertGreater(estimate_tokens("hello world this is text"), 0)
        self.assertEqual(estimate_tokens(""), 0)

    def test_prunes_old_keeps_recent(self):
        msgs = [
            AIMessage(content="", tool_calls=[{"id": "1", "name": "run_cmd", "args": {}}]),
            ToolMessage(content=self._big(60_000), tool_call_id="1"),
            AIMessage(content="", tool_calls=[{"id": "2", "name": "run_cmd", "args": {}}]),
            ToolMessage(content="recent small output", tool_call_id="2"),
        ]
        out, res = prune_tool_outputs(msgs, token_budget=40_000, min_savings=8_000)
        self.assertEqual(res.pruned_count, 1)
        self.assertTrue(out[1].content.startswith("[⚠️"))
        self.assertEqual(out[3].content, "recent small output")
        # tool_call_id preserved so tool/AI pairing stays valid.
        self.assertEqual(out[1].tool_call_id, "1")

    def test_idempotent(self):
        msgs = [
            AIMessage(content="", tool_calls=[{"id": "1", "name": "run_cmd", "args": {}}]),
            ToolMessage(content=self._big(60_000), tool_call_id="1"),
            AIMessage(content="", tool_calls=[{"id": "2", "name": "run_cmd", "args": {}}]),
            ToolMessage(content=self._big(60_000), tool_call_id="2"),
        ]
        out, _ = prune_tool_outputs(msgs, token_budget=40_000, min_savings=8_000)
        _, res2 = prune_tool_outputs(out, token_budget=40_000, min_savings=8_000)
        self.assertEqual(res2.pruned_count, 0)

    def test_protected_tools_never_pruned(self):
        msgs = [
            AIMessage(content="", tool_calls=[{"id": "1", "name": "recall_facts", "args": {}}]),
            ToolMessage(content=self._big(60_000), tool_call_id="1"),
            AIMessage(content="", tool_calls=[{"id": "2", "name": "run_cmd", "args": {}}]),
            ToolMessage(content="recent", tool_call_id="2"),
        ]
        out, res = prune_tool_outputs(msgs, token_budget=40_000, min_savings=8_000)
        self.assertEqual(res.pruned_count, 0)
        self.assertEqual(out[1].content, msgs[1].content)  # untouched

    def test_within_budget_skips(self):
        msgs = [
            AIMessage(content="", tool_calls=[{"id": "1", "name": "run_cmd", "args": {}}]),
            ToolMessage(content="tiny", tool_call_id="1"),
        ]
        _, res = prune_tool_outputs(msgs, token_budget=40_000, min_savings=8_000)
        self.assertEqual(res.skip_reason, "within-budget")

    def test_below_minimum_savings_skips(self):
        # Recent output fills the budget; the only older (prunable) output is
        # small, so total savings fall below min_savings -> skip pruning.
        old_out = self._big(3_000)
        recent_out = self._big(9_000)
        t_old = estimate_tokens(old_out)
        t_recent = estimate_tokens(recent_out)
        msgs = [
            AIMessage(content="", tool_calls=[{"id": "1", "name": "run_cmd", "args": {}}]),
            ToolMessage(content=old_out, tool_call_id="1"),     # old, overflow
            AIMessage(content="", tool_calls=[{"id": "2", "name": "run_cmd", "args": {}}]),
            ToolMessage(content=recent_out, tool_call_id="2"),  # recent, fills budget
        ]
        # Budget = recent size (recent just fits); min_savings above the old
        # output size, so pruning the old overflow saves too little -> skip.
        _, res = prune_tool_outputs(
            msgs, token_budget=t_recent, min_savings=t_old + 1
        )
        self.assertEqual(res.skip_reason, "below-minimum-savings")

    def test_no_tool_messages(self):
        msgs = [HumanMessage(content="hi"), AIMessage(content="hello")]
        out, res = prune_tool_outputs(msgs)
        self.assertEqual(res.skip_reason, "no-tool-outputs")
        self.assertIs(out, msgs)


class VerifyGateTests(unittest.TestCase):
    """core/verify_gate.py — enforce the 'verify' leg of explore→edit→verify."""

    def _edit(self, path, result="[OK] edited"):
        return {"name": "edit_file_replace", "args": {"path": path}, "result": result}

    def _run(self, result="ok"):
        return {"name": "run_python", "args": {"code": "x"}, "result": result}

    def test_empty_history_not_pending(self):
        self.assertFalse(verification_pending([]).pending)
        self.assertFalse(verification_pending(None).pending)

    def test_edit_without_run_is_pending(self):
        g = verification_pending([self._edit("main.py")])
        self.assertTrue(g.pending)
        self.assertEqual(g.file, "main.py")

    def test_run_after_edit_clears_even_if_run_failed(self):
        # The gate guarantees a run HAPPENS, not that it passes.
        hist = [self._edit("main.py"), self._run(result="❌ boom")]
        self.assertFalse(verification_pending(hist).pending)

    def test_failed_edit_does_not_arm(self):
        hist = [self._edit("a.py", result="❌ Text not found")]
        self.assertFalse(verification_pending(hist).pending)

    def test_non_runnable_file_does_not_arm(self):
        for path in ("notes.md", "data.json", "page.html", "style.css"):
            self.assertFalse(
                verification_pending([self._edit(path)]).pending, path
            )

    def test_blocked_edit_prefix_excluded(self):
        hist = [{"name": "BLOCKED:edit_file_replace",
                 "args": {"path": "a.py"}, "result": "⛔ blocked"}]
        self.assertFalse(verification_pending(hist).pending)

    def test_latest_edit_wins(self):
        hist = [
            self._edit("a.py"), self._run(),          # a.py verified
            self._edit("b.py"),                        # b.py not verified
        ]
        g = verification_pending(hist)
        self.assertTrue(g.pending)
        self.assertEqual(g.file, "b.py")

    def test_disabled_via_env(self):
        os.environ["HAYO_VERIFY_GATE"] = "0"
        try:
            self.assertFalse(verification_pending([self._edit("main.py")]).pending)
        finally:
            os.environ.pop("HAYO_VERIFY_GATE", None)

    def test_nudge_mentions_file(self):
        g = verification_pending([self._edit("app/server.py")])
        self.assertIn("app/server.py", generate_verify_nudge(g))


class VisualGateTests(unittest.TestCase):
    """core/verify_gate.py — the visual 'look at it' leg (build→run→SEE→fix).

    visual_is_enabled() needs a vision provider; force one on via a dummy key so
    the gate logic is exercised deterministically regardless of the real .env.
    """

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in
                       ("GOOGLE_API_KEY", "HAYO_VISION_PROVIDER", "HAYO_VISUAL_GATE")}
        os.environ["GOOGLE_API_KEY"] = "dummy-key-for-tests"
        os.environ["HAYO_VISION_PROVIDER"] = "google"
        os.environ.pop("HAYO_VISUAL_GATE", None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _run_gui(self, code="import tkinter as tk; tk.Tk().mainloop()", result="ok"):
        return {"name": "run_python", "args": {"code": code}, "result": result}

    def _run_cli(self, code="print(2+2)", result="4"):
        return {"name": "run_python", "args": {"code": code}, "result": result}

    def _analyze(self, result="[VISION:google] looks fine"):
        return {"name": "analyze_screen", "args": {"question": "ok?"}, "result": result}

    def test_empty_not_pending(self):
        self.assertFalse(visual_verification_pending([]).pending)
        self.assertFalse(visual_verification_pending(None).pending)

    def test_gui_run_without_look_is_pending(self):
        self.assertTrue(visual_verification_pending([self._run_gui()]).pending)

    def test_cli_run_does_not_arm(self):
        # A plain compute script is not visual — no look required.
        self.assertFalse(visual_verification_pending([self._run_cli()]).pending)

    def test_analyze_after_run_clears(self):
        hist = [self._run_gui(), self._analyze()]
        self.assertFalse(visual_verification_pending(hist).pending)

    def test_failed_gui_run_does_not_arm(self):
        hist = [self._run_gui(result="❌ ImportError")]
        self.assertFalse(visual_verification_pending(hist).pending)

    def test_web_server_signal_arms(self):
        hist = [{"name": "run_cmd",
                 "args": {"command": "streamlit run app.py"}, "result": "ok"}]
        self.assertTrue(visual_verification_pending(hist).pending)

    def test_html_run_arms(self):
        hist = [{"name": "run_script",
                 "args": {"path": "site/index.html"}, "result": "ok"}]
        self.assertTrue(visual_verification_pending(hist).pending)

    def test_android_launch_arms(self):
        # Launching an app on the emulator must be visually confirmed.
        hist = [{"name": "android_launch_app",
                 "args": {"package": "com.example"}, "result": "[OK] launched"}]
        self.assertTrue(visual_verification_pending(hist).pending)

    def test_android_screenshot_clears(self):
        hist = [{"name": "android_install_apk", "args": {"path": "app.apk"}, "result": "[OK]"},
                {"name": "android_screenshot", "args": {}, "result": "[OK] saved"}]
        self.assertFalse(visual_verification_pending(hist).pending)

    def test_adb_via_terminal_run_arms(self):
        hist = [{"name": "terminal_run",
                 "args": {"command": "adb shell am start com.example/.Main"}, "result": "ok"}]
        self.assertTrue(visual_verification_pending(hist).pending)

    def test_android_nudge_mentions_emulator_screenshot(self):
        hist = [{"name": "android_launch_app",
                 "args": {"package": "com.example"}, "result": "[OK]"}]
        nudge = generate_visual_nudge(visual_verification_pending(hist))
        self.assertIn("android_screenshot", nudge)

    def test_build_desktop_app_arms(self):
        hist = [{"name": "build_desktop_app",
                 "args": {"path": "app.py"}, "result": "[OK] built"}]
        self.assertTrue(visual_verification_pending(hist).pending)

    def test_latest_run_wins(self):
        hist = [self._run_gui(), self._analyze(),          # first GUI seen
                {"name": "run_cmd", "args": {"command": "flask run"}, "result": "ok"}]
        self.assertTrue(visual_verification_pending(hist).pending)

    def test_disabled_via_env(self):
        os.environ["HAYO_VISUAL_GATE"] = "0"
        self.assertFalse(visual_verification_pending([self._run_gui()]).pending)

    def test_dormant_without_vision_provider(self):
        # No vision provider available → gate stays dormant even for a GUI run.
        # Mock the provider check so the test is independent of the real .env
        # (which may legitimately have a vision key configured).
        import core.vision_analyze as _va
        from unittest.mock import patch
        with patch.object(_va, "available_vision_providers", return_value=[]):
            self.assertFalse(visual_verification_pending([self._run_gui()]).pending)

    def test_nudge_mentions_tools(self):
        g = visual_verification_pending([self._run_gui()])
        nudge = generate_visual_nudge(g)
        self.assertIn("analyze_screen", nudge)


class TodoStoreTests(unittest.TestCase):
    """core/todo.py — the live self-updating task checklist."""

    def setUp(self):
        from core import todo
        self.todo = todo
        self.tid = "test-task"
        todo.clear_todos(self.tid)

    def tearDown(self):
        self.todo.clear_todos(self.tid)

    def test_write_and_progress(self):
        self.todo.write_todos(self.tid, [
            {"id": "1", "content": "a", "status": "completed"},
            {"id": "2", "content": "b", "status": "in_progress"},
            {"id": "3", "content": "c", "status": "pending"},
        ])
        self.assertEqual(self.todo.progress(self.tid), (1, 3))

    def test_status_only_update_merges_keeps_content(self):
        self.todo.write_todos(self.tid, [
            {"id": "1", "content": "build", "status": "pending"},
            {"id": "2", "content": "test", "status": "pending"},
        ])
        # partial: no content → must merge, not wipe
        self.todo.write_todos(self.tid, [{"id": "1", "status": "completed"}])
        items = {t["id"]: t for t in self.todo.get_todos(self.tid)}
        self.assertEqual(items["1"]["content"], "build")
        self.assertEqual(items["1"]["status"], "completed")
        self.assertEqual(items["2"]["content"], "test")  # untouched

    def test_replace_semantics_when_full(self):
        self.todo.write_todos(self.tid, [{"id": "1", "content": "old", "status": "pending"}])
        self.todo.write_todos(self.tid, [
            {"id": "9", "content": "new", "status": "pending"}], merge=False)
        ids = [t["id"] for t in self.todo.get_todos(self.tid)]
        self.assertEqual(ids, ["9"])

    def test_status_normalisation(self):
        self.todo.write_todos(self.tid, [
            {"id": "1", "content": "x", "status": "doing"},
            {"id": "2", "content": "y", "status": "done"},
        ])
        st = {t["id"]: t["status"] for t in self.todo.get_todos(self.tid)}
        self.assertEqual(st["1"], "in_progress")
        self.assertEqual(st["2"], "completed")

    def test_all_complete(self):
        self.todo.write_todos(self.tid, [
            {"id": "1", "content": "x", "status": "completed"},
            {"id": "2", "content": "y", "status": "cancelled"},
        ])
        self.assertTrue(self.todo.all_complete(self.tid))  # cancelled ignored

    def test_render_contains_content(self):
        self.todo.write_todos(self.tid, [{"id": "1", "content": "احفظ الملف", "status": "pending"}])
        self.assertIn("احفظ الملف", self.todo.render(self.tid))

    def test_render_markdown_strikes_completed(self):
        self.todo.write_todos(self.tid, [
            {"id": "1", "content": "done item", "status": "completed"},
            {"id": "2", "content": "active item", "status": "in_progress"},
            {"id": "3", "content": "todo item", "status": "pending"},
        ])
        md = self.todo.render_markdown(self.tid)
        self.assertIn("~~done item~~", md)          # struck through
        self.assertIn("**active item**", md)         # bold in-progress
        self.assertIn("todo item", md)
        self.assertIn("1/3", md)                     # count header

    def test_active_task_tracks_last(self):
        self.todo.set_current_task("some-active-task")
        self.assertEqual(self.todo.active_task(), "some-active-task")

    def test_context_var_binds_default_task(self):
        self.todo.set_current_task("ctx-task")
        self.todo.clear_todos("ctx-task")
        self.todo.write_todos("", [{"id": "1", "content": "z", "status": "pending"}])
        self.assertEqual(len(self.todo.get_todos("")), 1)
        self.todo.clear_todos("ctx-task")


class BudgetGuardTests(unittest.TestCase):
    """core/budget.py — per-task token spend cap."""

    def setUp(self):
        from core import budget
        self.budget = budget
        self._saved = os.environ.get("HAYO_TASK_TOKEN_BUDGET")
        os.environ["HAYO_TASK_TOKEN_BUDGET"] = "1000"
        budget.reset("bt")

    def tearDown(self):
        self.budget.reset("bt")
        if self._saved is None:
            os.environ.pop("HAYO_TASK_TOKEN_BUDGET", None)
        else:
            os.environ["HAYO_TASK_TOKEN_BUDGET"] = self._saved

    def test_accumulates_and_reports_remaining(self):
        self.budget.add_tokens("bt", 300)
        self.assertEqual(self.budget.remaining("bt"), 700)
        self.assertFalse(self.budget.over_budget("bt"))

    def test_halts_when_exceeded(self):
        self.budget.add_tokens("bt", 1200)
        self.assertTrue(self.budget.over_budget("bt"))

    def test_reset_clears(self):
        self.budget.add_tokens("bt", 1200)
        self.budget.reset("bt")
        self.assertEqual(self.budget.used("bt"), 0)
        self.assertFalse(self.budget.over_budget("bt"))

    def test_disabled_when_zero(self):
        os.environ["HAYO_TASK_TOKEN_BUDGET"] = "0"
        self.budget.add_tokens("bt", 99999)
        self.assertFalse(self.budget.over_budget("bt"))
        self.assertFalse(self.budget.is_enabled())

    def test_add_text_estimates_tokens(self):
        before = self.budget.used("bt")
        self.budget.add_text("bt", "x" * 400)  # ~100 tokens at chars/4
        self.assertGreater(self.budget.used("bt"), before)


class TerminalSessionTests(unittest.TestCase):
    """core/terminal_session.py — persistent stateful shell (Windows)."""

    def setUp(self):
        from core import terminal_session
        self.ts = terminal_session
        self.sid = "unittest"
        self.ts.reset_session(self.sid)

    def tearDown(self):
        self.ts.reset_session(self.sid)

    def test_basic_command(self):
        r = self.ts.run_in_session("echo hi", session_id=self.sid, timeout=15)
        self.assertEqual(r["output"], "hi")
        self.assertEqual(r["exit_code"], 0)
        self.assertFalse(r["timed_out"])

    def test_state_persists_between_calls(self):
        self.ts.run_in_session("set UT_VAR=persisted", session_id=self.sid, timeout=15)
        r = self.ts.run_in_session("echo %UT_VAR%", session_id=self.sid, timeout=15)
        self.assertEqual(r["output"], "persisted")

    def test_exit_code_captured(self):
        r = self.ts.run_in_session("cmd /c exit 5", session_id=self.sid, timeout=15)
        self.assertEqual(r["exit_code"], 5)

    def test_timeout_does_not_hang(self):
        # A 30s ping with a 2s timeout must return timed_out quickly, not block.
        import time as _t
        start = _t.time()
        r = self.ts.run_in_session("ping -n 30 127.0.0.1", session_id=self.sid, timeout=2)
        self.assertTrue(r["timed_out"])
        self.assertLess(_t.time() - start, 12)  # generous bound; must not hang 30s
        self.ts.reset_session(self.sid)  # wedged session cleaned


if __name__ == "__main__":
    unittest.main(verbosity=2)
