from __future__ import annotations

from typing import Any, Dict

from sqlalchemy.orm import Session

from .. import ffmpeg as ffmpeg_tools
from ..engine import PipelineRuntimeError
from ...db_helpers import first_mp4_material
from ...models import Job, OutputVideo
from ...settings import ffmpeg_path
from ...utils import json_loads


def _compose_stage(ctx, explanation: Dict[str, Any]) -> list[OutputVideo]:
    db, job, settings = ctx.db, ctx.job, ctx.settings
    ffmpeg = ffmpeg_path()
    if not ffmpeg:
        raise PipelineRuntimeError("ffmpeg is required")

    return _compose_real_outputs(db, job, settings, ffmpeg, explanation)


def _compose_real_outputs(
    db: Session,
    job: Job,
    settings,
    ffmpeg: str,
    explanation: Dict[str, Any],
) -> list[OutputVideo]:
    snapshot = json_loads(job.input_snapshot_json)
    config = snapshot.get("config", {}) if isinstance(snapshot.get("config"), dict) else {}
    summary = explanation.get("summary", {}) if isinstance(explanation, dict) else {}
    if not isinstance(summary, dict):
        summary = {}
    fallback_source = first_mp4_material(db, job.workspace_id)
    fallback_duration = float(fallback_source.duration or 30) if fallback_source else 30.0
    target_duration = float(summary.get("estimated_duration") or fallback_duration)

    outputs: list[OutputVideo] = []
    timelines = explanation.get("timelines") if isinstance(explanation, dict) else None
    if not isinstance(timelines, list) or not timelines:
        timelines = [{"name": summary.get("title", "Real cut"), "timeline": explanation.get("timeline", [])}]

    for index, plan in enumerate(timelines):
        if not isinstance(plan, dict):
            continue
        plan_name = str(plan.get("name") or f"Plan {index + 1}")
        plan_tl = plan.get("timeline", [])
        clips = ffmpeg_tools._timeline_clips(db, job, {"timeline": plan_tl}, target_duration)
        suffix = f"_plan{index + 1}" if len(timelines) > 1 else ""
        output = ffmpeg_tools._render_ffmpeg_output(
            db, job, ffmpeg, clips,
            plan_name=plan_name, plan_suffix=suffix,
            target_duration=target_duration,
        )
        outputs.append(output)
    if not outputs:
        raise PipelineRuntimeError("no ffmpeg outputs were generated")
    return outputs

