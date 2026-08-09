"""
Care Mode tests — run with:  python -m unittest tests.test_care_mode

Covers core/care_mode.py: time parsing, CRUD, the due/missed heartbeat,
adherence, spoken lines, and the Syrian female/male voice switch. Stdlib
unittest only (no pytest dependency), matching the rest of this suite.
"""
import importlib
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _fresh(tmpdir):
    """Reload care_mode bound to an isolated data file."""
    os.environ["CARE_DATA_PATH"] = os.path.join(tmpdir, "care.json")
    import core.care_mode as cm
    importlib.reload(cm)
    return cm


class CareBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.cm = _fresh(self._tmp)

    def slot(self, s):
        return self.cm._slot_epoch(self.cm._today_str(), s)


class TimeParsing(CareBase):
    def test_norm_time_variants(self):
        cases = {"8": "08:00", "08:00": "08:00", "8:5": "08:05",
                 "8 am": "08:00", "8 pm": "20:00", "12 am": "00:00",
                 "12 pm": "12:00", "8 صباحا": "08:00", "8 مساءً": "20:00",
                 "14:30": "14:30"}
        for raw, exp in cases.items():
            self.assertEqual(self.cm._norm_time(raw), exp, raw)

    def test_norm_time_rejects_garbage(self):
        for bad in ("hello", "25:00", ""):
            with self.assertRaises(ValueError):
                self.cm._norm_time(bad)

    def test_norm_times_split_sort(self):
        self.assertEqual(self.cm._norm_times("8 مساءً, 8 صباحا"), ["08:00", "20:00"])
        self.assertEqual(self.cm._norm_times("8 و 14 و 20"), ["08:00", "14:00", "20:00"])


class Crud(CareBase):
    def test_add_and_list(self):
        m = self.cm.add_medication("بانادول", ["8", "20:00"], dose="حبة", with_food=True)
        self.assertEqual(m["times"], ["08:00", "20:00"])
        self.assertTrue(m["with_food"])
        self.assertEqual(len(self.cm.list_medications()), 1)

    def test_add_requires_name_and_time(self):
        with self.assertRaises(ValueError):
            self.cm.add_medication("", ["8"])
        with self.assertRaises(ValueError):
            self.cm.add_medication("x", [])

    def test_remove_by_name_ci(self):
        self.cm.add_medication("Aspirin", ["9"])
        self.assertTrue(self.cm.remove_medication("aspirin"))
        self.assertFalse(self.cm.remove_medication("aspirin"))

    def test_persistence(self):
        self.cm.add_medication("Vitamin", ["10"])
        import core.care_mode as cm2
        importlib.reload(cm2)
        self.assertTrue(any(m["name"] == "Vitamin" for m in cm2.list_medications()))


class Heartbeat(CareBase):
    def test_due_at_slot_time(self):
        self.cm.add_medication("Med", ["08:00"])
        evs = self.cm.due_reminders(now=self.slot("08:00") + 5)
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["kind"], "due")

    def test_not_due_before(self):
        self.cm.add_medication("Med", ["08:00"])
        self.assertEqual(self.cm.due_reminders(now=self.slot("08:00") - 600), [])

    def test_taken_stops(self):
        self.cm.add_medication("Med", ["08:00"])
        t = self.slot("08:00") + 5
        self.assertEqual(len(self.cm.due_reminders(now=t)), 1)
        self.cm.mark("Med", slot="08:00", status="taken")
        self.assertEqual(self.cm.due_reminders(now=t + self.cm.GRACE_MIN * 60 + 3600), [])

    def test_reannounce_throttled(self):
        self.cm.add_medication("Med", ["08:00"])
        base = self.slot("08:00") + 5
        self.assertEqual(len(self.cm.due_reminders(now=base)), 1)
        self.assertEqual(self.cm.due_reminders(now=base + 60), [])
        self.assertEqual(len(self.cm.due_reminders(now=base + self.cm.REPEAT_MIN * 60 + 5)), 1)

    def test_announce_cap(self):
        self.cm.add_medication("Med", ["08:00"])
        base = self.slot("08:00") + 5
        announces = 0
        for i in range(self.cm.MAX_ANNOUNCE + 3):
            evs = self.cm.due_reminders(now=base + i * (self.cm.REPEAT_MIN * 60 + 1))
            announces += sum(1 for e in evs if e["kind"] == "due")
        self.assertLessEqual(announces, self.cm.MAX_ANNOUNCE)

    def test_missed_once(self):
        self.cm.add_medication("Med", ["08:00"])
        t = self.slot("08:00") + self.cm.GRACE_MIN * 60 + 120
        evs = self.cm.due_reminders(now=t)
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["kind"], "missed")
        self.assertEqual(self.cm.due_reminders(now=t + 300), [])

    def test_mark_nearest_slot(self):
        self.cm.add_medication("Med", ["08:00", "20:00"])
        res = self.cm.mark("Med", slot=None, now=self.slot("20:00") + 30)
        self.assertEqual(res["slot"], "20:00")


class Views(CareBase):
    def test_plan_and_next(self):
        self.cm.add_medication("A", ["08:00"])
        self.cm.add_medication("B", ["20:00"])
        self.assertEqual([r["slot"] for r in self.cm.today_plan()], ["08:00", "20:00"])
        nxt = self.cm.next_dose(now=self.slot("08:00") - 3600)
        self.assertEqual(nxt["slot"], "08:00")

    def test_adherence(self):
        self.cm.add_medication("A", ["08:00"])
        now = self.slot("08:00") + 3600
        self.cm.mark("A", slot="08:00", status="taken")
        a = self.cm.adherence(days=1, now=now)
        self.assertEqual((a["taken"], a["total"], a["percent"]), (1, 1, 100))


class SpeechAndVoice(CareBase):
    def test_speech_names(self):
        ev = {"patient": "فاطمة", "med": "بانادول", "dose": "حبة",
              "with_food": True, "slot": "08:00", "announce_no": 1}
        self.assertIn("فاطمة", self.cm.build_reminder_speech(ev))
        self.assertIn("بانادول", self.cm.build_reminder_speech(ev))
        self.assertIn("فاطمة", self.cm.build_missed_speech(ev))

    def test_voice_default_is_syrian_female(self):
        self.assertEqual(self.cm.get_voice_gender(), "female")
        self.assertEqual(self.cm.get_voice(), self.cm.VOICE_FEMALE)

    def test_voice_toggle(self):
        self.assertEqual(self.cm.toggle_voice_gender(), "male")
        self.assertEqual(self.cm.get_voice(), self.cm.VOICE_MALE)
        self.assertEqual(self.cm.toggle_voice_gender(), "female")

    def test_set_voice_arabic_words(self):
        self.assertEqual(self.cm.set_voice_gender("ذكر"), "male")
        self.assertEqual(self.cm.set_voice_gender("أنثى"), "female")

    def test_voice_names_are_syrian(self):
        # the short names must resolve to Syrian neural voices
        from core.voice_system import VOICES
        self.assertEqual(VOICES[self.cm.VOICE_FEMALE], "ar-SY-AmanyNeural")
        self.assertEqual(VOICES[self.cm.VOICE_MALE], "ar-SY-LaithNeural")

    def test_guardian_roundtrip(self):
        self.cm.set_guardian(name="أحمد", telegram_chat_id="123", email="a@b.com")
        g = self.cm.get_guardian()
        self.assertEqual(g["name"], "أحمد")
        self.assertEqual(g["telegram_chat_id"], "123")


if __name__ == "__main__":
    unittest.main(verbosity=2)
