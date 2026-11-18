"""Settings: config + small amount of live schedule state, stored as one JSON file.

Everything lives in the data directory the user picks, so the whole app is
"a folder of files". The API key is written with 0600 permissions.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

DEFAULT_DATA_DIR = Path.home() / ".whatidid"
SETTINGS_NAME = "settings.json"


def _clamp_int(value, low, high, fallback):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(high, value))


def _hhmm(value, fallback):
    try:
        h, m = str(value).split(":")
        h, m = int(h), int(m)
    except (ValueError, AttributeError):
        return fallback
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return fallback
    return f"{h:02d}:{m:02d}"


TONES = ("gentle", "honest", "brutal")
PROVIDERS = ("openai", "anthropic", "gemini", "ollama")

DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-haiku-latest",
    "gemini": "gemini-2.0-flash",
    "ollama": "llama3.1",
}


@dataclass
class Settings:
    # schedule
    interval_minutes: int = 90
    active_start: str = "08:00"
    active_end: str = "22:00"
    weekday_only: bool = False
    max_ask_minutes: int = 480

    # behaviour
    tone: str = "honest"
    grader: str = "local"          # "local" (no key, free) or "llm"
    llm_provider: str = "openai"
    llm_model: str = ""
    llm_base_url: str = ""
    llm_api_key: str = ""

    # live schedule state (persisted so a reload or restart doesn't lose the clock)
    next_due_at: str | None = None
    last_entry_end: str | None = None
    deep_work: bool = False
    deep_work_since: str | None = None
    muted: bool = False

    @classmethod
    def load(cls, data_dir: Path) -> "Settings":
        path = Path(data_dir) / SETTINGS_NAME
        raw = {}
        if path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8") or "{}")
            except (json.JSONDecodeError, OSError):
                raw = {}
        known = {f.name for f in fields(cls)}
        inst = cls(**{k: v for k, v in raw.items() if k in known})
        return inst.normalised()

    def normalised(self) -> "Settings":
        self.interval_minutes = _clamp_int(self.interval_minutes, 1, 480, 90)
        self.max_ask_minutes = _clamp_int(self.max_ask_minutes, 15, 1440, 480)
        self.active_start = _hhmm(self.active_start, "08:00")
        self.active_end = _hhmm(self.active_end, "22:00")
        if self.tone not in TONES:
            self.tone = "honest"
        if self.grader not in ("local", "llm"):
            self.grader = "local"
        if self.llm_provider not in PROVIDERS:
            self.llm_provider = "openai"
        self.weekday_only = bool(self.weekday_only)
        self.deep_work = bool(self.deep_work)
        self.muted = bool(self.muted)
        if not self.llm_model:
            self.llm_model = DEFAULT_MODELS.get(self.llm_provider, "")
        return self

    def save(self, data_dir: Path) -> None:
        path = Path(data_dir) / SETTINGS_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.public(redact=False), indent=2) + "\n", encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)

    def public(self, redact: bool = True) -> dict:
        data = asdict(self)
        if redact:
            data["llm_api_key"] = ""
            data["llm_api_key_set"] = bool(self.llm_api_key)
        return data

    def update(self, patch: dict) -> "Settings":
        known = {f.name for f in fields(self)}
        for key, value in (patch or {}).items():
            if key in known and key not in ("llm_api_key_set",):
                setattr(self, key, value)
        return self.normalised()
