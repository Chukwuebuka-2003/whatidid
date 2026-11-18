"""Grading: does the verdict follow the plan, and only the plan?"""
import shutil
import tempfile
import unittest
from datetime import date, datetime, time
from pathlib import Path

from whatidid import graders
from whatidid.config import Settings
from whatidid.graders import analysis as A
from whatidid.graders import render
from whatidid.store import Store, week_key

WEEKDAY = date(2026, 11, 16)
NOW = datetime(2026, 11, 20, 18, 0)


def dt(day, hhmm):
    hour, minute = (int(p) for p in hhmm.split(":"))
    return datetime.combine(day, time(hour, minute))


class GraderCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.store = Store(self.root)
        self.store.ensure()
        self.settings = Settings()
        self.settings.interval_minutes = 90
        self.iso = week_key(WEEKDAY)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def plan(self, week, month=(), today=(), today_date=None):
        return self.store.write_plan(self.iso, {
            "month_label": "November 2026",
            "month": [{"text": t, "done": False} for t in month],
            "week": [{"text": t, "done": False} for t in week],
            "today": [{"text": t, "done": False} for t in today],
            "today_date": today_date or WEEKDAY.isoformat(),
        })

    def add(self, day, start, end, text, kind="checkin"):
        self.store.append_span(dt(day, start), dt(day, end), text, kind)

    def grade(self, tone="honest"):
        self.settings.tone = tone
        return graders.grade_week(self.store, self.settings, self.iso, now=NOW)


class GradeabilityTests(GraderCase):
    def test_no_plan_means_no_score(self):
        self.add(WEEKDAY, "09:00", "10:00", "did something")
        result = self.grade()
        self.assertIsNone(result["score"])
        self.assertEqual(result["analysis"]["pattern_key"], "no-plan")
        self.assertIn("no standard to grade", result["markdown"].lower())
        self.assertIn("Not scored", result["markdown"])

    def test_no_entries_means_no_score(self):
        self.plan(["Write the onboarding copy"])
        result = self.grade()
        self.assertIsNone(result["score"])
        self.assertIn("empty", result["markdown"].lower())

    def test_a_week_that_kept_its_word_gets_a_high_score(self):
        self.plan(["Write the onboarding copy", "Fix the CSV import bug"])
        self.add(WEEKDAY, "09:00", "11:00", "onboarding copy #write-the-onboarding-copy")
        self.add(WEEKDAY, "11:00", "12:00", "csv import fixed #fix-the-csv-import-bug")
        self.add(WEEKDAY + __import__("datetime").timedelta(days=1), "09:00", "10:00",
                 "onboarding copy again #write-the-onboarding-copy")
        result = self.grade()
        self.assertGreaterEqual(result["score"], 8)

    def test_a_rested_week_you_planned_to_rest_grades_well(self):
        """The app has no opinion of its own: rest is work if rest was the plan."""
        self.plan(["Rest properly", "Read for pleasure"])
        self.add(WEEKDAY, "10:00", "12:00", "rested, read on the sofa #rest-properly")
        self.add(WEEKDAY, "12:00", "13:00", "walk, no phone #rest-properly")
        self.add(WEEKDAY + __import__("datetime").timedelta(days=1), "10:00", "11:30",
                 "read two chapters of the novel #read-for-pleasure")
        result = self.grade()
        self.assertGreaterEqual(result["score"], 7)


class CreditTests(GraderCase):
    def test_hashtag_is_exact_and_untagged_words_are_an_estimate(self):
        self.plan(["Write the onboarding copy"])
        self.add(WEEKDAY, "09:00", "10:30", "onboarding copy #write-the-onboarding-copy")
        self.add(WEEKDAY, "10:30", "11:00", "onboarding copy again, no tag")
        result = self.grade()
        objective = result["analysis"]["objectives"][0]
        self.assertEqual(objective["exact_minutes"], 90)
        self.assertEqual(objective["estimated_minutes"], 30)
        self.assertIn("estimated", result["markdown"])

    def test_labelled_work_with_no_match_is_counted_as_unplanned(self):
        self.plan(["Write the onboarding copy"])
        self.add(WEEKDAY, "09:00", "10:00", "watched football highlights")
        result = self.grade()
        self.assertEqual(result["analysis"]["credited_minutes"], 0)
        self.assertEqual(result["analysis"]["unmatched_minutes"], 60)

    def test_missed_checkins_lower_coverage_but_not_hours(self):
        self.plan(["Write the onboarding copy"])
        self.add(WEEKDAY, "09:00", "10:00", "onboarding copy #write-the-onboarding-copy")
        self.add(WEEKDAY, "10:00", "11:00", "(no answer)", kind="missed")
        result = self.grade()
        a = result["analysis"]
        self.assertEqual(a["missed"], 1)
        self.assertEqual(a["logged_minutes"], 60)
        self.assertLess(a["components"]["coverage"], 100)


