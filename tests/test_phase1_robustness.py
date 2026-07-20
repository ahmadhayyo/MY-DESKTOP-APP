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

from core.loop_detection import detect_loop, generate_loop_nudge  # noqa: E402
from core.compaction import prune_tool_outputs, estimate_tokens  # noqa: E402


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
