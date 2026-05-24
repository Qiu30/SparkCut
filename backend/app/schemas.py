from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class WorkspaceSummary(BaseModel):
    id: str
    name: str
    created_at: datetime
    updated_at: datetime
    material_count: int
    job_count: int
    latest_job_status: Optional[str] = None


class MaterialOut(BaseModel):
    id: str
    workspace_id: str
    filename: str
    size_bytes: int
    order_index: int
    duration: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    audio_status: str
    probe_status: str
    asr_status: Optional[str] = None
    asr_updated_at: Optional[datetime] = None
    asr_error_message: Optional[str] = None
    created_at: datetime


class MaterialOrderUpdate(BaseModel):
    material_ids: List[str]


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    type: str = Field(pattern="^(clip|review)$")
    config: Dict[str, Any]


class TemplateOut(BaseModel):
    id: str
    name: str
    type: str
    config: Dict[str, Any]
    is_default: bool = False
    last_used_at: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class JobCreate(BaseModel):
    config: Dict[str, Any]


class FeedbackCreate(BaseModel):
    status: str = Field(pattern="^(usable|needs_edit|rejected)$")
    reason: str = Field(default="", max_length=500)


class RefineRequest(BaseModel):
    action: str = Field(pattern="^(adjust|regenerate)$")
    feedback: str = Field(min_length=1, max_length=1000)


class OutputVideoOut(BaseModel):
    id: str
    job_id: str
    name: str
    filename: str
    size_bytes: int
    duration: Optional[float] = None
    review_status: str
    feedback_status: Optional[str] = None
    feedback_reason: Optional[str] = None
    feedback_updated_at: Optional[str] = None
    created_at: datetime


class JobOut(BaseModel):
    id: str
    workspace_id: str
    status: str
    stage: str
    progress: int
    input_snapshot: Dict[str, Any]
    explainability: Dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    source_job_id: Optional[str] = None
    outputs: List[OutputVideoOut] = Field(default_factory=list)


class JobListItem(BaseModel):
    id: str
    workspace_id: str
    status: str
    stage: str
    progress: int
    rule_summary: str
    whisper_model: str
    output_count: int
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None


class WorkspaceDetail(BaseModel):
    id: str
    name: str
    created_at: datetime
    updated_at: datetime
    materials: List[MaterialOut]
    jobs: List[JobListItem]


class LogsOut(BaseModel):
    lines: List[str]
    next_offset: int
    status: str
    stage: str
    progress: int


class DuplicateOut(BaseModel):
    job: JobOut


class StorageSummary(BaseModel):
    storage_bytes: int
    material_count: int
    output_count: int
    missing_files: int
    cleanup_available: bool


class PipelineStatus(BaseModel):
    mode: str
    ffmpeg_available: bool
    ffprobe_available: bool
    llm_configured: bool
    llm_endpoint_configured: bool
    whisper_configured: bool
    max_concurrent_jobs: int
    recover_jobs: bool
    queue_depth: int
    active_jobs: int
    worker_count: int
    task_ready: bool
    blocking_requirements: List[str]
    missing_env_vars: List[str]
    warnings: List[str]


class LlmModelsOut(BaseModel):
    models: List[str]
    default_model: str
    source: str
    error: Optional[str] = None


class RuntimeSettingsOut(BaseModel):
    pipeline_mode: str
    llm_endpoint: str = ""
    llm_api_key_set: bool = False
    llm_api_key_preview: str = ""
    llm_model: str
    llm_models: List[str] = Field(default_factory=list)
    default_whisper_model: str
    asr_clip_seconds: float


class RuntimeSettingsUpdate(BaseModel):
    pipeline_mode: Optional[str] = None
    llm_endpoint: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_model: Optional[str] = None
    default_whisper_model: Optional[str] = None
    asr_clip_seconds: Optional[float] = None
