"""Report rendering: same findings, three deliveries.

The verdict never changes with tone — only the wording. That is a promise the
UI repeats, so it has to stay true here: every tone reads the same numbers and
the same pattern, and adds no new accusation of its own.
"""
from __future__ import annotations

from .. import text as txt


def _p(tone: str, gentle: str, honest: str, brutal: str) -> str:
    return {"gentle": gentle, "honest": honest, "brutal": brutal}.get(tone, honest)


def _score_line(score) -> str:
    if score is None:
        return "**Not scored**"
    return f"**{score} / 10**"


def _objective_line(obj: dict) -> str:
    minutes = obj["total_minutes"]
    tag = "#" + obj["slug"]
    if obj["done"]:
        return f"- {obj['text']} — checked off on the plan"
    if obj["state"] == "untouched":
        return f"- {obj['text']} — nothing in the log"
    if obj["exact_minutes"] and not obj["estimated_minutes"]:
        return f"- {obj['text']} — {txt.format_duration(minutes)}, tagged {tag}"
    if obj["estimated_minutes"] and not obj["exact_minutes"]:
        return f"- {obj['text']} — about {txt.format_duration(minutes)} by word match (untagged estimate)"
    return f"- {obj['text']} — {txt.format_duration(minutes)} ({txt.format_duration(obj['exact_minutes'])} tagged, rest estimated)"


def _fact_lines(analysis: dict) -> list[str]:
    lines: list[str] = []
    logged = analysis["logged_minutes"]
    if logged:
        lines.append(
            f"- {txt.human_duration(logged)} on the record, across {analysis['covered_days']} "
            f"{txt.plural(analysis['covered_days'], 'day')} of {analysis['elapsed_days']} elapsed."
        )
    longest = analysis.get("longest_stretch")
    if longest and longest["minutes"] >= 30:
        excerpt = longest["text"].strip().rstrip(".")
        if len(excerpt) > 100:
            excerpt = excerpt[:97].rsplit(" ", 1)[0] + "…"
        lines.append(
            f"- Longest single stretch: {longest['label']} on {longest['date'][8:10]}/"
            f"{longest['date'][5:7]} ({txt.format_duration(longest['minutes'])}) — “{excerpt}”"
        )
    if logged and analysis.get("has_plan"):
        share = int(round(100 * analysis["credited_minutes"] / logged))
        if share >= 95:
            lines.append(f"- {share}% of it matched something you wrote down as mattering.")
        else:
            lines.append(
                f"- {share}% of it matched something you wrote down as mattering. "
                f"{txt.format_duration(analysis['unmatched_minutes'])} wasn't accounted for against the plan."
            )
    for d in analysis["distractions"][:2]:
        lines.append(
            f"- {d['category'].capitalize()}: {txt.format_duration(d['minutes'])} across "
            f"{d['count']} {txt.plural(d['count'], 'check-in')}."
        )
    if analysis["missed"]:
        lines.append(
            f"- {analysis['missed']} {txt.plural(analysis['missed'], 'question')} went unanswered."
        )
    for span in analysis["silent_spans"][:2]:
        lines.append(
            f"- Silence: {span['label']} {_pretty_time(span['start'])}–{_pretty_time(span['end'])}, "
            f"{txt.human_duration(span['minutes'])} with nothing on the record."
        )
    if not lines:
        lines.append("- Nothing on the record this week.")
    return lines


def _pretty_time(hhmm: str) -> str:
    h, m = (int(p) for p in hhmm.split(":")[:2])
    return f"{h % 12 or 12}:{m:02d}{'am' if h < 12 else 'pm'}"


