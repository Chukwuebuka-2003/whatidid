"""The analyst, offline: turn a week of plain-text entries plus a plan into a
graded verdict with no API key, no model, no network.

Design rules, in order of importance:

1. It only grades against the user's own written goals. A week whose goal was
   "rest" and which was spent resting must score well. There is no notion here
   of what "productive" means outside the plan.
2. It says what it knows and labels what it guesses. An entry that carries an
   objective's hashtag is exact credit; one that merely shares words is
   "estimated" and is reported as such.
3. No plan, no score. If the user never wrote what the week was for, the honest
   answer is "nothing to grade against", not a made-up number.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from .. import text as txt
from ..config import Settings
from ..store import Entry, WeekData, _hhmm_to_time, week_bounds

WEIGHTS = {"completion": 0.35, "alignment": 0.30, "coverage": 0.20, "focus": 0.15}
ITEM_WEIGHT = {"week": 1.0, "month": 0.6, "today": 0.8}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _minutes(entry: Entry) -> int:
    return int(entry.minutes or 0)


def _fmt_time(hhmm: str) -> str:
    h, m = (int(p) for p in hhmm.split(":")[:2])
    suffix = "am" if h < 12 else "pm"
    hour = h % 12 or 12
    return f"{hour}:{m:02d}{suffix}"


def _span_label(entry: Entry) -> str:
    return f"{_fmt_time(entry.start)}–{_fmt_time(entry.end)}"


def _day_label(d: date) -> str:
    return d.strftime("%A %d %B")


def rubric(plan: dict) -> list[dict]:
    """Flatten the plan into weighted rubric items."""
    items: list[dict] = []
    for kind in ("month", "week", "today"):
        for item in plan.get(kind) or []:
            items.append({
                "text": item.get("text", "").strip(),
                "slug": item.get("slug") or txt.slugify(item.get("text", "")),
                "done": bool(item.get("done")),
                "kind": kind,
                "weight": ITEM_WEIGHT[kind],
                "only_date": plan.get("today_date") if kind == "today" else None,
            })
    return [i for i in items if i["text"]]


# --------------------------------------------------------------------------- #
# the analysis
# --------------------------------------------------------------------------- #
def analyse(week: WeekData, settings: Settings, now: datetime | None = None) -> dict:
    now = now or datetime.now()
    entries = [e for e in week.entries]
    items = rubric(week.plan)

    logged = sum(_minutes(e) for e in entries if e.kind != "missed")
    answered = sum(1 for e in entries if e.kind != "missed")
    missed = sum(1 for e in entries if e.kind == "missed")

    # --- credit each entry to the plan items it belongs to ------------------ #
    per_item = {i["slug"]: {"exact": 0, "estimated": 0, "entries": 0} for i in items}
    credited = 0.0
    unmatched: list[dict] = []
    for entry in entries:
        if entry.kind == "missed":
            continue
        hits = []
        for item in items:
            if item["only_date"] and entry.date.isoformat() != item["only_date"]:
                continue
            exact, fuzzy, ratio = txt.match_entry(item, entry.to_dict())
            if exact or fuzzy:
                hits.append((item, exact, ratio))
        if not hits:
            unmatched.append(entry.to_dict() | {"minutes": _minutes(entry)})
            continue
        # exact hashtag hits win outright; otherwise credit is proportional
        exact_hits = [h for h in hits if h[1]] or hits
        share = _minutes(entry) / len(exact_hits)
        best_credit = 0.0
        for item, exact, ratio in exact_hits:
            slot = per_item[item["slug"]]
            if exact:
                slot["exact"] += int(round(share))
                best_credit = max(best_credit, 1.0)
            else:
                slot["estimated"] += int(round(share))
                best_credit = max(best_credit, ratio)
            slot["entries"] += 1
        credited += _minutes(entry) * best_credit

    objectives = []
    completion_num = 0.0
    completion_den = 0.0
    for item in items:
        slot = per_item[item["slug"]]
        matched_minutes = slot["exact"] + slot["estimated"]
        if item["done"]:
            state = "done"
            credit = 1.0
        elif matched_minutes > 0:
            state = "tagged" if slot["exact"] else "estimated"
            credit = 1.0 if slot["exact"] else 0.6
        else:
            state = "untouched"
            credit = 0.0
        completion_num += credit * item["weight"]
        completion_den += item["weight"]
        objectives.append({
            "text": item["text"],
            "slug": item["slug"],
            "kind": item["kind"],
            "done": item["done"],
            "state": state,
            "exact_minutes": slot["exact"],
            "estimated_minutes": slot["estimated"],
            "total_minutes": matched_minutes,
            "entries": slot["entries"],
        })

    # --- distractions ------------------------------------------------------ #
    by_category: dict[str, dict] = {}
    for entry in entries:
        if entry.kind == "missed":
            continue
        category = txt.classify(entry.text)
        if not category:
            continue
        slot = by_category.setdefault(category, {"category": category, "minutes": 0, "count": 0, "examples": []})
        slot["minutes"] += _minutes(entry)
        slot["count"] += 1
        if len(slot["examples"]) < 3:
            slot["examples"].append(entry.text.strip()[:90])
    distractions = sorted(by_category.values(), key=lambda d: -d["minutes"])
    distraction_minutes = sum(d["minutes"] for d in distractions)

    # --- days and silence -------------------------------------------------- #
    by_day: list[dict] = []
    silent_spans: list[dict] = []
    threshold = max(90, int(settings.interval_minutes) * 2)
    for day in sorted({e.date for e in entries}):
        day_entries = sorted([e for e in entries if e.date == day], key=lambda e: _hhmm_to_time(e.start))
        by_day.append({
            "date": day.isoformat(),
            "label": _day_label(day),
            "minutes": sum(_minutes(e) for e in day_entries if e.kind != "missed"),
            "entries": len(day_entries),
            "missed": sum(1 for e in day_entries if e.kind == "missed"),
        })
        # Gaps inside the day's own recorded window. A missed check-in is on the
        # record (as a blank), so the cursor moves past it: "silence" means the
        # app truly had nothing, not that the user declined to answer.
        win_start, win_end = _active_window(settings, day)
        if not day_entries:
            continue
        cursor = max(win_start, datetime.combine(day, _hhmm_to_time(day_entries[0].start)))
        if day == now.date():
            win_end = min(win_end, now)
        for entry in day_entries:
            start = datetime.combine(day, _hhmm_to_time(entry.start))
            gap = int((start - cursor).total_seconds() // 60)
            if gap >= threshold:
                silent_spans.append({
                    "date": day.isoformat(),
                    "label": _day_label(day),
                    "start": cursor.strftime("%H:%M"),
                    "end": start.strftime("%H:%M"),
                    "minutes": gap,
                })
            end = datetime.combine(day, _hhmm_to_time(entry.end))
            cursor = max(cursor, end)
    silent_spans.sort(key=lambda s: -s["minutes"])

    # --- stretches --------------------------------------------------------- #
    longest = None
    best_run = 0
    for entry in entries:
        if entry.kind == "missed":
            continue
        if _minutes(entry) > best_run:
            best_run = _minutes(entry)
            longest = entry.to_dict() | {"minutes": _minutes(entry), "label": _span_label(entry)}

    # --- scores ------------------------------------------------------------ #
    elapsed_days = _elapsed_days(week, now)
    covered_days = len(by_day)
    completion = completion_num / completion_den if completion_den else None
    alignment = (credited / logged) if logged else None
    answer_rate = answered / (answered + missed) if (answered + missed) else None
    day_rate = (covered_days / elapsed_days) if elapsed_days else None
    coverage_parts = [p for p in (answer_rate, day_rate) if p is not None]
    coverage = sum(coverage_parts) / len(coverage_parts) if coverage_parts else None
    focus = (1 - (distraction_minutes / logged)) if logged else None

    components = {"completion": completion, "alignment": alignment, "coverage": coverage, "focus": focus}
    gradeable = bool(items) and logged > 0 and completion is not None
    if gradeable:
        composite = sum(WEIGHTS[k] * (v if v is not None else 0.5) for k, v in components.items())
        score = max(1, min(10, int(round(composite * 10))))
    else:
        composite = None
        score = None

    result = {
        "week": week.iso,
        "start": week.start.isoformat(),
        "end": week.end.isoformat(),
        "logged_minutes": logged,
        "logged_hours": round(logged / 60, 1),
        "answered": answered,
        "missed": missed,
        "covered_days": covered_days,
        "elapsed_days": elapsed_days,
        "credited_minutes": int(round(credited)),
        "credited_hours": round(credited / 60, 1),
        "unmatched_minutes": logged - int(round(credited)),
        "objectives": objectives,
        "distractions": distractions,
        "distraction_minutes": distraction_minutes,
        "silent_spans": silent_spans[:4],
        "silent_minutes": sum(s["minutes"] for s in silent_spans),
        "longest_stretch": longest,
        "by_day": by_day,
        "components": {k: (round(v * 100) if v is not None else None) for k, v in components.items()},
        "composite": round(composite, 3) if composite is not None else None,
        "score": score,
        "gradeable": gradeable,
        "has_plan": bool(items),
        "interval_minutes": settings.interval_minutes,
        "weakest": _weakest(components) if gradeable else None,
    }
    result["pattern_key"] = primary_pattern(result)
    result["instruction"] = instruction_for(result)
    return result


def _active_window(settings: Settings, day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, _hhmm_to_time(settings.active_start))
    end = datetime.combine(day, _hhmm_to_time(settings.active_end))
    if end <= start:
        end = datetime.combine(day + timedelta(days=1), _hhmm_to_time(settings.active_end))
    return start, end


def _elapsed_days(week: WeekData, now: datetime) -> int:
    monday = week.start
    today = now.date()
    if today < monday:
        return 1
    if today > week.end:
        return 7
    return (today - monday).days + 1


def _weakest(components: dict) -> str:
    live = {k: (v if v is not None else 0.0) for k, v in components.items()}
    return min(live, key=lambda k: live[k] * WEIGHTS[k])


def primary_pattern(result: dict) -> str:
    """One key naming the thing that actually explains the gap this week.

    The prose and the instruction both key off this, so the advice can never be
    about something the report didn't just accuse you of.
    """
    if not result.get("gradeable"):
        return "no-plan"
    untouched = [o for o in result["objectives"] if o["state"] == "untouched"]
    logged = max(1, result["logged_minutes"])
    share = result["distraction_minutes"] / logged
    coverage = result["components"].get("coverage") or 0
    if (result["score"] or 0) >= 8 and len(untouched) <= 1 and coverage >= 70:
        return "kept"
    if untouched and share >= 0.2:
        return "unscheduled"
    if untouched:
        return "invisible"
    if result["silent_minutes"] >= 120:
        return "silence"
    if (result["components"].get("alignment") or 100) < 60:
        return "drift"
    return "steady"


INSTRUCTIONS = {
    "completion": (
        "Give one unfinished objective a fixed block tomorrow morning before anything else, "
        "and tag the check-in with its hashtag so the record shows it."
    ),
    "alignment": (
        "Tag every check-in with the objective it serves. Everything untagged is time you spent "
        "but cannot account for, and that gap is what this report keeps finding."
    ),
    "coverage": (
        "Answer the question even when the answer is embarrassing. The misses cost you more score "
        "than the scrolling does — a week you can read is worth more than a week you can defend."
    ),
    "focus": (
        "Write the distraction down when it happens, in the check-in, in plain words. Naming it "
        "is the only thing that has ever shortened it."
    ),
}


PATTERN_INSTRUCTIONS = {
    "unscheduled": (
        "Put the objective that got no time into a fixed block tomorrow morning, before the day "
        "fills up, and tag that check-in so the record shows it."
    ),
    "kept": "Keep next week's list exactly this size. Add nothing to it until something comes off.",
    "silence": (
        "Answer even when the answer is embarrassing, especially then. The misses cost you more "
        "score than the scrolling does."
    ),
    "invisible": (
        "The moment you touch an objective, write the line. Work that never gets a line is "
        "indistinguishable from work you didn't do."
    ),
    "drift": (
        "Tag every check-in with the objective it serves. Untagged time is the gap this report "
        "keeps finding."
    ),
}


def instruction_for(result: dict) -> str:
    key = result.get("pattern_key") or primary_pattern(result)
    if key == "no-plan":
        return "Write the plan first: a month goal, two or three objectives for the week, and today's tasks."
    if key == "unscheduled":
        untouched = [o for o in result["objectives"] if o["state"] == "untouched"]
        if not untouched:
            return PATTERN_INSTRUCTIONS["unscheduled"]
        return (f"Put “{untouched[0]['text']}” in a fixed block tomorrow morning, before the day "
                f"fills up, and tag that check-in so the record shows it.")
    if key in PATTERN_INSTRUCTIONS:
        return PATTERN_INSTRUCTIONS[key]
    return INSTRUCTIONS.get(result.get("weakest") or "coverage", INSTRUCTIONS["coverage"])


# --------------------------------------------------------------------------- #
# month roll-up
# --------------------------------------------------------------------------- #
def analyse_month(store, month: str, settings: Settings, now: datetime | None = None) -> dict:
    """Aggregate every week in the month that has data."""
    from ..store import month_bounds, week_key

    first, last = month_bounds(month)
    weeks: list[dict] = []
    cursor = first
    while cursor <= last:
        iso = week_key(cursor)
        week = store.read_week(iso)
        if week.entries:
            weeks.append(analyse(week, settings, now))
        cursor += timedelta(days=7)

    scored = [w for w in weeks if w["score"] is not None]
    total_logged = sum(w["logged_minutes"] for w in weeks)
    total_credited = sum(w["credited_minutes"] for w in weeks)
    habit: dict[str, dict] = {}
    for week in weeks:
        for d in week["distractions"]:
            slot = habit.setdefault(d["category"], {"category": d["category"], "minutes": 0, "weeks": 0})
            slot["minutes"] += d["minutes"]
            slot["weeks"] += 1
    habits = sorted(habit.values(), key=lambda h: -h["minutes"])

    per_week = []
    for week in weeks:
        start = date.fromisoformat(week["start"])
        per_week.append({
            "week": week["week"],
            "label": f"w/c {start.strftime('%d %b')}",
            "score": week["score"],
            "hours": week["logged_hours"],
            "minutes": week["logged_minutes"],
            "completion": week["components"]["completion"],
            "coverage": week["components"]["coverage"],
        })

    average = round(sum(w["score"] for w in scored) / len(scored), 1) if scored else None
    trend = None
    if len(scored) >= 2:
        trend = scored[-1]["score"] - scored[0]["score"]

    patterns = [w.get("pattern_key") for w in weeks
                if w.get("pattern_key") and w["pattern_key"] not in ("kept", "no-plan")]
    dominant = max(set(patterns), key=patterns.count) if patterns else None

    return {
        "month": month,
        "weeks": weeks,
        "per_week": per_week,
        "dominant_pattern": dominant,
        "average_score": average,
        "trend": trend,
        "total_logged_minutes": total_logged,
        "total_credited_minutes": total_credited,
        "habits": habits,
        "weeks_with_data": len(weeks),
        "weeks_scored": len(scored),
        "objectives_met": sum(1 for w in weeks for o in w["objectives"] if o["state"] in ("done", "tagged")),
        "objectives_total": sum(len(w["objectives"]) for w in weeks),
        "gradeable": bool(scored),
    }