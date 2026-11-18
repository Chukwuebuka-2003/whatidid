"""The local HTTP server: a JSON API plus the static app, bound to 127.0.0.1.

No auth on purpose — it binds to loopback and only ever serves one person's
folder of markdown. `--host 0.0.0.0` is possible for a phone on the same wifi,
and the README says what that means.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, date, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import graders, schedule
from .config import DEFAULT_DATA_DIR, Settings
from .graders import analysis as analysis_mod
from .store import (Entry, Store, month_key, render_plan, week_key)

VERSION = "0.1.0"


def _web_dir() -> Path:
    """Where the HTML lives: beside the package when run from a checkout, or in
    share/whatidid/web when installed from a wheel."""
    here = Path(__file__).resolve().parent
    candidates = [
        here / "web",                                     # installed inside the package
        here.parent / "web",                              # from a source checkout
        Path(sys.prefix) / "share" / "whatidid" / "web",  # pip data-files
        Path("/usr/local/share/whatidid/web"),
    ]
    for candidate in candidates:
        if (candidate / "index.html").is_file():
            return candidate
    return here.parent / "web"


WEB_DIR = _web_dir()


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


def create_app(data_dir: Path | str | None = None) -> FastAPI:
    root = Path(data_dir).expanduser() if data_dir else DEFAULT_DATA_DIR
    store = Store(root)
    store.ensure()
    settings = Settings.load(root)
    settings.save(root)

    app = FastAPI(title="What I Did", version=VERSION, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.store = store
    app.state.settings = settings
    app.state.root = root

    # ---------------------------------------------------------------- helpers
    def iso_for(value: str | None) -> str:
        if not value:
            return week_key(_now())
        try:
            if len(value) == 10 and value[4] == "-" and value[7] == "-":
                return week_key(date.fromisoformat(value))
            if "-W" in value:
                year, week = value.split("-W")
                date.fromisocalendar(int(year), int(week), 1)
                return f"{year}-W{int(week):02d}"
        except ValueError as exc:
            raise HTTPException(400, f"bad week: {value}") from exc
        raise HTTPException(400, f"bad week: {value}")

    def last_hint():
        return store.latest_entry_end()

    def week_payload(iso: str) -> dict:
        week = store.read_week(iso)
        data = week.to_dict()
        data["log_path"] = str(store.log_path(iso))
        data["plan_path"] = str(store.plan_path(iso))
        data["report_path"] = str(store.report_path(iso))
        data["analysis"] = analysis_mod.analyse(week, settings, _now())
        return data

    def save_settings() -> None:
        settings.save(root)

    # -------------------------------------------------------------------- app
    @app.get("/api/bootstrap")
    def bootstrap(week: str | None = None):
        iso = iso_for(week)
        today = _now().date()
        return {
            "version": VERSION,
            "now": _now().isoformat(),
            "today": today.isoformat(),
            "data_dir": str(root),
            "settings": settings.public(),
            "due": schedule.due_state(settings, _now(), last_hint()),
            "week": week_payload(iso),
            "current_week": week_key(today),
            "weeks": store.list_weeks(),
            "months": store.list_months(),
            "today_key": today.isoformat(),
        }

    @app.get("/api/due")
    def due():
        state = schedule.due_state(settings, _now(), last_hint())
        save_settings()
        return state

    # ------------------------------------------------------------------- plan
    @app.post("/api/plan")
    async def save_plan(request: Request):
        payload = await request.json()
        iso = iso_for(payload.get("week"))
        current = store.read_plan(iso)
        merged = {
            "month_label": payload.get("month_label") or current.get("month_label"),
            "month": payload.get("month", current.get("month", [])),
            "week": payload.get("week_items", payload.get("week", current.get("week", []))),
            "today": payload.get("today", current.get("today", [])),
            "today_date": payload.get("today_date") or current.get("today_date") or _now().date().isoformat(),
        }
        for key in ("month", "week", "today"):
            cleaned = []
            for item in merged[key] or []:
                if isinstance(item, str):
                    item = {"text": item, "done": False}
                text_value = str(item.get("text", "")).strip()
                if text_value:
                    cleaned.append({"text": text_value, "done": bool(item.get("done"))})
            merged[key] = cleaned
        store.write_plan(iso, merged)
        return {"week": week_payload(iso)}

    @app.post("/api/plan/raw")
    async def save_plan_raw(request: Request):
        payload = await request.json()
        iso = iso_for(payload.get("week"))
        store.write_plan_raw(iso, str(payload.get("raw", "")))
        return {"week": week_payload(iso)}

    @app.get("/api/plan")
    def get_plan(week: str | None = None):
        iso = iso_for(week)
        return {"week": iso, "plan": store.read_plan(iso), "markdown": render_plan(store.read_plan(iso), iso)}

    # ---------------------------------------------------------------- entries
    @app.post("/api/checkin")
    async def checkin(request: Request):
        payload = await request.json()
        text_value = str(payload.get("text", "")).strip()
        if not text_value:
            raise HTTPException(400, "an answer needs at least one word")
        now = _now()
        state = schedule.due_state(settings, now, last_hint())
        last = schedule.effective_last(settings, last_hint())
        start, end = schedule.ask_span(settings, last, now)
        entries = store.append_span(start, end, text_value, kind="checkin")
        schedule.schedule_from_answer(settings, now)
        save_settings()
        return {
            "entries": [e.to_dict() for e in entries],
            "due": schedule.due_state(settings, now, last_hint()),
            "week": week_key(now),
            "asked": {"start": start.isoformat(), "end": end.isoformat(),
                      "minutes": state.get("ask_minutes")},
        }

    @app.post("/api/checkin/skip")
    async def skip(request: Request):
        payload = {}
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        now = _now()
        last = schedule.effective_last(settings, last_hint())
        start, end = schedule.ask_span(settings, last, now)
        store.append_span(start, end, "(no answer)", kind="missed")
        schedule.schedule_from_answer(settings, now)
        save_settings()
        return {"skipped": True, "due": schedule.due_state(settings, now, last_hint()),
                "week": week_key(now), "reason": payload.get("reason", "")}

    @app.post("/api/checkin/snooze")
    async def snooze(request: Request):
        payload = await request.json()
        minutes = int(payload.get("minutes", 15))
        now = _now()
        schedule.snooze(settings, minutes, now)
        save_settings()
        return {"due": schedule.due_state(settings, now)}

    @app.post("/api/entries")
    async def add_entry(request: Request):
        payload = await request.json()
        text_value = str(payload.get("text", "")).strip()
        if not text_value:
            raise HTTPException(400, "an entry needs at least one word")
        day = payload.get("date") or _now().date().isoformat()
        try:
            entry_date = date.fromisoformat(str(day))
        except ValueError as exc:
            raise HTTPException(400, "date must be YYYY-MM-DD") from exc
        start = str(payload.get("start") or "09:00")
        end = str(payload.get("end") or start)
        try:
            start_dt = datetime.combine(entry_date, datetime.strptime(start, "%H:%M").time())
            end_dt = datetime.combine(entry_date, datetime.strptime(end, "%H:%M").time())
        except ValueError as exc:
            raise HTTPException(400, "times must be HH:MM") from exc
        if end_dt <= start_dt:
            end_dt += timedelta(days=1)
        made = store.append_span(start_dt, end_dt, text_value, kind="manual")
        return {"entries": [e.to_dict() for e in made], "week": week_key(entry_date)}

    @app.delete("/api/entries/{iso}/{index}")
    def delete_entry(iso: str, index: int):
        if not store.delete_entry(iso, index):
            raise HTTPException(404, "no such entry")
        return {"deleted": True, "week": week_payload(iso)}

    @app.patch("/api/entries/{iso}/{index}")
    async def edit_entry(iso: str, index: int, request: Request):
        payload = await request.json()
        entries = store.read_entries(iso)
        if not (0 <= index < len(entries)):
            raise HTTPException(404, "no such entry")
        text_value = str(payload.get("text", "")).strip()
        if not text_value:
            raise HTTPException(400, "an entry needs at least one word")
        entries[index].text = text_value
        entries[index].kind = "missed" if text_value.lower() == "(no answer)" else "checkin"
        store.write_entries(iso, entries)
        return {"week": week_payload(iso)}

    # --------------------------------------------------------------- controls
    @app.post("/api/deepwork")
    async def deepwork(request: Request):
        payload = await request.json()
        now = _now()
        if payload.get("on"):
            schedule.start_deep_work(settings, now)
        else:
            schedule.stop_deep_work(settings, now)
        save_settings()
        return {"due": schedule.due_state(settings, now)}

    @app.post("/api/mute")
    async def mute(request: Request):
        payload = await request.json()
        settings.muted = bool(payload.get("muted"))
        if not settings.muted:
            schedule.schedule_from_now(settings, _now())
        save_settings()
        return {"due": schedule.due_state(settings, _now())}

    # ---------------------------------------------------------------- reports
    @app.post("/api/report/week")
    async def report_week(request: Request):
        payload = {}
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        iso = iso_for(payload.get("week"))
        result = graders.grade_week(store, settings, iso, _now())
        return result

    @app.get("/api/report/week")
    def get_report(week: str | None = None):
        iso = iso_for(week)
        report = store.read_report(iso)
        return {"week": iso, "report": report,
                "analysis": analysis_mod.analyse(store.read_week(iso), settings, _now())}

    @app.post("/api/report/month")
    async def report_month(request: Request):
        payload = {}
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        month = payload.get("month") or month_key(_now())
        return graders.grade_month(store, settings, month, _now())

    @app.get("/api/report/month")
    def get_month_report(month: str | None = None):
        key = month or month_key(_now())
        return {"month": key, "report": store.read_month_report(key),
                "summary": analysis_mod.analyse_month(store, key, settings, _now())}

    # --------------------------------------------------------------- settings
    @app.get("/api/settings")
    def get_settings():
        return {"settings": settings.public(), "data_dir": str(root)}

    @app.put("/api/settings")
    async def put_settings(request: Request):
        nonlocal root
        payload = await request.json()
        patch = dict(payload)
        new_root = patch.pop("data_dir", None)
        if "llm_api_key" in patch and patch["llm_api_key"] == "":
            patch.pop("llm_api_key")  # "" means "leave it alone"; null clears it
        if patch.get("llm_api_key") is None:
            patch["llm_api_key"] = ""
        settings.update(patch)
        if "interval_minutes" in patch or "active_start" in patch or "active_end" in patch:
            schedule.schedule_from_now(settings, _now())
        if new_root and str(Path(new_root).expanduser()) != str(root):
            candidate = Path(new_root).expanduser()
            try:
                candidate.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise HTTPException(400, f"can't use that folder: {exc}") from exc
            test = candidate / ".write-test"
            try:
                test.write_text("ok", encoding="utf-8")
                test.unlink()
            except OSError as exc:
                raise HTTPException(400, f"that folder isn't writable: {exc}") from exc
            root = candidate
            app.state.root = root
            store.root = root
            store.ensure()
        save_settings()
        return {"settings": settings.public(), "data_dir": str(root)}

    @app.post("/api/settings/test-key")
    def test_key():
        """One cheap call to prove the key works, without touching the week."""
        from .graders import llm as llm_mod
        sample = {"score": 5, "logged_minutes": 60, "covered_days": 1, "answered": 3, "missed": 0,
                  "components": {"completion": 50, "alignment": 50, "coverage": 100}}
        try:
            result = llm_mod.grade(settings, "## This week\n- [ ] test the key\n",
                                   "## Mon 2026-01-01\n- 09:00–10:00 (1h) | tested the key #test-the-key\n",
                                   sample, "honest")
            return {"ok": True, "score": result.get("score"), "model": settings.llm_model}
        except llm_mod.GraderError as exc:
            return JSONResponse(status_code=400, content={"ok": False, "error": str(exc)})

    # --------------------------------------------------------------- files/io
    @app.get("/api/export")
    def export(format: str = "json"):
        if format == "md":
            body = store.export_markdown()
            return PlainTextResponse(body, headers={
                "Content-Disposition": f'attachment; filename="what-i-did-{_now().date().isoformat()}.md"'})
        payload = store.export_bundle()
        return JSONResponse(payload, headers={
            "Content-Disposition": f'attachment; filename="what-i-did-{_now().date().isoformat()}.json"'})

    @app.get("/api/file")
    def read_file(path: str):
        target = (root / path).resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError as exc:
            raise HTTPException(403, "outside the data folder") from exc
        if not target.is_file():
            raise HTTPException(404, "no such file")
        return {"path": str(target), "content": target.read_text(encoding="utf-8")}

    # ------------------------------------------------------------------ static
    @app.get("/", response_class=HTMLResponse)
    def index():
        page = WEB_DIR / "index.html"
        if not page.is_file():
            return HTMLResponse("<h1>What I Did</h1><p>The web folder is missing.</p>", status_code=500)
        return HTMLResponse(page.read_text(encoding="utf-8"))

    @app.get("/manifest.webmanifest")
    def manifest():
        return FileResponse(WEB_DIR / "manifest.webmanifest", media_type="application/manifest+json")

    @app.get("/icon.svg")
    def icon():
        return FileResponse(WEB_DIR / "icon.svg", media_type="image/svg+xml")

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "version": VERSION}

    if WEB_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

    return app