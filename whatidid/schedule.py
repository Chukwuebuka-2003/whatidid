"""The clock: when to interrupt, how long a question covers, what "paused" means.

All times are naive local datetimes; the app is a single-person local tool, so
"local" is the right frame. The schedule state lives in settings.json rather
than in memory, so closing and reopening the tab (or the server) doesn't
silently reset the clock to "ninety minutes from now, forever".
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from .config import Settings


def now_local() -> datetime:
    return datetime.now().replace(microsecond=0)


def _at(d: date, hhmm: str) -> datetime:
    h, m = (int(p) for p in hhmm.split(":"))
    return datetime.combine(d, time(h, m))


def active_window(settings: Settings, d: date) -> tuple[datetime, datetime]:
    start = _at(d, settings.active_start)
    end = _at(d, settings.active_end)
    if end <= start:  # window crosses midnight
        end = _at(d + timedelta(days=1), settings.active_end)
    return start, end


def is_active_day(settings: Settings, d: date) -> bool:
    if not settings.weekday_only:
        return True
    return d.weekday() < 5


def in_active_window(settings: Settings, moment: datetime) -> bool:
    if not is_active_day(settings, moment.date()):
        return False
    start, end = active_window(settings, moment.date())
    return start <= moment < end


def next_active_moment(settings: Settings, moment: datetime) -> datetime:
    """First active instant at or after `moment`."""
    if in_active_window(settings, moment):
        return moment
    for offset in range(0, 8):
        day = moment.date() + timedelta(days=offset)
        if not is_active_day(settings, day):
            continue
        start, end = active_window(settings, day)
        if moment < start:
            return start
        if start <= moment < end:
            return moment
    return moment  # give up quietly rather than loop forever


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is not None:  # stored timestamps carry an offset; drop it
        parsed = parsed.replace(tzinfo=None)
    return parsed.replace(microsecond=0)


def _iso(moment: datetime | None) -> str | None:
    return moment.replace(microsecond=0).isoformat() if moment else None


def effective_last(settings: Settings, hint: datetime | None = None) -> datetime | None:
    """Where the next question starts from: the stored marker, or the newest
    entry on disk if that is later (hand-edited logs, a fresh install pointing
    at an existing folder)."""
    stored = _parse(settings.last_entry_end)
    if hint and (stored is None or hint > stored):
        return hint
    return stored


def compute_next_due(settings: Settings, reference: datetime) -> datetime:
    """`reference` + interval, pushed forward into the next active window."""
    interval = max(1, int(settings.interval_minutes))
    return next_active_moment(settings, reference + timedelta(minutes=interval))


def schedule_from_answer(settings: Settings, answered_at: datetime) -> None:
    settings.last_entry_end = _iso(answered_at)
    settings.next_due_at = _iso(compute_next_due(settings, answered_at))


def schedule_from_now(settings: Settings, now: datetime | None = None) -> None:
    settings.next_due_at = _iso(compute_next_due(settings, now or now_local()))


def ensure_scheduled(settings: Settings, now: datetime) -> None:
    """If there is no next_due_at yet (fresh install, or hand-edited file), set one."""
    if not settings.next_due_at:
        schedule_from_now(settings, now)


def ask_span(settings: Settings, last: datetime | None, now: datetime) -> tuple[datetime, datetime]:
    """The window a question covers: back to the last answer, but never more
    than `max_ask_minutes`, and never more than 24h."""
    if last is None:
        start = now - timedelta(minutes=max(1, int(settings.interval_minutes)))
    else:
        start = last
    cap = timedelta(minutes=min(int(settings.max_ask_minutes), 24 * 60))
    if now - start > cap:
        start = now - cap
    if start >= now:
        start = now - timedelta(minutes=max(1, min(int(settings.interval_minutes), 60)))
    return start.replace(second=0, microsecond=0), now.replace(second=0, microsecond=0)


def due_state(settings: Settings, now: datetime | None = None,
              last_hint: datetime | None = None) -> dict:
    now = (now or now_local()).replace(microsecond=0)
    ensure_scheduled(settings, now)

    last = effective_last(settings, last_hint)
    next_due = _parse(settings.next_due_at) or compute_next_due(settings, now)

    paused = None
    if settings.deep_work:
        paused = "deep-work"
    elif settings.muted:
        paused = "muted"
    elif not in_active_window(settings, now):
        paused = "off-hours"

    # The log is already ahead of the clock (future-dated entries, or the
    # machine's time changed). There is nothing to ask about yet.
    ahead = last if (last is not None and last >= now) else None
    if ahead and not paused:
        next_due = compute_next_due(settings, ahead)

    due = False
    if not paused and not ahead and now >= next_due:
        due = True

    start, end = ask_span(settings, last, now)
    return {
        "due": due,
        "paused": paused,
        "next_due_at": _iso(next_due),
        "last_answer_at": _iso(last),
        "seconds_until_due": int((next_due - now).total_seconds()),
        "ask_start": _iso(start),
        "ask_end": _iso(end),
        "ask_minutes": int((end - start).total_seconds() // 60),
        "deep_work_since": settings.deep_work_since,
        "now": now.isoformat(),
    }


def start_deep_work(settings: Settings, now: datetime) -> None:
    settings.deep_work = True
    settings.deep_work_since = _iso(now)


def stop_deep_work(settings: Settings, now: datetime) -> None:
    """Coming back up: ask once, about the whole stretch."""
    settings.deep_work = False
    settings.deep_work_since = None
    settings.next_due_at = _iso(now.replace(microsecond=0))


def snooze(settings: Settings, minutes: int, now: datetime) -> None:
    settings.next_due_at = _iso(now + timedelta(minutes=max(1, int(minutes))))


def resume_schedule(settings: Settings, now: datetime) -> None:
    """After answering or skipping, the next question is one interval out."""
    settings.next_due_at = _iso(compute_next_due(settings, now))
    settings.last_entry_end = _iso(now)