def _summary(analysis: dict, tone: str) -> str:
    if not analysis["has_plan"]:
        return _p(
            tone,
            "There is no plan for this week, so there is nothing to hold it against. The log is here; "
            "the standard it should be measured by isn't.",
            "You never wrote down what this week was for, so there is no standard to grade it against. "
            "A log without a plan is a diary.",
            "No plan, no rubric, no verdict. You can't fail a test you didn't sit.",
        )
    if analysis["logged_minutes"] == 0:
        return _p(
            tone,
            "Nothing was written down this week, so there is no week to read back to you.",
            "The log is empty. Whatever happened, it isn't on the record, so it can't be counted.",
            "Nothing on the record. Nothing to grade. Whatever you did this week is now unverifiable, "
            "including to you.",
        )
    score = analysis["score"] or 0
    completion = analysis["components"]["completion"] or 0
    coverage = analysis["components"]["coverage"] or 0
    alignment = analysis["components"]["alignment"] or 0
    facts = f"{completion}% of the plan got time, {alignment}% of logged time went to the plan"
    if score >= 8:
        return _p(
            tone,
            f"This was a strong week. {facts}, and you kept the record well enough to prove it.",
            f"You did what you said you'd do. {facts}. Nothing to argue with here.",
            f"{facts}. You kept your word. Fine.",
        )
    if score >= 6:
        return _p(
            tone,
            f"Mostly the week you planned. {facts}. The gap is narrow and it has a shape, below.",
            f"Roughly the week you planned, minus a hole. {facts}.",
            f"{facts}. Close, not close enough to call it met.",
        )
    if score >= 4:
        return _p(
            tone,
            f"Part of the week landed. {facts}. What didn't, and why, is below.",
            f"About half of what you promised showed up in the record. {facts}.",
            f"{facts}. Half a week, honestly reported.",
        )
    return _p(
        tone,
        f"The plan and the week lived in different places. {facts}. That's worth sitting with, "
        "not worth beating yourself up over.",
        f"The week went somewhere else. {facts}, and the record has holes in it.",
        f"{facts}. The plan was decoration.",
    )


def _thin_record(analysis: dict, tone: str) -> str:
    """A high score on a thin record is a ceiling, not a measurement. Say so."""
    logged = txt.format_duration(analysis["logged_minutes"])
    days = analysis["elapsed_days"]
    return _p(
        tone,
        f"The record is thin — {logged} across {days} days — so read the score as a ceiling "
        f"rather than a measurement.",
        f"One caveat: {logged} across {days} days is barely a record. The score is what the log "
        f"can support, not a verdict on the week.",
        f"{logged} in {days} days. That's not a week, it's a sample. The score is a ceiling.",
    )


def _coverage_note(analysis: dict, tone: str) -> str:
    if analysis["components"]["coverage"] is None:
        return ""
    cov = analysis["components"]["coverage"]
    if cov >= 80:
        return _p(
            tone,
            "You answered nearly every question, so this report has something real to stand on.",
            "The record is solid: you answered almost every question asked.",
            "The record held up. That's the only reason this verdict is worth reading.",
        )
    if cov >= 50:
        return _p(
            tone,
            "Some questions went unanswered, so parts of this week are simply unknown.",
            "A fair share of questions went unanswered. Those hours are unknown, not zero.",
            "Half the week is missing from the record. Unknown is not the same as nothing.",
        )
    return _p(
        tone,
        "Most questions went unanswered, which means this report is reading a fraction of the week.",
        "Most of the week is unrecorded, so treat the score as a lower bound on what happened.",
        "You answered almost nothing. This report is mostly guesswork dressed as a verdict.",
    )


