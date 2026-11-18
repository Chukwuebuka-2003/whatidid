"""The HTTP surface: same behaviour the browser gets, exercised without a browser."""
import json
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from whatidid.config import Settings
from whatidid.server import create_app


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.app = create_app(self.root)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        shutil.rmtree(self.root, ignore_errors=True)

    # -- basics ------------------------------------------------------------ #
    def test_health(self):
        self.assertEqual(self.client.get("/healthz").json()["ok"], True)

    def test_index_is_the_app(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("What I&nbsp;Did", response.text)
        self.assertIn("/static/app.js", response.text)

    def test_static_assets_are_served(self):
        for path in ("/static/styles.css", "/static/app.js", "/icon.svg", "/manifest.webmanifest"):
            self.assertEqual(self.client.get(path).status_code, 200, path)

    def test_bootstrap_shape(self):
        data = self.client.get("/api/bootstrap").json()
        for key in ("version", "today", "data_dir", "settings", "due", "week", "weeks"):
            self.assertIn(key, data)
        self.assertIn("analysis", data["week"])
        self.assertIn("plan", data["week"])

    def test_api_key_is_never_sent_to_the_browser(self):
        self.client.put("/api/settings", json={"llm_api_key": "«redacted:sk-…»"})
        body = self.client.get("/api/bootstrap").text
        self.assertNotIn("«redacted:sk-…»", body)
        self.assertTrue(self.client.get("/api/bootstrap").json()["settings"]["llm_api_key_set"])
        stored = json.loads((self.root / "settings.json").read_text())
        self.assertEqual(stored["llm_api_key"], "«redacted:sk-…»")

    # -- plan -------------------------------------------------------------- #
    def test_plan_save_and_read(self):
        response = self.client.post("/api/plan", json={
            "week": "2026-W47",
            "month": [{"text": "Ship the beta", "done": False}],
            "week_items": [{"text": "Write the copy", "done": False}],
            "today": [{"text": "Draft the intro", "done": False}],
            "today_date": "2026-11-18",
        }).json()
        plan = response["week"]["plan"]
        self.assertEqual([i["text"] for i in plan["week"]], ["Write the copy"])
        self.assertEqual(plan["week"][0]["slug"], "write-the-copy")
        written = (self.root / "2026" / "2026-W47" / "plan.md").read_text()
        self.assertIn("Write the copy", written)

    def test_plan_accepts_plain_strings(self):
        response = self.client.post("/api/plan", json={
            "week": "2026-W47", "week_items": ["One bare string"]}).json()
        self.assertEqual(response["week"]["plan"]["week"][0]["text"], "One bare string")

    def test_raw_plan_round_trip(self):
        raw = "# Week 47\n\n## This week\n- [ ] write it down\n"
        self.client.post("/api/plan/raw", json={"week": "2026-W47", "raw": raw})
        self.assertEqual((self.root / "2026" / "2026-W47" / "plan.md").read_text(), raw)
        plan = self.client.get("/api/plan?week=2026-W47").json()["plan"]
        self.assertEqual(plan["week"][0]["text"], "write it down")

    # -- entries ----------------------------------------------------------- #
    def test_checkin_writes_an_entry_and_moves_the_clock(self):
        self.client.post("/api/plan", json={"week": "2026-W47", "week_items": ["Write the copy"]})
        before = self.client.get("/api/due").json()
        result = self.client.post("/api/checkin", json={"text": "wrote the copy #write-the-copy"}).json()
        self.assertEqual(len(result["entries"]), 1)
        entry = result["entries"][0]
        self.assertEqual(entry["kind"], "checkin")
        self.assertIn("wrote the copy", entry["text"])
        self.assertEqual(entry["tags"], ["write-the-copy"])
        after = self.client.get("/api/due").json()
        self.assertIsNotNone(after["last_answer_at"])
        self.assertGreater(after["seconds_until_due"], 0)
        self.assertFalse(after["due"])

    def test_empty_answer_is_refused(self):
        response = self.client.post("/api/checkin", json={"text": "   "})
        self.assertEqual(response.status_code, 400)

    def test_skip_records_a_miss_not_an_answer(self):
        result = self.client.post("/api/checkin/skip", json={"reason": "meeting"}).json()
        self.assertTrue(result["skipped"])
        week = self.client.get("/api/bootstrap").json()["week"]
        self.assertEqual(len(week["entries"]), 1)
        self.assertEqual(week["entries"][0]["kind"], "missed")

    def test_snooze_pushes_the_question_out(self):
        before = self.client.get("/api/due").json()
        self.client.post("/api/checkin/snooze", json={"minutes": 30})
        after = self.client.get("/api/due").json()
        self.assertNotEqual(before["next_due_at"], after["next_due_at"])
        self.assertFalse(after["due"])

    def test_manual_entry_needs_a_date_and_times(self):
        bad = self.client.post("/api/entries", json={"text": "x", "date": "18-11-2026"})
        self.assertEqual(bad.status_code, 400)
        bad_time = self.client.post("/api/entries", json={"text": "x", "date": "2026-11-18", "start": "9am"})
        self.assertEqual(bad_time.status_code, 400)
        good = self.client.post("/api/entries", json={
            "text": "wrote it down by hand", "date": "2026-11-18", "start": "09:00", "end": "10:30"})
        self.assertEqual(good.status_code, 200)
        self.assertEqual(good.json()["entries"][0]["minutes"], 90)

    def test_edit_and_delete_an_entry(self):
        self.client.post("/api/entries", json={
            "text": "typo", "date": "2026-11-18", "start": "09:00", "end": "09:30"})
        iso = self.client.get("/api/bootstrap?week=2026-11-18").json()["week"]["iso"]
        patched = self.client.patch(f"/api/entries/{iso}/0", json={"text": "fixed the typo"})
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(self.client.get("/api/bootstrap").json()["week"]["entries"][0]["text"],
                         "fixed the typo")
        self.assertEqual(self.client.delete(f"/api/entries/{iso}/0").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/entries/{iso}/5").status_code, 404)

    # -- controls ---------------------------------------------------------- #
    def test_deep_work_pauses_then_asks_once(self):
        paused = self.client.post("/api/deepwork", json={"on": True}).json()
        self.assertEqual(paused["due"]["paused"], "deep-work")
        back = self.client.post("/api/deepwork", json={"on": False}).json()
        self.assertIsNone(back["due"]["paused"])

    def test_mute_and_unmute(self):
        muted = self.client.post("/api/mute", json={"muted": True}).json()
        self.assertEqual(muted["due"]["paused"], "muted")
        unmuted = self.client.post("/api/mute", json={"muted": False}).json()
        self.assertIsNone(unmuted["due"]["paused"])

    # -- reports ----------------------------------------------------------- #
    def test_week_report_is_written_and_scored(self):
        self.client.post("/api/plan", json={"week": "2026-W47", "week_items": ["Write the copy"]})
        self.client.post("/api/entries", json={
            "text": "wrote the copy #write-the-copy", "date": "2026-11-17", "start": "09:00", "end": "10:00"})
        result = self.client.post("/api/report/week", json={"week": "2026-W47"}).json()
        self.assertIsNotNone(result["score"])
        self.assertEqual(result["source"], "local")
        self.assertIn("## The pattern", result["markdown"])
        path = self.root / "2026" / "2026-W47" / "report.md"
        self.assertTrue(path.is_file())
        self.assertIn("score:", path.read_text())
        fetched = self.client.get("/api/report/week?week=2026-W47").json()
        self.assertEqual(fetched["report"]["score"], result["score"])

    def test_month_report(self):
        result = self.client.post("/api/report/month", json={"month": "2026-11"}).json()
        self.assertIn("Monthly report", result["markdown"])
        self.assertTrue((self.root / "2026" / "2026-11" / "report.md").is_file())

    def test_a_tone_change_shows_up_in_the_next_report(self):
        self.client.post("/api/plan", json={"week": "2026-W47", "week_items": ["Write the copy"]})
        self.client.post("/api/entries", json={
            "text": "wrote the copy #write-the-copy", "date": "2026-11-17", "start": "09:00", "end": "10:00"})
        honest = self.client.post("/api/report/week", json={"week": "2026-W47"}).json()
        self.client.put("/api/settings", json={"tone": "brutal"})
        brutal = self.client.post("/api/report/week", json={"week": "2026-W47"}).json()
        self.assertEqual(honest["score"], brutal["score"])
        self.assertNotEqual(honest["markdown"], brutal["markdown"])

    # -- settings ---------------------------------------------------------- #
    def test_interval_change_reschedules(self):
        self.client.put("/api/settings", json={"interval_minutes": 45})
        settings = self.client.get("/api/settings").json()["settings"]
        self.assertEqual(settings["interval_minutes"], 45)

    def test_absurd_interval_is_clamped(self):
        self.client.put("/api/settings", json={"interval_minutes": 99999})
        self.assertLessEqual(self.client.get("/api/settings").json()["settings"]["interval_minutes"], 480)

    def test_moving_the_data_folder(self):
        new_root = Path(tempfile.mkdtemp())
        try:
            response = self.client.put("/api/settings", json={"data_dir": str(new_root)})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["data_dir"], str(new_root))
            self.client.post("/api/checkin", json={"text": "after the move"})
            self.assertTrue(any(new_root.rglob("log.md")))
        finally:
            shutil.rmtree(new_root, ignore_errors=True)

    def test_bad_folder_is_refused(self):
        response = self.client.put("/api/settings", json={"data_dir": "/proc/definitely/not/writable"})
        self.assertEqual(response.status_code, 400)

    # -- io ---------------------------------------------------------------- #
    def test_export(self):
        self.client.post("/api/entries", json={
            "text": "exported line", "date": "2026-11-18", "start": "09:00", "end": "09:30"})
        self.assertIn("exported line", self.client.get("/api/export?format=md").text)
        self.assertIn("exported line", json.dumps(self.client.get("/api/export?format=json").json()))

    def test_file_reader_cannot_escape_the_folder(self):
        outside = Path(tempfile.mkdtemp())
        try:
            secret = outside / "secret.txt"
            secret.write_text("should not be readable")
            response = self.client.get(f"/api/file?path=../../../../../../{str(secret).lstrip('/')}")
            self.assertEqual(response.status_code, 403)
        finally:
            shutil.rmtree(outside, ignore_errors=True)

    def test_file_reader_reads_inside_the_folder(self):
        self.client.post("/api/entries", json={
            "text": "x", "date": "2026-11-18", "start": "09:00", "end": "09:30"})
        response = self.client.get("/api/file?path=2026/2026-W47/log.md")
        self.assertEqual(response.status_code, 200)
        self.assertIn("## Wed 2026-11-18", response.json()["content"])

    def test_bad_week_is_a_400(self):
        self.assertEqual(self.client.get("/api/bootstrap?week=banana").status_code, 400)

    def test_settings_file_is_private(self):
        stored = self.root / "settings.json"
        self.assertTrue(stored.is_file())
        mode = oct(stored.stat().st_mode)[-3:]
        self.assertEqual(mode, "600")


if __name__ == "__main__":
    unittest.main()