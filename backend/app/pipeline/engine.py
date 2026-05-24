from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from sqlalchemy.orm import Session

from ..models import Job, OutputVideo
from ..db_helpers import add_log
from ..settings import ffmpeg_path, ffprobe_path, get_pipeline_settings


StageGuard = Callable[[], bool]


@dataclass(frozen=True)
class PipelineContext:
    db: Session
    job: Job
    settings: Any
    is_cancelled: StageGuard


class PipelineCancelled(Exception):
    pass


class PipelineRuntimeError(RuntimeError):
    pass


PIPELINE_STAGES = [
    ("probe", 12, "素材探查", "读取素材列表和基础信息"),
    ("asr", 28, "ASR 转写", "生成字幕与对白线索"),
    ("analysis", 48, "剧情分析", "生成片段时间线和方案摘要"),
    ("review", 62, "审查过滤", "应用审查规则并标记风险"),
    ("compose", 82, "视频合成", "切割和拼接片段"),
    ("package", 94, "视频包装", "应用剧名、字幕颜色、角标和片尾配置"),
]

def pipeline_status(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    settings = get_pipeline_settings()
    ffmpeg_available = bool(ffmpeg_path())
    ffprobe_available = bool(ffprobe_path())
    whisper_command_present = bool(settings.whisper_command)
    whisper_available = settings.whisper_configured
    missing_env_vars: list[str] = []
    blocking_requirements: list[str] = []
    warnings: list[str] = []

    if not settings.llm_endpoint:
        missing_env_vars.append("VIDEO_CUT_LLM_ENDPOINT")
        blocking_requirements.append("VIDEO_CUT_LLM_ENDPOINT is required for the real pipeline")
    if not os.environ.get("VIDEO_CUT_LLM_API_KEY"):
        missing_env_vars.append("VIDEO_CUT_LLM_API_KEY")
        blocking_requirements.append("VIDEO_CUT_LLM_API_KEY is required for the real pipeline")
    if not whisper_command_present:
        missing_env_vars.append("VIDEO_CUT_WHISPER_COMMAND")
        blocking_requirements.append("VIDEO_CUT_WHISPER_COMMAND is required for ASR")
    elif not whisper_available:
        missing_env_vars.append("VIDEO_CUT_WHISPER_COMMAND:{output_file}")
        blocking_requirements.append("VIDEO_CUT_WHISPER_COMMAND must be executable and include {output_file}")
    if not ffmpeg_available:
        missing_env_vars.append("ffmpeg")
        blocking_requirements.append("ffmpeg is required for video composition")
    if not ffprobe_available:
        warnings.append("ffprobe is not available; uploaded material metadata may be less accurate")

    payload = {
        "mode": settings.mode,
        "ffmpeg_available": ffmpeg_available,
        "ffprobe_available": ffprobe_available,
        "llm_configured": settings.llm_configured,
        "llm_endpoint_configured": bool(settings.llm_endpoint),
        "whisper_configured": whisper_available,
        "max_concurrent_jobs": settings.max_concurrent_jobs,
        "recover_jobs": settings.recover_jobs,
        "task_ready": len(blocking_requirements) == 0,
        "blocking_requirements": blocking_requirements,
        "missing_env_vars": missing_env_vars,
        "warnings": warnings,
    }
    if extra:
        payload.update(extra)
    return payload


def run_job_pipeline(db: Session, job: Job, is_cancelled: StageGuard) -> list[OutputVideo]:
    from .stages import analysis, asr, compose, package, probe, review

    settings = get_pipeline_settings()
    ctx = PipelineContext(db=db, job=job, settings=settings, is_cancelled=is_cancelled)
    outputs: list[OutputVideo] = []
    explanation: Dict[str, Any] = {}

    for stage, progress, label, detail in PIPELINE_STAGES:
        _raise_if_cancelled(is_cancelled)
        job.stage = stage
        job.progress = progress
        db.commit()
        add_log(db, job, f"===== {label} =====\n")
        add_log(db, job, f"[Pipeline] {detail}...\n")

        if stage == "probe":
            probe._probe_stage(ctx)
        elif stage == "asr":
            asr._asr_stage(ctx)
        elif stage == "analysis":
            explanation = analysis._analysis_stage(ctx)
        elif stage == "review":
            review._review_stage(ctx, explanation)
        elif stage == "compose":
            outputs = compose._compose_stage(ctx, explanation)
        elif stage == "package":
            package._package_stage(ctx, outputs)

    return outputs


def _raise_if_cancelled(is_cancelled: StageGuard) -> None:
    if is_cancelled():
        raise PipelineCancelled()