class PatternTests(GraderCase):
    def test_objective_with_no_time_and_a_distraction_is_named(self):
        self.plan(["Write the onboarding copy", "Finish chapter two of the thesis"])
        self.add(WEEKDAY, "09:00", "10:00", "onboarding copy #write-the-onboarding-copy")
        self.add(WEEKDAY, "10:00", "12:00", "scrolling twitter")
        result = self.grade()
        self.assertEqual(result["analysis"]["pattern_key"], "unscheduled")
        self.assertIn("chapter two", result["markdown"].lower())
        self.assertIn("chapter two", result["analysis"]["instruction"].lower())

    def test_silence_is_named_when_the_record_has_holes(self):
        self.plan(["Write the onboarding copy"])
        # two short answers, then a four-hour hole inside working hours
        self.add(WEEKDAY, "08:30", "08:45", "onboarding copy #write-the-onboarding-copy")
        self.add(WEEKDAY, "13:00", "13:15", "onboarding copy, again #write-the-onboarding-copy")
        result = self.grade()
        self.assertGreater(result["analysis"]["silent_minutes"], 180)
        self.assertEqual(result["analysis"]["pattern_key"], "silence")
        self.assertIn("8:45am", result["markdown"])
        self.assertIn("4 hours 15 minutes", result["markdown"])
        self.assertIn("barely a record", result["markdown"])

    def test_drift_when_time_matches_nothing(self):
        self.plan(["Write the onboarding copy"])
        self.add(WEEKDAY, "09:00", "12:00", "unrelated paperwork and invoices")
        result = self.grade()
        self.assertIn(result["analysis"]["pattern_key"], ("drift", "invisible", "unscheduled"))


class ToneTests(GraderCase):
    def test_the_score_never_moves_with_the_tone(self):
        self.plan(["Write the onboarding copy", "Fix the CSV import bug"])
        self.add(WEEKDAY, "09:00", "10:00", "onboarding copy #write-the-onboarding-copy")
        self.add(WEEKDAY, "10:00", "11:30", "youtube")
        scores = {tone: self.grade(tone)["score"] for tone in ("gentle", "honest", "brutal")}
        self.assertEqual(len(set(scores.values())), 1)

    def test_the_wording_does_move_with_the_tone(self):
        self.plan(["Write the onboarding copy"])
        self.add(WEEKDAY, "09:00", "10:00", "onboarding copy #write-the-onboarding-copy")
        bodies = {tone: self.grade(tone)["markdown"] for tone in ("gentle", "honest", "brutal")}
        self.assertNotEqual(bodies["gentle"], bodies["brutal"])
        self.assertNotEqual(bodies["gentle"], bodies["honest"])

    def test_components_stay_inside_the_scale(self):
        self.plan(["Write the onboarding copy"])
        self.add(WEEKDAY, "09:00", "10:00", "onboarding copy #write-the-onboarding-copy")
        result = self.grade()
        for value in result["analysis"]["components"].values():
            if value is not None:
                self.assertGreaterEqual(value, 0)
                self.assertLessEqual(value, 100)
        self.assertGreaterEqual(result["score"], 1)
        self.assertLessEqual(result["score"], 10)


class MonthTests(GraderCase):
    def test_month_average_over_scored_weeks(self):
        self.plan(["Write the onboarding copy"])
        self.add(WEEKDAY, "09:00", "10:00", "onboarding copy #write-the-onboarding-copy")
        graders.grade_week(self.store, self.settings, self.iso, now=NOW)
        month = graders.grade_month(self.store, self.settings, "2026-11", now=NOW)
        self.assertEqual(month["summary"]["weeks_with_data"], 1)
        self.assertEqual(month["summary"]["weeks_scored"], 1)
        self.assertIsNotNone(month["summary"]["average_score"])
        self.assertIn("Monthly report", month["markdown"])

    def test_empty_month_says_so(self):
        month = graders.grade_month(self.store, self.settings, "2026-05", now=NOW)
        self.assertFalse(month["summary"]["gradeable"])
        self.assertIn("no month to read back", month["markdown"].lower())


class MarkdownShapeTests(GraderCase):
    def test_report_has_the_four_sections(self):
        self.plan(["Write the onboarding copy"])
        self.add(WEEKDAY, "09:00", "10:00", "onboarding copy #write-the-onboarding-copy")
        body = self.grade()["markdown"]
        for heading in ("## What you said you'd do", "## What the log says",
                        "## The pattern", "## One instruction for next week"):
            self.assertIn(heading, body)

    def test_report_body_strips_title_and_score(self):
        body = render.render_week(A.analyse(self.store.read_week(self.iso), self.settings, NOW), "honest")
        self.assertTrue(body.startswith("# Sunday report"))

    def test_render_is_stable_with_no_data(self):
        body = render.render_week(A.analyse(self.store.read_week(self.iso), self.settings, NOW), "honest")
        self.assertIn("Not scored", body)


if __name__ == "__main__":
    unittest.main()