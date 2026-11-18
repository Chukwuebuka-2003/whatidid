"""The store: markdown in, markdown out, and hand-edited files still parse."""
import shutil
import tempfile
import unittest
from datetime import date, datetime, time
from pathlib import Path

from whatidid.store import (Entry, Store, month_key, parse_plan, render_plan,
                            split_span, week_bounds, week_key)


def dt(day, hhmm):
    hour, minute = (int(p) for p in hhmm.split(":"))
    return datetime.combine(day, time(hour, minute))


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.store = Store(self.root)
        self.store.ensure()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_week_keys_and_bounds(self):
        self.assertEqual(week_key(date(2026, 11, 18)), "2026-W47")
        self.assertEqual(week_key(date(2026, 11, 16)), "2026-W47")
        start, end = week_bounds("2026-W47")
        self.assertEqual(start, date(2026, 11, 16))
        self.assertEqual(end, date(2026, 11, 22))

    def test_month_key_handles_december(self):
        self.assertEqual(month_key(date(2026, 12, 31)), "2026-12")

    def test_append_and_read_round_trip(self):
        iso = week_key(date(2026, 11, 18))
        made = self.store.append_span(dt(date(2026, 11, 18), "09:00"),
                                      dt(date(2026, 11, 18), "10:30"),
                                      "Drafted the proposal #write-the-onboarding-copy")
        self.assertEqual(len(made), 1)
        entries = self.store.read_entries(iso)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].start, "09:00")
        self.assertEqual(entries[0].end, "10:30")
        self.assertEqual(entries[0].minutes, 90)
        self.assertIn("#write-the-onboarding-copy", entries[0].text)

    def test_file_is_readable_markdown(self):
        d = date(2026, 11, 18)
        self.store.append_span(dt(d, "09:00"), dt(d, "10:30"), "wrote the thing")
        body = self.store.log_path(week_key(d)).read_text()
        self.assertIn("## Wed 2026-11-18", body)
        self.assertIn("- 09:00–10:30 (1h 30m) | wrote the thing", body)

    def test_entries_are_sorted_on_write(self):
        d = date(2026, 11, 18)
        self.store.append_span(dt(d, "14:00"), dt(d, "15:00"), "later")
        self.store.append_span(dt(d, "09:00"), dt(d, "10:00"), "earlier")
        entries = self.store.read_entries(week_key(d))
        self.assertEqual([e.text for e in entries], ["earlier", "later"])

    def test_midnight_split(self):
        chunks = split_span(dt(date(2026, 11, 18), "23:20"), dt(date(2026, 11, 19), "00:40"), "late night")
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].date, date(2026, 11, 18))
        self.assertEqual(chunks[0].end, "24:00")
        self.assertEqual(chunks[0].minutes, 40)
        self.assertEqual(chunks[1].date, date(2026, 11, 19))
        self.assertEqual(chunks[1].start, "00:00")
        self.assertEqual(chunks[1].minutes, 40)

    def test_missed_marker_round_trips(self):
        d = date(2026, 11, 18)
        self.store.append_span(dt(d, "11:00"), dt(d, "12:00"), "(no answer)", kind="missed")
        entries = self.store.read_entries(week_key(d))
        self.assertEqual(entries[0].kind, "missed")

    def test_hand_edited_file_with_loose_formatting(self):
        """A user opened log.md and typed with hyphens and no duration."""
        iso = "2026-W47"
        path = self.store.log_path(iso)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "# my week\n\n"
            "## Wed 2026-11-18\n"
            "- 9:05 - 10:00 | called the supplier\n"
            "* 10:00–11:15 | packed orders\n"
            "- 14:00 | wrote it down without an end time\n"
            "not an entry at all\n",
            encoding="utf-8",
        )
        entries = self.store.read_entries(iso)
        self.assertEqual([e.text for e in entries], ["called the supplier", "packed orders"])
        self.assertEqual(entries[0].start, "09:05")
        self.assertEqual(entries[0].minutes, 55)
        self.assertEqual(entries[1].minutes, 75)

    def test_delete_entry(self):
        d = date(2026, 11, 18)
        self.store.append_span(dt(d, "09:00"), dt(d, "10:00"), "one")
        self.store.append_span(dt(d, "10:00"), dt(d, "11:00"), "two")
        iso = week_key(d)
        self.assertTrue(self.store.delete_entry(iso, 0))
        self.assertEqual([e.text for e in self.store.read_entries(iso)], ["two"])
        self.assertFalse(self.store.delete_entry(iso, 9))

    def test_plan_round_trip(self):
        iso = "2026-W47"
        plan = {"month_label": "November 2026",
                "month": [{"text": "Ship the beta", "done": False}],
                "week": [{"text": "Write the copy", "done": True}],
                "today": [{"text": "Draft the format", "done": False}],
                "today_date": "2026-11-18"}
        saved = self.store.write_plan(iso, plan)
        self.assertEqual(saved["month"][0]["text"], "Ship the beta")
        self.assertTrue(saved["week"][0]["done"])
        self.assertEqual(saved["today_date"], "2026-11-18")
        self.assertEqual(saved["week"][0]["slug"], "write-the-copy")
        self.assertTrue(saved["written"])

    def test_plan_parses_hand_written_bullets(self):
        raw = ("# Week 47\n\n## Month — November 2026\n- ship the beta\n\n"
               "## This week\n* [ ] write the copy\n- [x] fix the bug\n\n"
               "## Today — 2026-11-18\n- [ ] draft\n")
        plan = parse_plan(raw, "2026-W47")
        self.assertEqual([i["text"] for i in plan["month"]], ["ship the beta"])
        self.assertEqual([i["text"] for i in plan["week"]], ["write the copy", "fix the bug"])
        self.assertTrue(plan["week"][1]["done"])
        self.assertEqual(plan["today_date"], "2026-11-18")

    def test_duplicate_titles_get_distinct_slugs(self):
        plan = parse_plan("## This week\n- [ ] same thing\n- [ ] same thing\n", "2026-W47")
        slugs = [i["slug"] for i in plan["week"]]
        self.assertEqual(len(set(slugs)), 2)

    def test_plan_render_is_parseable(self):
        iso = "2026-W47"
        plan = {"month_label": "November 2026",
                "month": [{"text": "Ship the beta", "done": False}],
                "week": [{"text": "Write the copy", "done": True}],
                "today": [{"text": "Draft", "done": False}],
                "today_date": "2026-11-18"}
        reparsed = parse_plan(render_plan(plan, iso), iso)
        self.assertEqual([i["text"] for i in reparsed["week"]], ["Write the copy"])
        self.assertTrue(reparsed["week"][0]["done"])

    def test_report_front_matter(self):
        iso = "2026-W47"
        saved = self.store.write_report(iso, "# Sunday report\n\n**7 / 10**\n\nbody", {
            "week": iso, "score": 7, "source": "local", "generated": "2026-11-18T20:00:00"})
        self.assertEqual(saved["score"], 7)
        self.assertEqual(saved["source"], "local")
        self.assertIn("body", saved["markdown"])
        self.assertTrue(self.store.report_path(iso).parent.name == iso)

    def test_list_weeks_and_months(self):
        d = date(2026, 11, 18)
        self.store.append_span(dt(d, "09:00"), dt(d, "10:00"), "x")
        self.store.write_month_report("2026-11", "# m", {"month": "2026-11"})
        self.assertEqual(self.store.list_weeks(), ["2026-W47"])
        self.assertEqual(self.store.list_months(), ["2026-11"])

    def test_latest_entry_end_ignores_misses(self):
        d = date(2026, 11, 18)
        self.store.append_span(dt(d, "09:00"), dt(d, "10:00"), "real")
        self.store.append_span(dt(d, "10:00"), dt(d, "12:00"), "(no answer)", kind="missed")
        self.assertEqual(self.store.latest_entry_end(), dt(d, "10:00"))

    def test_export_markdown_contains_everything(self):
        d = date(2026, 11, 18)
        self.store.write_plan(week_key(d), {"month": [], "week": [{"text": "One thing", "done": False}],
                                            "today": [], "today_date": str(d), "month_label": "Nov"})
        self.store.append_span(dt(d, "09:00"), dt(d, "10:00"), "did the thing")
        bundle = self.store.export_markdown()
        self.assertIn("One thing", bundle)
        self.assertIn("did the thing", bundle)


if __name__ == "__main__":
    unittest.main()
