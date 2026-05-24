from __future__ import annotations

import json
import os
import queue
import threading
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from .engine import PipelineCancelled, PipelineRuntimeError, StageGuard
from ..llm_models import normalize_llm_urls
from ..prompts import build_llm_messages


def _llm_model_for_snapshot(snapshot: Dict[str, Any], settings, config_key: str = "clipModel") -> str:
    config = snapshot.get("config", {})
    if not isinstance(config, dict):
        config = {}
    selected = str(config.get(config_key) or "").strip()
    return selected or settings.llm_model


def _call_llm(snapshot: Dict[str, Any], settings, is_cancelled: Optional[StageGuard] = None) -> str:
    model = _llm_model_for_snapshot(snapshot, settings, "clipModel")
    messages = build_llm_messages(snapshot, model)
    return _call_llm_with_messages(messages, settings, model=model, is_cancelled=is_cancelled)


def _call_llm_with_messages(
    messages: list[Dict[str, str]],
    settings,
    model: Optional[str] = None,
    is_cancelled: Optional[StageGuard] = None,
) -> str:
    api_key = os.environ.get("VIDEO_CUT_LLM_API_KEY")
    if not settings.llm_endpoint or not api_key:
        raise PipelineRuntimeError("LLM endpoint/key not configured")
    request_model = model or settings.llm_model
    payload = {
        "model": request_model,
        "messages": messages,
        "temperature": 0.2,
    }
    llm_urls = normalize_llm_urls(settings.llm_endpoint)
    if not llm_urls.chat_completions_url:
        raise PipelineRuntimeError("LLM endpoint/key not configured")
    request = urllib.request.Request(
        llm_urls.chat_completions_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        data = _request_json_cancellable(request, settings.llm_timeout_seconds, is_cancelled)
    except urllib.error.HTTPError as exc:
        raise PipelineRuntimeError(f"LLM HTTP {exc.code}") from exc
    choices = data.get("choices") or []
    if not choices:
        raise PipelineRuntimeError("LLM returned no choices")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if not content:
        raise PipelineRuntimeError("LLM returned empty content")
    return str(content)


def _send_json_request(request: urllib.request.Request, timeout: int) -> Dict[str, Any]:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise PipelineRuntimeError("LLM returned invalid JSON payload")
    return data


def _request_json_cancellable(
    request: urllib.request.Request,
    timeout: int,
    is_cancelled: Optional[StageGuard],
) -> Dict[str, Any]:
    if is_cancelled is None:
        return _send_json_request(request, timeout)
    if is_cancelled():
        raise PipelineCancelled()

    result_queue: "queue.Queue[tuple[str, Any]]" = queue.Queue(maxsize=1)

    def target() -> None:
        try:
            result_queue.put(("ok", _send_json_request(request, timeout)), block=False)
        except Exception as exc:  # pragma: no cover - exercised through queue result
            result_queue.put(("error", exc), block=False)

    threading.Thread(target=target, daemon=True).start()
    while True:
        if is_cancelled():
            raise PipelineCancelled()
        try:
            status, payload = result_queue.get(timeout=0.2)
        except queue.Empty:
            continue
        if status == "error":
            raise payload
        if not isinstance(payload, dict):
            raise PipelineRuntimeError("LLM returned invalid JSON payload")
        return payload


def _extract_json_object(content: str) -> Optional[Dict[str, Any]]:
    start = content.find("{")
    end = content.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(content[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None

