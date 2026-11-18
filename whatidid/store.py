"""The store: the whole database is a folder of plain markdown files.

Layout inside the data directory (all human readable, all editable by hand):

    2026/
      2026-W47/
        plan.md       goals: month, this week, today
        log.md        one line per check-in, grouped by day
        report.md     the Sunday report, with a tiny front-matter block
      2026-11/
        report.md     the monthly report
    settings.json

There is no database and no server-side state beyond settings.json. Reading a
week parses its markdown; writing a week rewrites the file in sorted order.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

from . import text as txt

ENTRY_RE = re.compile(
    r"^[-*]\s+"
    r"(?P<start>\d{1,2}:\d{2})\s*[–\-—~]\s*(?P<end>\d{1,2}:\d{2})\s*"
    r"(?:\((?P<dur>[^)]*)\)\s*)?"
    r"(?:\|\s*(?P<text>.*))?$"
)
DAY_RE = re.compile(r"^#{2,3}\s+(?:[A-Za-z]{3,9}\s+)?(?:[A-Za-z]{3},\s*)?(?P<date>\d{4}-\d{2}-\d{2})\s*$")
PLAN_HEAD_RE = re.compile(r"^##+\s*(?P<head>.+?)\s*$")
CHECK_RE = re.compile(r"^[-*]\s*\[(?P<mark>[ xX])\]\s*(?P<text>.+?)\s*$")
BULLET_RE = re.compile(r"^[-*]\s+(?P<text>.+?)\s*$")
FRONT_RE = re.compile(r"^---\s*$")

MISSING_TEXT = "(no answer)"


# --------------------------------------------------------------------------- #
# week / month keys
# --------------------------------------------------------------------------- #
def week_key(d: date | datetime) -> str:
    if isinstance(d, datetime):
        d = d.date()
    iso = d.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def week_bounds(iso: str) -> tuple[date, date]:
    year, week = iso.split("-W")
    monday = date.fromisocalendar(int(year), int(week), 1)
    return monday, monday + timedelta(days=6)


def month_key(d: date | datetime) -> str:
    if isinstance(d, datetime):
        d = d.date()
    return f"{d.year}-{d.month:02d}"


def month_bounds(key: str) -> tuple[date, date]:
    year, month = (int(p) for p in key.split("-"))
    first = date(year, month, 1)
    last = (date(year + (month == 12), (month % 12) + 1, 1)) - timedelta(days=1)
    return first, last


# --------------------------------------------------------------------------- #
# entries
# --------------------------------------------------------------------------- #
@dataclass
class Entry:
    date: date
    start: str            # "09:00"
    end: str              # "10:30"
    text: str
    kind: str = "checkin"  # checkin | manual | missed | deepwork
    minutes: int = 0

    def to_dict(self) -> dict:
        return {
            "date": self.date.isoformat(),
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "kind": self.kind,
            "minutes": self.minutes,
            "tags": txt.tags_in(self.text),
        }

    @property
    def start_dt(self) -> datetime:
        return datetime.combine(self.date, _hhmm_to_time(self.start))

    @property
    def end_dt(self) -> datetime:
        end = datetime.combine(self.date, _hhmm_to_time(self.end))
        return end


def _hhmm_to_time(value: str) -> time:
    h, m = str(value).split(":")[:2]
    return time(int(h) % 24, int(m) % 60)


def _minutes_between(start: str, end: str) -> int:
    a = _hhmm_to_time(start)
    b = _hhmm_to_time(end)
    mins = (b.hour * 60 + b.minute) - (a.hour * 60 + a.minute)
    if mins < 0:  # crossed midnight; the store splits spans so this is only a fallback
        mins += 24 * 60
    return mins


def _line_for(entry: Entry) -> str:
    body = entry.text.strip() or MISSING_TEXT
    return f"- {entry.start}–{entry.end} ({txt.format_duration(entry.minutes)}) | {body}"


def split_span(start: datetime, end: datetime, text: str, kind: str = "checkin") -> list[Entry]:
    """Split one span at midnight so every entry belongs to exactly one day."""
    if end <= start:
        return []
    out: list[Entry] = []
    cursor = start
    while cursor < end:
        midnight = datetime.combine(cursor.date() + timedelta(days=1), time(0, 0))
        chunk_end = min(end, midnight)
        out.append(Entry(
            date=cursor.date(),
            start=cursor.strftime("%H:%M"),
            end=(chunk_end.strftime("%H:%M") if chunk_end != midnight else "24:00"),
            text=text,
            kind=kind,
            minutes=int((chunk_end - cursor).total_seconds() // 60),
        ))
        cursor = chunk_end
    return out


# --------------------------------------------------------------------------- #
# the store
# --------------------------------------------------------------------------- #
@dataclass
class WeekData:
    iso: str
    start: date
    end: date
    entries: list[Entry] = field(default_factory=list)
    plan: dict = field(default_factory=dict)
    report: dict | None = None

    def to_dict(self) -> dict:
        return {
            "iso": self.iso,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "entries": [e.to_dict() for e in self.entries],
            "plan": self.plan,
            "report": self.report,
        }


class Store:
    def __init__(self, data_dir: Path):
        self.root = Path(data_dir).expanduser()

    # -- paths ------------------------------------------------------------- #
    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def week_dir(self, iso: str) -> Path:
        year = iso.split("-")[0]
        return self.root / year / iso

    def month_dir(self, key: str) -> Path:
        year = key.split("-")[0]
        return self.root / year / key

    def log_path(self, iso: str) -> Path:
        return self.week_dir(iso) / "log.md"

    def plan_path(self, iso: str) -> Path:
        return self.week_dir(iso) / "plan.md"

    def report_path(self, iso: str) -> Path:
        return self.week_dir(iso) / "report.md"

    def month_report_path(self, key: str) -> Path:
        return self.month_dir(key) / "report.md"

    # -- atomic write ------------------------------------------------------ #
    @staticmethod
    def _write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)

    # -- log --------------------------------------------------------------- #
    def read_week(self, iso: str) -> WeekData:
        start, end = week_bounds(iso)
        return WeekData(
            iso=iso,
            start=start,
            end=end,
            entries=self.read_entries(iso),
            plan=self.read_plan(iso),
            report=self.read_report(iso),
        )

    def read_entries(self, iso: str) -> list[Entry]:
        path = self.log_path(iso)
        if not path.is_file():
            return []
        entries: list[Entry] = []
        current: date | None = None
        week_start, _ = week_bounds(iso)
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            day = DAY_RE.match(stripped)
            if day:
                try:
                    current = date.fromisoformat(day.group("date"))
                except ValueError:
                    current = None
                continue
            if stripped.startswith("#"):
                continue
            if current is None:
                continue
            m = ENTRY_RE.match(stripped)
            if not m:
                continue
            body = (m.group("text") or "").strip()
            kind = "checkin"
            if body.lower().startswith(MISSING_TEXT) or not body:
                kind = "missed"
                body = MISSING_TEXT
            minutes = _minutes_between(m.group("start"), m.group("end"))
            entries.append(Entry(
                date=current,
                start=_pad(m.group("start")),
                end=_pad(m.group("end")),
                text=body,
                kind=kind,
                minutes=minutes,
            ))
        entries.sort(key=lambda e: (e.date, _hhmm_to_time(e.start)))
        return entries

    def write_entries(self, iso: str, entries: list[Entry]) -> None:
        start, end = week_bounds(iso)
        year, week = iso.split("-W")
        lines = [f"# Week {week}, {year} ({start.strftime('%d %b')} – {end.strftime('%d %b %Y')})"]
        by_day: dict[date, list[Entry]] = {}
        for entry in sorted(entries, key=lambda e: (e.date, _hhmm_to_time(e.start))):
            by_day.setdefault(entry.date, []).append(entry)
        for day in sorted(by_day):
            lines.append("")
            lines.append(f"## {day.strftime('%a')} {day.isoformat()}")
            for entry in by_day[day]:
                lines.append(_line_for(entry))
        self._write(self.log_path(iso), "\n".join(lines) + "\n")

    def append_entry(self, entry: Entry) -> Entry:
        iso = week_key(entry.date)
        entries = self.read_entries(iso)
        entries.append(entry)
        self.write_entries(iso, entries)
        return entry

    def append_span(self, start: datetime, end: datetime, text: str, kind: str = "checkin") -> list[Entry]:
        made: list[Entry] = []
        for chunk in split_span(start, end, text, kind):
            self.append_entry(chunk)
            made.append(chunk)
        return made

    def delete_entry(self, iso: str, index: int) -> bool:
        entries = self.read_entries(iso)
        if 0 <= index < len(entries):
            entries.pop(index)
            self.write_entries(iso, entries)
            return True
        return False

    def latest_entry_end(self) -> datetime | None:
        """The end of the newest real entry, for when settings has no marker."""
        best: datetime | None = None
        for iso in self.list_weeks()[:3]:
            for entry in self.read_entries(iso):
                if entry.kind == "missed":
                    continue
                moment = datetime.combine(entry.date, _hhmm_to_time(entry.end))
                if best is None or moment > best:
                    best = moment
        return best

    def entries_between(self, start: datetime, end: datetime) -> list[Entry]:
        seen: dict[str, Entry] = {}
        cursor = start.date()
        while cursor <= end.date():
            iso = week_key(cursor)
            for entry in self.read_entries(iso):
                key = f"{entry.date}|{entry.start}|{entry.text}"
                seen[key] = entry
            cursor += timedelta(days=7)
        out = [e for e in seen.values()
               if start <= datetime.combine(e.date, _hhmm_to_time(e.start)) < end]
        out.sort(key=lambda e: (e.date, _hhmm_to_time(e.start)))
        return out

    # -- plan -------------------------------------------------------------- #
    def read_plan(self, iso: str) -> dict:
        path = self.plan_path(iso)
        raw = path.read_text(encoding="utf-8") if path.is_file() else ""
        if not raw.strip():
            return empty_plan(iso)
        return parse_plan(raw, iso)

    def write_plan(self, iso: str, plan: dict) -> dict:
        self._write(self.plan_path(iso), render_plan(plan, iso))
        return self.read_plan(iso)

    def write_plan_raw(self, iso: str, raw: str) -> dict:
        self._write(self.plan_path(iso), raw)
        return self.read_plan(iso)

    # -- reports ----------------------------------------------------------- #
    def read_report(self, iso: str) -> dict | None:
        return _read_report_file(self.report_path(iso))

    def write_report(self, iso: str, markdown: str, meta: dict) -> dict:
        body = _front_matter(meta) + "\n" + markdown
        self._write(self.report_path(iso), body)
        return self.read_report(iso) or {}

    def read_month_report(self, key: str) -> dict | None:
        return _read_report_file(self.month_report_path(key))

    def write_month_report(self, key: str, markdown: str, meta: dict) -> dict:
        body = _front_matter(meta) + "\n" + markdown
        self._write(self.month_report_path(key), body)
        return self.read_month_report(key) or {}

    # -- discovery / export ------------------------------------------------ #
    def list_weeks(self) -> list[str]:
        if not self.root.exists():
            return []
        found = []
        for path in self.root.glob("*/*-W*"):
            if path.is_dir() and (path / "log.md").is_file():
                found.append(path.name)
        return sorted(found, reverse=True)

    def list_months(self) -> list[str]:
        if not self.root.exists():
            return []
        found = []
        for path in self.root.glob("*/*-*"):
            if path.is_dir() and re.fullmatch(r"\d{4}-\d{2}", path.name) and (path / "report.md").is_file():
                found.append(path.name)
        return sorted(found, reverse=True)

    def export_bundle(self) -> dict:
        payload = {"settings_exported_at": datetime.now().isoformat(timespec="seconds"), "weeks": []}
        for iso in self.list_weeks():
            week = self.read_week(iso)
            payload["weeks"].append(week.to_dict())
        return payload

    def export_markdown(self) -> str:
        chunks: list[str] = ["# What I Did — full export", ""]
        for iso in sorted(self.list_weeks()):
            week = self.read_week(iso)
            chunks.append(f"## Week {iso}")
            chunks.append("")
            chunks.append(render_plan(week.plan, iso).strip())
            chunks.append("")
            chunks.append(self.log_path(iso).read_text(encoding="utf-8").strip())
            if week.report:
                chunks.append("")
                chunks.append(week.report.get("markdown", "").strip())
            chunks.append("")
        return "\n".join(chunks) + "\n"


def _pad(value: str) -> str:
    h, m = value.split(":")[:2]
    return f"{int(h):02d}:{int(m):02d}"


# --------------------------------------------------------------------------- #
# plan rendering / parsing
# --------------------------------------------------------------------------- #
def empty_plan(iso: str) -> dict:
    start, _ = week_bounds(iso)
    return {
        "month_label": start.strftime("%B %Y"),
        "month": [],
        "week": [],
        "today_date": "",
        "today": [],
        "raw": "",
        "written": False,
    }


def _items(lines: list[str]) -> list[dict]:
    out: list[dict] = []
    used: dict[str, int] = {}
    for line in lines:
        stripped = line.strip()
        checked = CHECK_RE.match(stripped)
        bullet = BULLET_RE.match(stripped)
        match = checked or bullet
        if not match:
            continue
        body = match.group("text").strip()
        if not body:
            continue
        done = bool(checked and checked.group("mark").lower() == "x")
        slug = txt.slugify(body)
        if slug in used:
            used[slug] += 1
            slug = f"{slug}-{used[slug]}"
        else:
            used[slug] = 0
        out.append({"text": body, "done": done, "slug": slug})
    return out


def parse_plan(raw: str, iso: str) -> dict:
    plan = empty_plan(iso)
    sections: dict[str, list[str]] = {"month": [], "week": [], "today": []}
    current = None
    for line in raw.splitlines():
        stripped = line.strip()
        head = PLAN_HEAD_RE.match(stripped)
        if head and not stripped.startswith("# "):
            key = head.group("head").lower()
            if "month" in key:
                current = "month"
                label = re.sub(r"^.*?[—–-]\s*", "", head.group("head")).strip()
                if label:
                    plan["month_label"] = label
            elif "week" in key:
                current = "week"
            elif "today" in key or "day" in key:
                current = "today"
                date_match = re.search(r"(\d{4}-\d{2}-\d{2})", head.group("head"))
                plan["today_date"] = date_match.group(1) if date_match else ""
            else:
                current = None
            continue
        if current:
            sections[current].append(line)
    for key in ("month", "week", "today"):
        plan[key] = _items(sections[key])
    plan["raw"] = raw
    plan["written"] = any(plan[k] for k in ("month", "week", "today"))
    return plan


def render_plan(plan: dict, iso: str) -> str:
    start, _ = week_bounds(iso)
    month_label = plan.get("month_label") or start.strftime("%B %Y")
    lines = [f"# Week {iso.split('-W')[1]}, {iso.split('-')[0]} — plan", ""]
    lines.append(f"## Month — {month_label}")
    lines.append("")
    for item in plan.get("month") or []:
        lines.append(f"- {'[x]' if item.get('done') else '[ ]'} {item['text']}")
    lines.append("")
    lines.append("## This week")
    lines.append("")
    for item in plan.get("week") or []:
        lines.append(f"- {'[x]' if item.get('done') else '[ ]'} {item['text']}")
    lines.append("")
    label = plan.get("today_date") or start.isoformat()
    lines.append(f"## Today — {label}")
    lines.append("")
    for item in plan.get("today") or []:
        lines.append(f"- {'[x]' if item.get('done') else '[ ]'} {item['text']}")
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# report files
# --------------------------------------------------------------------------- #
def _front_matter(meta: dict) -> str:
    lines = ["---"]
    for key, value in meta.items():
        if isinstance(value, bool):
            value = "true" if value else "false"
        lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines)


def _read_report_file(path: Path) -> dict | None:
    if not path.is_file():
        return None
    raw = path.read_text(encoding="utf-8")
    meta: dict = {}
    body = raw
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].strip().splitlines():
                if ":" in line:
                    key, _, value = line.partition(":")
                    meta[key.strip()] = value.strip()
            body = parts[2]
    score = meta.get("score")
    try:
        score = int(score) if score is not None and str(score).strip() != "" else None
    except ValueError:
        score = None
    return {
        "meta": meta,
        "score": score,
        "source": meta.get("source", "local"),
        "generated_at": meta.get("generated", ""),
        "markdown": body.strip(),
        "raw": raw,
        "path": str(path),
    }