def _pattern(analysis: dict, tone: str) -> str:
    """The one thing that explains the gap, in the tone the user asked for.

    Every branch is driven by `pattern_key`, which the analyser also uses to
    pick the instruction, so the advice always answers the accusation.
    """
    key = analysis.get("pattern_key") or "steady"
    objectives = analysis["objectives"]
    untouched = [o for o in objectives if o["state"] == "untouched"]
    distractions = analysis["distractions"]
    logged = max(1, analysis["logged_minutes"])
    distraction_share = analysis["distraction_minutes"] / logged
    top = max(objectives, key=lambda o: o["total_minutes"]) if objectives else None

    if key == "kept" and top:
        minutes = txt.format_duration(top["total_minutes"])
        return _p(
            tone,
            f"What worked is dull: a plan small enough to finish. “{top['text']}” got {minutes} "
            f"and the week followed it. Keep the plan that size.",
            f"The plan was sized to the week, not to your ambition. “{top['text']}” got {minutes}; "
            f"the rest followed from that.",
            f"What worked is unglamorous: a short list, and you did it. “{top['text']}” took {minutes}. "
            f"Same size next week.",
        )

    if key == "unscheduled" and untouched:
        names = txt.join_list([o["text"] for o in untouched], 2)
        category = distractions[0]["category"] if distractions else "unplanned work"
        spent = txt.format_duration(analysis["distraction_minutes"])
        if len(untouched) == 1:
            return _p(
                tone,
                f"The pattern isn't a lack of effort. “{names}” is the only objective that got no time, "
                f"and it is also the only one with no block attached. {category.capitalize()} took {spent} "
                f"because it was there and the objective wasn't.",
                f"“{names}” got no time at all, while {category} took {spent}. It was never scheduled, "
                f"so it never had a chance.",
                f"Nothing was taken from “{names}”. It was never given. {category.capitalize()} got {spent} "
                f"because it was there and the objective wasn't.",
            )
        return _p(
            tone,
            f"The objectives that got nothing — {names} — are the ones that had no block attached, "
            f"while {category} took {spent}. They never competed.",
            f"{names} got no time at all, while {category} took {spent}. Those objectives were never "
            f"scheduled, so they never had a chance.",
            f"Nothing was taken from {names}. It was never given. {category.capitalize()} got {spent} "
            f"because it was there and the objectives weren't.",
        )

    if key == "invisible" and untouched:
        names = txt.join_list([o["text"] for o in untouched], 3)
        return _p(
            tone,
            f"No time was recorded against {names}. That doesn't mean you didn't think about them; "
            f"it means they never became something you could write a line about.",
            f"{names} never appears in the log. Work that never gets a line written about it is work "
            f"you can't tell apart from work you didn't do.",
            f"{names} has no entries. Either it didn't happen, or it happened in a way you couldn't put "
            f"in one line. Both are a problem.",
        )

    if key == "silence" and analysis["silent_spans"]:
        worst = analysis["silent_spans"][0]
        total = txt.human_duration(analysis["silent_minutes"])
        return _p(
            tone,
            f"The holes matter more than the numbers: {worst['label']} between "
            f"{_pretty_time(worst['start'])} and {_pretty_time(worst['end'])} has nothing on it, and "
            f"neither do the other gaps. That's the part of the week you'll be guessing about later.",
            f"{total} across the week has no entry at all. The largest is {worst['label']}, "
            f"{_pretty_time(worst['start'])} to {_pretty_time(worst['end'])}. Unrecorded time is where "
            f"the week goes.",
            f"{total} unrecorded. Biggest hole: {worst['label']}, {_pretty_time(worst['start'])}–"
            f"{_pretty_time(worst['end'])}. You don't know what happened there. That's the point of the log.",
        )

    if key == "drift":
        unmatched = txt.format_duration(analysis["unmatched_minutes"])
        return _p(
            tone,
            f"Most of the week went to things that weren't on the list — fine if it was a choice, "
            f"worth noticing if it wasn't. {unmatched} of the log matches nothing on the plan.",
            f"{unmatched} of logged time matches nothing on the plan. Some of that is the real job. "
            f"Some of it is drift. The log can't tell you which, and neither can you.",
            f"{unmatched} went nowhere the plan knew about. You can call that the real work, or you can "
            f"call it what it probably was.",
        )

    return _p(
        tone,
        "No single pattern stands out this week. The log is consistent enough that the differences look "
        "like noise rather than habit.",
        "Nothing dramatic explains the gap this week. The week was roughly the shape it always is.",
        "No pattern worth naming. That's either stability or a week you didn't really work.",
    )


