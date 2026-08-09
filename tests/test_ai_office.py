"""
AI Office tests — run with:  python -m unittest tests.test_ai_office

The model call is mocked (ai_office._LLM_INVOKER) so these are deterministic and
free — they verify the JSON contract, the precision guards, and that Excel / Word
/ PowerPoint render correctly from a spec, in Arabic and English.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import ai_office as ai  # noqa: E402
from core import office_convert as oc  # noqa: E402


def _mock(reply: str):
    """Install a fake model that returns `reply` regardless of input."""
    ai._LLM_INVOKER = lambda messages: reply


def _unmock():
    ai._LLM_INVOKER = None


class JsonExtraction(unittest.TestCase):
    def tearDown(self):
        _unmock()

    def test_plain_json(self):
        self.assertEqual(ai.extract_json('{"a":1}'), {"a": 1})

    def test_fenced_json(self):
        self.assertEqual(ai.extract_json("```json\n{\"a\": 2}\n```"), {"a": 2})

    def test_json_with_prose(self):
        txt = "Sure! Here it is:\n{\"x\": [1,2,3]}\nHope that helps."
        self.assertEqual(ai.extract_json(txt), {"x": [1, 2, 3]})

    def test_array_json(self):
        self.assertEqual(ai.extract_json("prefix [1, 2] suffix"), [1, 2])

    def test_bad_json_raises(self):
        with self.assertRaises(ValueError):
            ai.extract_json("no json here at all")


class TablePlanning(unittest.TestCase):
    def tearDown(self):
        _unmock()

    def test_plan_table_ok(self):
        _mock(json.dumps({
            "title": "المستفيدون", "sheet_name": "قائمة", "rtl": True,
            "header": ["الاسم", "العدد"],
            "rows": [["مخيم أ", 120], ["مخيم ب", 85]],
        }, ensure_ascii=False))
        spec = ai.plan_table("نظّم", "raw")
        self.assertEqual(spec["header"], ["الاسم", "العدد"])
        self.assertEqual(len(spec["rows"]), 2)
        self.assertTrue(spec["rtl"])
        self.assertIn("_model", spec)

    def test_plan_table_pads_ragged_rows(self):
        _mock(json.dumps({
            "header": ["A", "B", "C"],
            "rows": [["1"], ["2", "3", "4", "5"]],
        }))
        spec = ai.plan_table("x", "y")
        self.assertTrue(all(len(r) == 3 for r in spec["rows"]))  # precision guard

    def test_plan_table_invalid_raises(self):
        _mock('{"header": "notalist", "rows": []}')
        with self.assertRaises(ValueError):
            ai.plan_table("x", "y")


class DocPlanning(unittest.TestCase):
    def tearDown(self):
        _unmock()

    def test_plan_document_ok(self):
        _mock(json.dumps({
            "title": "تقرير", "rtl": True,
            "sections": [{"heading": "مقدمة", "paragraphs": ["نص"], "bullets": ["نقطة"]}],
        }, ensure_ascii=False))
        spec = ai.plan_document("اكتب", "data")
        self.assertEqual(len(spec["sections"]), 1)
        self.assertTrue(spec["rtl"])

    def test_plan_document_missing_sections_raises(self):
        _mock('{"title": "x"}')
        with self.assertRaises(ValueError):
            ai.plan_document("a", "b")


class Renderers(unittest.TestCase):
    """Render tools end-to-end with a mocked model — real files on disk."""
    def setUp(self):
        self.d = tempfile.mkdtemp()
        # tools use resolve_output_path; give absolute paths so output lands here

    def tearDown(self):
        _unmock()

    def test_ai_to_excel(self):
        from tools.ai_office_tools import ai_to_excel
        _mock(json.dumps({
            "title": "توزيع السلال", "sheet_name": "توزيع", "rtl": True,
            "header": ["المخيم", "عدد السلال"],
            "rows": [["الشمال", "١٢٠"], ["الغربي", "٨٥"]],
        }, ensure_ascii=False))
        out = os.path.join(self.d, "aid.xlsx")
        res = ai_to_excel.invoke({"instruction": "نظّم", "data": "خام", "dest": out})
        self.assertIn("✅", res)
        rows = oc.xlsx_to_rows(out)
        # a title row is written first, then the header, then data
        self.assertIn(["المخيم", "عدد السلال"], rows)
        self.assertIn(["الشمال", 120], rows)          # Arabic numerals coerced

    def test_ai_to_word(self):
        from tools.ai_office_tools import ai_to_word
        _mock(json.dumps({
            "title": "تقرير ميداني", "rtl": True,
            "sections": [
                {"heading": "الملخص", "paragraphs": ["تم التوزيع بنجاح."]},
                {"heading": "الأرقام", "table": {
                    "header": ["البند", "العدد"], "rows": [["أسر", "300"]]}},
            ],
        }, ensure_ascii=False))
        out = os.path.join(self.d, "report.docx")
        res = ai_to_word.invoke({"instruction": "اكتب", "data": "خام", "dest": out})
        self.assertIn("✅", res)
        self.assertTrue(os.path.exists(out))
        tabs = oc.docx_tables_to_rows(out)
        self.assertEqual(tabs[0][0], ["البند", "العدد"])

    def test_ai_to_powerpoint(self):
        from tools.ai_office_tools import ai_to_powerpoint
        _mock(json.dumps({
            "title": "عرض المشروع", "rtl": True,
            "sections": [{"heading": "الأهداف", "bullets": ["هدف 1", "هدف 2"]}],
        }, ensure_ascii=False))
        out = os.path.join(self.d, "deck.pptx")
        res = ai_to_powerpoint.invoke({"instruction": "جهّز", "data": "خام", "dest": out})
        self.assertIn("✅", res)
        from pptx import Presentation
        prs = Presentation(out)
        self.assertGreaterEqual(len(prs.slides), 2)   # title + 1 section

    def test_ai_office_dispatch(self):
        from tools.ai_office_tools import ai_office
        _mock(json.dumps({"header": ["A"], "rows": [["1"]]}))
        out = os.path.join(self.d, "d.xlsx")
        res = ai_office.invoke({"instruction": "x", "data": "y",
                                "output": "excel", "dest": out})
        self.assertIn("✅", res)
        self.assertTrue(os.path.exists(out))

    def test_ai_office_bad_output(self):
        from tools.ai_office_tools import ai_office
        res = ai_office.invoke({"instruction": "x", "data": "y",
                                "output": "mp3", "dest": "z"})
        self.assertIn("❌", res)


class ProviderPolicy(unittest.TestCase):
    def test_default_order_strong_first_free_last(self):
        order = ai._provider_order()
        self.assertEqual(order[0], "anthropic")       # strongest first
        self.assertEqual(order[-1], "omniroute")      # free fallback last

    def test_omniroute_always_available(self):
        self.assertTrue(ai._has_key("omniroute"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
