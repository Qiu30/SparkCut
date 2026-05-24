from __future__ import annotations

import os

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..db_helpers import storage_summary
from ..llm_models import fetch_llm_models
from ..pipeline import pipeline_status
from ..schemas import LlmModelsOut, PipelineStatus, RuntimeSettingsOut, RuntimeSettingsUpdate, StorageSummary
from ..settings import get_pipeline_settings, read_local_env_values, update_runtime_env
from ..worker import runner_status


router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/storage/summary", response_model=StorageSummary)
def get_storage_summary(db: Session = Depends(get_db)):
    return storage_summary(db)


@router.get("/pipeline/status", response_model=PipelineStatus)
def get_pipeline_status():
    return pipeline_status(runner_status())


@router.get("/llm/models", response_model=LlmModelsOut)
def get_llm_models():
    return fetch_llm_models()


def _api_key_preview(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return f"{value[:3]}****{value[-4:]}"


def _runtime_settings_payload() -> dict:
    settings = get_pipeline_settings()
    models_result = fetch_llm_models()
    env_values = read_local_env_values()
    api_key = env_values.get("VIDEO_CUT_LLM_API_KEY") or os.environ.get("VIDEO_CUT_LLM_API_KEY") or ""
    models = models_result.get("models") or []
    return {
        "pipeline_mode": settings.mode,
        "llm_endpoint": settings.llm_endpoint or "",
        "llm_api_key_set": bool(api_key),
        "llm_api_key_preview": _api_key_preview(api_key),
        "llm_model": settings.llm_model,
        "llm_models": models if isinstance(models, list) else [],
        "llm_timeout_seconds": settings.llm_timeout_seconds,
        "default_whisper_model": settings.default_whisper_model,
        "asr_clip_seconds": settings.asr_clip_seconds,
    }


@router.get("/settings/runtime", response_model=RuntimeSettingsOut)
def get_runtime_settings():
    return _runtime_settings_payload()


@router.put("/settings/runtime", response_model=RuntimeSettingsOut)
def update_runtime_settings(payload: RuntimeSettingsUpdate):
    updates = {}
    if payload.llm_endpoint is not None:
        updates["VIDEO_CUT_LLM_ENDPOINT"] = payload.llm_endpoint.strip()
    if payload.llm_api_key is not None:
        updates["VIDEO_CUT_LLM_API_KEY"] = payload.llm_api_key.strip()
    if payload.llm_model is not None:
        updates["VIDEO_CUT_LLM_MODEL"] = payload.llm_model.strip()
    if payload.llm_timeout_seconds is not None:
        updates["VIDEO_CUT_LLM_TIMEOUT_SECONDS"] = max(5, payload.llm_timeout_seconds)
    if payload.default_whisper_model is not None:
        updates["VIDEO_CUT_DEFAULT_WHISPER_MODEL"] = payload.default_whisper_model.strip()
    if payload.asr_clip_seconds is not None:
        updates["VIDEO_CUT_ASR_CLIP_SECONDS"] = max(0.0, payload.asr_clip_seconds)
    update_runtime_env(updates)
    return _runtime_settings_payload()
