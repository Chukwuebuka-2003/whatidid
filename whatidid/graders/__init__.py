"""Grading entry points: pick the offline analyser or the model, always fall back."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ..config import Settings
from ..store import Store, render_plan, week_key
from . import analysis as analysis_mod
from . import llm, render


def _now(now: datetime | None) -> datetime:
    return (now or datetime.now()).replace(microsecond=0)


def grade_week(store: Store, settings: Settings, iso: str | None = None,
               now: datetime | None = None) -> dict:
    now = _now(now)
    iso = iso or week_key(now)
    week = store.read_week(iso)
    result = analysis_mod.analyse(week, settings, now)

    payload: dict | None = None
    error: str | None = None
    source = "local"
    model = ""

    wants_model = settings.grader == "llm"
    if wants_model:
        plan_md = render_plan(week.plan, iso)
        log_md = store.log_path(iso).read_text(encoding="utf-8") if store.log_path(iso).is_file() else ""
        try:
            payload = llm.grade(settings, plan_md, log_md, result, settings.tone)
            source = "llm"
            model = f"{settings.llm_provider}/{settings.llm_model}"
        except llm.GraderError as exc:
            error = str(exc)

    if payload:
        markdown = render.render_llm_week(payload, result, model, settings.tone)
        score = payload.get("score")
    else:
        markdown = render.render_week(result, settings.tone, source="local")
        score = result.get("score")

    meta = {
        "week": iso,
        "score": score if score is not None else "",
        "source": source,
        "model": model,
        "tone": settings.tone,
        "generated": now.isoformat(timespec="seconds"),
    }
    saved = store.write_report(iso, markdown, meta)
    return {
        "iso": iso,
        "analysis": result,
        "markdown": markdown,
        "score": score,
        "source": source,
        "model": model,
        "error": error,
        "report": saved,
    }


def grade_month(store: Store, settings: Settings, month: str | None = None,
                now: datetime | None = None) -> dict:
    now = _now(now)
    month = month or now.strftime("%Y-%m")
    summary = analysis_mod.analyse_month(store, month, settings, now)
    markdown = render.render_month(summary, settings.tone)
    saved = store.write_month_report(month, markdown, {
        "month": month,
        "score": summary.get("average_score") or "",
        "source": "local",
        "tone": settings.tone,
        "generated": now.isoformat(timespec="seconds"),
    })
    return {"month": month, "summary": summary, "markdown": markdown, "report": saved}


def default_data_dir() -> Path:
    from ..config import DEFAULT_DATA_DIR
    return DEFAULT_DATA_DIR