def render_week(analysis: dict, tone: str = "honest", source: str = "local", extra: dict | None = None) -> str:
    score = analysis["score"]
    lines: list[str] = []
    start = analysis["start"][8:10] + "/" + analysis["start"][5:7]
    lines.append(f"# Sunday report — week of {start}")
    lines.append("")
    lines.append(_score_line(score))
    lines.append("")
    lines.append(_summary(analysis, tone))
    lines.append("")
    if (analysis.get("has_plan") and analysis["logged_minutes"] < 120
            and analysis["elapsed_days"] >= 3 and analysis["answered"] > 0):
        lines.append(_thin_record(analysis, tone))
        lines.append("")

    if analysis["objectives"]:
        lines.append("## What you said you'd do")
        lines.append("")
        for obj in analysis["objectives"]:
            lines.append(_objective_line(obj))
        lines.append("")

    lines.append("## What the log says")
    lines.append("")
    lines.extend(_fact_lines(analysis))
    note = _coverage_note(analysis, tone) if analysis.get("has_plan") else ""
    if note:
        lines.append("")
        lines.append(note)
    lines.append("")

    if analysis.get("has_plan"):
        lines.append("## The pattern")
        lines.append("")
        lines.append(_pattern(analysis, tone) if not extra else extra.get("pattern") or _pattern(analysis, tone))
        lines.append("")

    lines.append("## One instruction for next week")
    lines.append("")
    lines.append((extra or {}).get("instruction") or analysis["instruction"])
    lines.append("")

    comp = analysis["components"]
    lines.append("---")
    lines.append("")
    checks = analysis["answered"] + analysis["missed"]
    if analysis.get("gradeable"):
        parts = []
        for key, label in (("completion", "plan completion"), ("alignment", "time on plan"),
                           ("coverage", "record coverage"), ("focus", "time off the rails")):
            value = comp.get(key)
            parts.append(f"{label} {value}/100" if value is not None else f"{label} n/a")
        lines.append(
            f"Scored {'on your machine' if source == 'local' else 'by ' + source} from "
            f"{checks} check-ins · " + " · ".join(parts) + "."
        )
    else:
        lines.append(
            f"Not scored: there was no plan to grade against. "
            f"{checks} {txt.plural(checks, 'check-in')} on the record."
        )
    lines.append("")
    lines.append("_Same findings in Gentle, Honest and Brutal. Only the delivery changes._")
    return "\n".join(lines)


def render_month(month: dict, tone: str = "honest") -> str:
    per_week = month["per_week"]
    label = month["month"]
    lines = [f"# Monthly report — {label}", ""]
    if not month["gradeable"]:
        lines.append("No graded weeks this month, so there is no month to read back.")
        return "\n".join(lines)
    lines.append(f"**Average {month['average_score']} / 10**")
    lines.append("")
    trend = month["trend"]
    if trend is None:
        lines.append(_p(tone, "One week is not a trend, but it is a start.",
                        "A single scored week. Not enough to call a trend.",
                        "One week. Trends need more than one."))
    elif trend > 0:
        lines.append(_p(tone, f"The month improved: the last scored week is {trend:+d} on the first.",
                        f"Up {trend:+d} from the first scored week to the last.",
                        f"You climbed {trend:+d} across the month. Keep the thing that caused it."))
    elif trend < 0:
        lines.append(_p(tone, f"The month slipped {abs(trend)} points from the first scored week to the last.",
                        f"Down {abs(trend)} from the first scored week to the last. Worth knowing before next month starts.",
                        f"{abs(trend)} points lost across the month. Whatever stopped working, stop pretending it didn't."))
    else:
        lines.append("Flat across the month: the same week, four times.")
    lines.append("")
    lines.append("## The weeks")
    lines.append("")
    for week in per_week:
        score = f"{week['score']}/10" if week["score"] is not None else "not scored"
        lines.append(f"- {week['label']} — {score}, {txt.format_duration(week.get('minutes') or 0)} logged")
    lines.append("")
    lines.append("## What you achieved")
    lines.append("")
    lines.append(f"- {month['objectives_met']} of {month['objectives_total']} plan items got time "
                 f"across {month['weeks_with_data']} recorded "
                 f"{txt.plural(month['weeks_with_data'], 'week')}.")
    lines.append(f"- {txt.human_duration(month['total_logged_minutes'])} on the record, "
                 f"{txt.human_duration(month['total_credited_minutes'])} of it against the plan.")
    lines.append("")
    if month["habits"]:
        lines.append("## The habit that kept costing you")
        lines.append("")
        top = month["habits"][0]
        lines.append(_p(
            tone,
            f"{top['category'].capitalize()} showed up in {top['weeks']} "
            f"{txt.plural(top['weeks'], 'week')} for {txt.human_duration(top['minutes'])} in total. "
            "Not a moral failing — an unwritten rule about when it's allowed.",
            f"{top['category'].capitalize()} took {txt.human_duration(top['minutes'])} over "
            f"{top['weeks']} {txt.plural(top['weeks'], 'week')}. That is the largest single leak of the month.",
            f"{top['category'].capitalize()}: {txt.human_duration(top['minutes'])} across "
            f"{top['weeks']} {txt.plural(top['weeks'], 'week')}. That's your month, one habit at a time.",
        ))
        lines.append("")
    lines.append("## A plan for next month")
    lines.append("")
    from .analysis import INSTRUCTIONS, PATTERN_INSTRUCTIONS, primary_pattern
    dominant = month.get("dominant_pattern")
    if dominant in PATTERN_INSTRUCTIONS:
        lines.append(PATTERN_INSTRUCTIONS[dominant])
    else:
        counts: dict[str, int] = {}
        for week in month["weeks"]:
            if week.get("weakest"):
                counts[week["weakest"]] = counts.get(week["weakest"], 0) + 1
        weakest = max(counts, key=lambda k: counts[k]) if counts else "coverage"
        lines.append(INSTRUCTIONS.get(weakest, INSTRUCTIONS["coverage"]))
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"Built from {month['weeks_with_data']} recorded "
                 f"{txt.plural(month['weeks_with_data'], 'week')}, "
                 f"{month['weeks_scored']} of them graded.")
    return "\n".join(lines)


