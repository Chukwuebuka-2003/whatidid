"""Optional model grader. One HTTP call, the user's key, the user's provider.

Supported: any OpenAI-compatible endpoint (OpenAI, DeepSeek, Groq, OpenRouter,
LM Studio), Anthropic, Google Gemini, and a local Ollama daemon.

Nothing here is required for the app to work: if there is no key, the offline
analyser grades the week instead.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from ..config import DEFAULT_MODELS, Settings
from . import prompts


class GraderError(RuntimeError):
    """Raised when the model call fails; callers fall back to the offline grader."""


def _post(url: str, payload: dict, headers: dict, timeout: int = 120) -> dict:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    for key, value in headers.items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:400]
        except Exception:  # pragma: no cover - best effort only
            pass
        raise GraderError(f"{exc.code} {exc.reason}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise GraderError(f"could not reach the provider: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise GraderError("the provider returned something that isn't JSON") from exc


def _openai(settings: Settings, system: str, user: str) -> str:
    base = (settings.llm_base_url or "https://api.openai.com/v1").rstrip("/")
    data = _post(
        f"{base}/chat/completions",
        {
            "model": settings.llm_model or DEFAULT_MODELS["openai"],
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.3,
        },
        {"Authorization": f"Bearer {settings.llm_api_key}"},
    )
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise GraderError("unexpected response shape from the OpenAI-compatible endpoint") from exc


def _anthropic(settings: Settings, system: str, user: str) -> str:
    base = (settings.llm_base_url or "https://api.anthropic.com").rstrip("/")
    data = _post(
        f"{base}/v1/messages",
        {
            "model": settings.llm_model or DEFAULT_MODELS["anthropic"],
            "max_tokens": 2000,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        },
        {"x-api-key": settings.llm_api_key, "anthropic-version": "2023-06-01"},
    )
    try:
        return "".join(block.get("text", "") for block in data["content"])
    except (KeyError, TypeError) as exc:
        raise GraderError("unexpected response shape from Anthropic") from exc


def _gemini(settings: Settings, system: str, user: str) -> str:
    model = settings.llm_model or DEFAULT_MODELS["gemini"]
    base = (settings.llm_base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
    data = _post(
        f"{base}/models/{model}:generateContent?key={settings.llm_api_key}",
        {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": 0.3, "responseMimeType": "application/json"},
        },
        {},
    )
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise GraderError("unexpected response shape from Gemini") from exc


def _ollama(settings: Settings, system: str, user: str) -> str:
    base = (settings.llm_base_url or "http://127.0.0.1:11434").rstrip("/")
    data = _post(
        f"{base}/api/chat",
        {
            "model": settings.llm_model or DEFAULT_MODELS["ollama"],
            "stream": False,
            "format": "json",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "options": {"temperature": 0.3},
        },
        {},
        timeout=300,
    )
    try:
        return data["message"]["content"]
    except (KeyError, TypeError) as exc:
        raise GraderError("unexpected response shape from Ollama") from exc


PROVIDERS = {
    "openai": _openai,
    "anthropic": _anthropic,
    "gemini": _gemini,
    "ollama": _ollama,
}


def extract_json(raw: str) -> dict:
    text = (raw or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise GraderError("the model didn't return a JSON object")
    try:
        payload = json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise GraderError(f"the model's JSON didn't parse: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise GraderError("the model returned JSON that isn't an object")
    return payload


def normalise(payload: dict, fallback_score: int | None) -> dict:
    score = payload.get("score")
    try:
        score = int(round(float(score))) if score is not None else fallback_score
    except (TypeError, ValueError):
        score = fallback_score
    if score is not None:
        score = max(1, min(10, score))

    pairs = []
    for pair in payload.get("said_vs_did") or []:
        if not isinstance(pair, dict):
            continue
        pairs.append({
            "said": str(pair.get("said", "")).strip(),
            "did": str(pair.get("did", "")).strip(),
            "verdict": str(pair.get("verdict", "")).strip().lower(),
        })
    notes = [str(n).strip() for n in (payload.get("notes") or []) if str(n).strip()]
    return {
        "score": score,
        "verdict": str(payload.get("verdict", "")).strip(),
        "said_vs_did": pairs,
        "pattern": str(payload.get("pattern", "")).strip(),
        "instruction": str(payload.get("instruction", "")).strip(),
        "notes": notes,
    }


def grade(settings: Settings, plan_markdown: str, log_markdown: str, analysis: dict, tone: str) -> dict:
    provider = PROVIDERS.get(settings.llm_provider)
    if provider is None:
        raise GraderError(f"unknown provider: {settings.llm_provider}")
    if settings.llm_provider != "ollama" and not settings.llm_api_key:
        raise GraderError("no API key saved")
    user = prompts.build_user(plan_markdown, log_markdown, analysis, tone)
    return normalise(extract_json(provider(settings, prompts.SYSTEM, user)), analysis.get("score"))
