"""The optional model grader: JSON in, JSON out, and always a fallback."""
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from whatidid import graders
from whatidid.config import Settings
from whatidid.graders import llm, render
from whatidid.store import Store, week_key


class ExtractTests(unittest.TestCase):
    def test_plain_json(self):
        payload = llm.extract_json('{"score": 7, "pattern": "x"}')
        self.assertEqual(payload["score"], 7)

    def test_fenced_json(self):
        payload = llm.extract_json('Here you go:\n```json\n{"score": 4}\n```\n')
        self.assertEqual(payload["score"], 4)

    def test_json_with_chatter_around_it(self):
        payload = llm.extract_json('Sure. {"score": 9, "verdict": "kept it"} Hope that helps.')
        self.assertEqual(payload["verdict"], "kept it")

    def test_no_json_is_an_error(self):
        with self.assertRaises(llm.GraderError):
            llm.extract_json("I cannot grade this.")

    def test_broken_json_is_an_error(self):
        with self.assertRaises(llm.GraderError):
            llm.extract_json('{"score": 7,, }')


class NormaliseTests(unittest.TestCase):
    def test_score_is_clamped_to_the_scale(self):
        self.assertEqual(llm.normalise({"score": 14}, None)["score"], 10)
        self.assertEqual(llm.normalise({"score": -2}, None)["score"], 1)

    def test_score_falls_back_when_absent_or_junk(self):
        self.assertEqual(llm.normalise({}, 6)["score"], 6)
        self.assertEqual(llm.normalise({"score": "banana"}, 6)["score"], 6)

    def test_said_vs_did_pairs_are_coerced(self):
        payload = llm.normalise({"said_vs_did": [{"said": "a", "did": "b", "verdict": "KEPT"}, "junk"]}, None)
        self.assertEqual(len(payload["said_vs_did"]), 1)
        self.assertEqual(payload["said_vs_did"][0]["verdict"], "kept")

    def test_notes_are_dropped_when_empty(self):
        self.assertEqual(llm.normalise({"notes": ["", "  ", "real"]}, None)["notes"], ["real"])


class ProviderTests(unittest.TestCase):
    def settings(self, **kwargs):
        s = Settings()
        s.grader = "llm"
        s.llm_provider = "openai"
        s.llm_model = "test-model"
        for key, value in kwargs.items():
            setattr(s, key, value)
        return s

    def test_no_key_is_an_error_before_any_network_call(self):
        with self.assertRaises(llm.GraderError):
            llm.grade(self.settings(llm_api_key=""), "plan", "log", {}, "honest")

    def test_ollama_needs_no_key(self):
        with mock.patch.object(llm, "_post", return_value={"message": {"content": '{"score": 6}'}}):
            payload = llm.grade(self.settings(llm_provider="ollama", llm_api_key=""), "p", "l", {}, "honest")
        self.assertEqual(payload["score"], 6)

    def test_anthropic_shape(self):
        with mock.patch.object(llm, "_post", return_value={"content": [{"text": '{"score": 5}'}]}):
            payload = llm.grade(self.settings(llm_provider="anthropic", llm_api_key="k"), "p", "l", {}, "brutal")
        self.assertEqual(payload["score"], 5)

    def test_gemini_shape(self):
        with mock.patch.object(
                llm, "_post",
                return_value={"candidates": [{"content": {"parts": [{"text": '{"score": 8}'}]}}]}):
            payload = llm.grade(self.settings(llm_provider="gemini", llm_api_key="k"), "p", "l", {}, "gentle")
        self.assertEqual(payload["score"], 8)

    def test_http_error_becomes_a_grader_error(self):
        import urllib.error
        from email.message import Message
        error = urllib.error.HTTPError("u", 401, "Unauthorized", Message(), None)
        with mock.patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(llm.GraderError):
                llm.grade(self.settings(llm_api_key="k"), "p", "l", {}, "honest")


class FallbackTests(unittest.TestCase):
    """A model that fails must never take the report down with it."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.store = Store(self.root)
        self.store.ensure()
        self.iso = week_key(datetime.now())
        self.store.write_plan(self.iso, {
            "month": [], "week": [{"text": "Write the copy", "done": False}],
            "today": [], "today_date": datetime.now().date().isoformat(), "month_label": "Now"})
        from whatidid.store import Entry
        self.store.append_entry(Entry(date=datetime.now().date(), start="09:00", end="10:00",
                                      text="wrote the copy #write-the-copy", kind="checkin", minutes=60))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_model_failure_falls_back_to_the_offline_report(self):
        settings = Settings()
        settings.grader = "llm"
        settings.llm_api_key = "k"
        with mock.patch.object(llm, "grade", side_effect=llm.GraderError("provider is down")):
            result = graders.grade_week(self.store, settings, self.iso)
        self.assertEqual(result["source"], "local")
        self.assertIn("provider is down", result["error"])
        self.assertIn("## The pattern", result["markdown"])

    def test_model_success_is_rendered_with_its_own_prose(self):
        settings = Settings()
        settings.grader = "llm"
        settings.llm_api_key = "k"
        payload = {"score": 4, "verdict": "You wrote two hundred words and called it a week.",
                   "said_vs_did": [{"said": "Write the copy", "did": "1h", "verdict": "partly"}],
                   "pattern": "The afternoons were never yours.", "instruction": "Block 9 to 11 tomorrow.",
                   "notes": ["Slack took the 2pm hour twice."]}
        with mock.patch.object(llm, "grade", return_value=payload):
            result = graders.grade_week(self.store, settings, self.iso)
        self.assertEqual(result["source"], "llm")
        self.assertEqual(result["score"], 4)
        self.assertIn("two hundred words", result["markdown"])
        self.assertIn("Block 9 to 11 tomorrow", result["markdown"])
        self.assertIn("partly", result["markdown"])

    def test_llm_render_keeps_the_sections_and_labels_the_model(self):
        analysis = {"start": "2026-11-16", "week": "2026-W47", "answered": 3, "missed": 1,
                    "logged_minutes": 180, "covered_days": 2, "elapsed_days": 3,
                    "credited_minutes": 90, "unmatched_minutes": 90, "distraction_minutes": 30,
                    "seconds": None, "longest_stretch": None, "silent_spans": [],
                    "silent_minutes": 0, "distractions": [],
                    "components": {"completion": 50, "alignment": 50, "coverage": 75, "focus": 90}}
        body = render.render_llm_week({"score": 5, "verdict": "v", "pattern": "p", "instruction": "i"},
                                      analysis, "anthropic/claude", "honest")
        self.assertIn("## What the log says", body)
        self.assertIn("anthropic/claude", body)


if __name__ == "__main__":
    unittest.main()