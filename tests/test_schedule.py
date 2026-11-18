"""The clock: when it asks, how much a question covers, what pauses it."""
import unittest
from datetime import datetime, timedelta

from whatidid import schedule
from whatidid.config import Settings

NOW = datetime(2026, 11, 18, 10, 0)  # a Wednesday, 10am


def settings(**kwargs):
    base = Settings()
    base.interval_minutes = 90
    base.active_start = "08:00"
    base.active_end = "22:00"
    for key, value in kwargs.items():
        setattr(base, key, value)
    return base.normalised()


class ActiveWindowTests(unittest.TestCase):
    def test_inside_and_outside(self):
        s = settings()
        self.assertTrue(schedule.in_active_window(s, datetime(2026, 11, 18, 9, 0)))
        self.assertFalse(schedule.in_active_window(s, datetime(2026, 11, 18, 6, 0)))
        self.assertFalse(schedule.in_active_window(s, datetime(2026, 11, 18, 23, 0)))

    def test_off_hours_pushes_to_next_morning(self):
        s = settings()
        self.assertEqual(schedule.next_active_moment(s, datetime(2026, 11, 18, 23, 30)),
                         datetime(2026, 11, 19, 8, 0))

    def test_weekday_only_skips_the_weekend(self):
        s = settings(weekday_only=True)
        friday_night = datetime(2026, 11, 20, 23, 0)  # Friday
        self.assertEqual(schedule.next_active_moment(s, friday_night),
                         datetime(2026, 11, 23, 8, 0))  # Monday

    def test_window_across_midnight(self):
        s = settings(active_start="22:00", active_end="06:00")
        self.assertTrue(schedule.in_active_window(s, datetime(2026, 11, 18, 23, 0)))


class DueTests(unittest.TestCase):
    def test_first_ever_question_is_interval_away(self):
        s = settings()
        state = schedule.due_state(s, NOW)
        self.assertFalse(state["due"])
        self.assertEqual(state["next_due_at"], (NOW + timedelta(minutes=90)).isoformat())

    def test_due_when_the_clock_passes(self):
        s = settings()
        s.next_due_at = (NOW - timedelta(minutes=1)).isoformat()
        self.assertTrue(schedule.due_state(s, NOW)["due"])

    def test_not_due_before_the_clock(self):
        s = settings()
        s.next_due_at = (NOW + timedelta(minutes=5)).isoformat()
        self.assertFalse(schedule.due_state(s, NOW)["due"])

    def test_deep_work_holds_questions(self):
        s = settings()
        s.next_due_at = (NOW - timedelta(hours=3)).isoformat()
        schedule.start_deep_work(s, NOW - timedelta(hours=3))
        state = schedule.due_state(s, NOW)
        self.assertFalse(state["due"])
        self.assertEqual(state["paused"], "deep-work")

    def test_coming_back_up_asks_once_about_the_whole_stretch(self):
        s = settings()
        schedule.start_deep_work(s, NOW - timedelta(hours=2))
        schedule.stop_deep_work(s, NOW)
        state = schedule.due_state(s, NOW)
        self.assertTrue(state["due"])

    def test_mute_stops_the_question_but_not_the_schedule(self):
        s = settings()
        s.muted = True
        s.next_due_at = (NOW - timedelta(hours=1)).isoformat()
        state = schedule.due_state(s, NOW)
        self.assertFalse(state["due"])
        self.assertEqual(state["paused"], "muted")

    def test_off_hours_reports_paused(self):
        s = settings()
        s.next_due_at = (NOW - timedelta(hours=6)).isoformat()
        self.assertEqual(schedule.due_state(s, datetime(2026, 11, 18, 3, 0))["paused"], "off-hours")

    def test_answer_reschedules_one_interval_out(self):
        s = settings()
        s.next_due_at = NOW.isoformat()
        schedule.schedule_from_answer(s, NOW)
        self.assertEqual(s.next_due_at, (NOW + timedelta(minutes=90)).isoformat())
        self.assertEqual(s.last_entry_end, NOW.isoformat())

    def test_answer_at_night_reschedules_into_the_morning(self):
        s = settings()
        schedule.schedule_from_answer(s, datetime(2026, 11, 18, 21, 30))
        self.assertEqual(s.next_due_at, datetime(2026, 11, 19, 8, 0).isoformat())

    def test_snooze_moves_it_forward(self):
        s = settings()
        s.next_due_at = (NOW - timedelta(minutes=5)).isoformat()
        schedule.snooze(s, 15, NOW)
        self.assertEqual(s.next_due_at, (NOW + timedelta(minutes=15)).isoformat())

    def test_a_log_ahead_of_the_clock_asks_nothing(self):
        s = settings()
        s.last_entry_end = (NOW + timedelta(hours=2)).isoformat()
        s.next_due_at = (NOW - timedelta(hours=1)).isoformat()
        state = schedule.due_state(s, NOW)
        self.assertFalse(state["due"])
        self.assertEqual(state["next_due_at"], (NOW + timedelta(hours=2, minutes=90)).isoformat())

    def test_disk_hint_beats_a_stale_marker(self):
        s = settings()
        s.last_entry_end = (NOW - timedelta(days=3)).isoformat()
        start, end = schedule.ask_span(s, schedule.effective_last(s, NOW - timedelta(minutes=30)), NOW)
        self.assertEqual(end, NOW)
        self.assertEqual(start, NOW - timedelta(minutes=30))


class AskSpanTests(unittest.TestCase):
    def test_span_is_capped_so_a_long_silence_is_not_a_question(self):
        s = settings(max_ask_minutes=480)
        start, end = schedule.ask_span(s, NOW - timedelta(days=2), NOW)
        self.assertEqual(int((end - start).total_seconds() // 60), 480)

    def test_span_starts_at_the_last_answer(self):
        s = settings()
        start, end = schedule.ask_span(s, NOW - timedelta(minutes=45), NOW)
        self.assertEqual(int((end - start).total_seconds() // 60), 45)

    def test_span_never_starts_in_the_future(self):
        s = settings()
        start, end = schedule.ask_span(s, NOW + timedelta(hours=1), NOW)
        self.assertLess(start, NOW)
        self.assertEqual(end, NOW)


if __name__ == "__main__":
    unittest.main()
