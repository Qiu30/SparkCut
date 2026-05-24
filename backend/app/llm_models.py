from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .settings import DEFAULT_LLM_MODEL, get_pipeline_settings


@dataclass(frozen=True)
class LlmUrls:
    chat_completions_url: str
    model_urls: list[str]
    mode: str


def _ensure_scheme(value: str) -> str:
    if "://" in value:
        return value
    return f"https://{value}"


def _append_path(base_path: str, suffix: str) -> str:
    base = base_path.rstrip("/")
    return f"{base}{suffix}" if base else suffix


def _without_suffix(path: str, suffix: str) -> str:
    return path[: -len(suffix)] if path.endswith(suffix) else path


def _ends_with_v1(path: str) -> bool:
    return path.rstrip("/").endswith("/v1") or path.rstrip("/") == "/v1"


def normalize_llm_urls(endpoint: str) -> LlmUrls:
    raw = (endpoint or "").strip()
    if not raw:
        return LlmUrls(chat_completions_url="", model_urls=[], mode="empty")

    exact = raw.endswith("#")
    if exact:
        raw = raw[:-1].strip()
    if not raw:
        return LlmUrls(chat_completions_url="", model_urls=[], mode="empty")

    trailing_slash = raw.endswith("/")
    parsed = urlsplit(_ensure_scheme(raw))

    if exact:
        exact_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))
        return LlmUrls(chat_completions_url=exact_url, model_urls=[exact_url], mode="exact")

    path = parsed.path.rstrip("/")
    query = ""
    mode = "auto_v1"

    if path.endswith("/chat/completions"):
        base_path = _without_suffix(path, "/chat/completions")
        chat_path = path
        mode = "chat_endpoint"
    elif path.endswith("/completions"):
        base_path = _without_suffix(path, "/completions")
        chat_path = path
        mode = "completions_endpoint"
    elif path.endswith("/models"):
        base_path = _without_suffix(path, "/models")
        chat_path = _append_path(base_path, "/chat/completions")
        mode = "models_endpoint"
    elif path.endswith("/model"):
        base_path = _without_suffix(path, "/model")
        chat_path = _append_path(base_path, "/chat/completions")
        mode = "model_endpoint"
    else:
        base_path = path
        if trailing_slash:
            mode = "slash_no_v1"
        elif not _ends_with_v1(base_path):
            base_path = _append_path(base_path, "/v1")
        chat_path = _append_path(base_path, "/chat/completions")

    candidates = [
        _append_path(base_path, "/models"),
        _append_path(base_path, "/model"),
        _append_path(base_path, "/chat/models"),
        _append_path(base_path, "/chat/model"),
    ]
    model_urls: list[str] = []
    for candidate in candidates:
        url = urlunsplit((parsed.scheme, parsed.netloc, candidate, query, ""))
        if url not in model_urls:
            model_urls.append(url)

    chat_url = urlunsplit((parsed.scheme, parsed.netloc, chat_path, query, ""))
    return LlmUrls(chat_completions_url=chat_url, model_urls=model_urls, mode=mode)


def derive_models_url(endpoint: str) -> str:
    urls = derive_model_urls(endpoint)
    return urls[0] if urls else ""


def derive_model_urls(endpoint: str) -> list[str]:
    return normalize_llm_urls(endpoint).model_urls


def _extract_model_ids(payload: Any) -> list[str]:
    if isinstance(payload, dict):
        raw_models = payload.get("data") or payload.get("models") or payload.get("model")
    else:
        raw_models = payload

    if isinstance(raw_models, str):
        return [raw_models]
    if not isinstance(raw_models, list):
        return []

    model_ids: list[str] = []
    for item in raw_models:
        model_id = item.get("id") if isinstance(item, dict) else item
        if isinstance(model_id, str) and model_id.strip() and model_id not in model_ids:
            model_ids.append(model_id.strip())
    return model_ids


def fallback_llm_models(reason: str = "unavailable") -> dict[str, Any]:
    settings = get_pipeline_settings()
    return {
        "models": [],
        "default_model": settings.llm_model or DEFAULT_LLM_MODEL,
        "source": "fallback",
        "error": reason,
    }


def fetch_llm_models() -> dict[str, Any]:
    settings = get_pipeline_settings()
    api_key = os.environ.get("VIDEO_CUT_LLM_API_KEY")
    if not settings.llm_endpoint or not api_key:
        return fallback_llm_models("not_configured")

    saw_response = False
    for models_url in derive_model_urls(settings.llm_endpoint):
        try:
            request = urllib.request.Request(
                models_url,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                method="GET",
            )
            with urllib.request.urlopen(request, timeout=min(settings.llm_timeout_seconds, 20)) as response:
                saw_response = True
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
        except Exception:
            continue

        models = _extract_model_ids(payload)
        if not models:
            continue

        default_model = settings.llm_model if settings.llm_model in models else models[0]
        return {
            "models": models,
            "default_model": default_model,
            "source": "remote",
            "error": None,
        }

    return fallback_llm_models("empty_response" if saw_response else "fetch_failed")