def render_llm_week(payload: dict, analysis: dict, model: str, tone: str = "honest") -> str:
    """The same file shape, filled with a model's prose instead of templates."""
    start = analysis["start"][8:10] + "/" + analysis["start"][5:7]
    lines = [f"# Sunday report — week of {start}", ""]
    score = payload.get("score", analysis.get("score"))
    lines.append(f"**{score} / 10**" if score is not None else "**Not scored**")
    lines.append("")
    if payload.get("verdict"):
        lines.append(str(payload["verdict"]).strip())
        lines.append("")

    pairs = payload.get("said_vs_did") or []
    if pairs:
        lines.append("## What you said you'd do")
        lines.append("")
        for pair in pairs:
            said = str(pair.get("said", "")).strip()
            did = str(pair.get("did", "")).strip()
            verdict = str(pair.get("verdict", "")).strip().lower()
            mark = {"kept": "kept", "partly": "partly", "broken": "dropped"}.get(verdict, verdict or "—")
            lines.append(f"- {said} — {did} ({mark})" if did else f"- {said} — {mark}")
        lines.append("")

    lines.append("## What the log says")
    lines.append("")
    lines.extend(_fact_lines(analysis))
    lines.append("")
    if payload.get("pattern"):
        lines.append("## The pattern")
        lines.append("")
        lines.append(str(payload["pattern"]).strip())
        lines.append("")
    if payload.get("instruction"):
        lines.append("## One instruction for next week")
        lines.append("")
        lines.append(str(payload["instruction"]).strip())
        lines.append("")
    notes = payload.get("notes") or []
    if notes:
        lines.append("### Also worth knowing")
        lines.append("")
        for note in notes[:5]:
            lines.append(f"- {str(note).strip()}")
        lines.append("")
    comp = analysis["components"]
    lines.append("---")
    lines.append("")
    lines.append(
        f"Graded by {model} (your key, your machine) from {analysis['answered'] + analysis['missed']} check-ins · "
        f"plan completion {comp['completion']}/100 · time on plan {comp['alignment']}/100 · "
        f"record coverage {comp['coverage']}/100."
    )
    return "\n".join(lines)