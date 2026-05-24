from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from . import explainability
from .engine import PipelineRuntimeError
from .stages import asr
from ..db_helpers import add_log, first_mp4_material, ordered_materials
from ..models import AsrTranscript, Job, Material, OutputVideo
from ..settings import get_pipeline_settings
from ..storage import outputs_dir
from ..utils import json_loads, new_id


def _load_asr_segments(db: Session, material_id: str) -> list[Dict[str, Any]]:
    transcript = (
        db.query(AsrTranscript)
        .filter(AsrTranscript.material_id == material_id, AsrTranscript.status == "done")
        .order_by(AsrTranscript.updated_at.desc(), AsrTranscript.created_at.desc())
        .first()
    )
    return asr._transcript_segments(transcript) if transcript else []


def _align_clip_to_speech(
    clip: Dict[str, Any], segments: list[Dict[str, Any]], max_extend: float = 3.0,
) -> Dict[str, Any]:
    if not segments:
        return clip
    original_end = clip["end"]
    source_duration = float(clip["material"].duration or 0)

    best_end = original_end
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        seg_end = explainability._as_number(seg.get("end"), 0)
        if seg_end <= original_end:
            continue
        if seg_end - original_end <= max_extend:
            best_end = seg_end
            break

    if source_duration > 0:
        best_end = min(best_end, source_duration)

    if best_end > original_end:
        clip = dict(clip)
        clip["end"] = round(best_end, 1)
        clip["duration"] = round(best_end - clip["start"], 1)
    return clip


def _render_ffmpeg_output(
    db: Session,
    job: Job,
    ffmpeg: str,
    clips: list[Dict[str, Any]],
    plan_name: str = "真实混剪输出",
    plan_suffix: str = "",
    target_duration: float = 30.0,
) -> OutputVideo:
    fallback_source = first_mp4_material(db, job.workspace_id)
    if not fallback_source:
        raise PipelineRuntimeError("no MP4 material available for ffmpeg output")

    snapshot = json_loads(job.input_snapshot_json)
    config = snapshot.get("config", {}) if isinstance(snapshot.get("config"), dict) else {}
    if not clips:
        raise PipelineRuntimeError("no timeline clips available for ffmpeg output")
    stored_name = f"videocut_{job.id}{plan_suffix}_real_cut.mp4"
    target = outputs_dir(job.workspace_id, job.id) / stored_name
    filters = _video_filters(config)
    material_count = len({clip["material"].id for clip in clips})
    add_log(db, job, f"[Pipeline] 方案「{plan_name}」合成 {len(clips)} 个片段，涉及 {material_count} 个素材\n")

    with tempfile.TemporaryDirectory(prefix=f"videocut_{job.id}_") as tmp_dir:
        segment_paths: list[Path] = []
        asr_cache: Dict[str, list] = {}
        for index, clip in enumerate(clips, start=1):
            material = clip["material"]
            if material.id not in asr_cache:
                asr_cache[material.id] = _load_asr_segments(db, material.id)
            aligned = _align_clip_to_speech(clip, asr_cache[material.id])
            if aligned["end"] != clip["end"]:
                add_log(db, job, f"[Pipeline] 片段 {index} 结束时间 {clip['end']:.1f}s → {aligned['end']:.1f}s（对齐语句边界）\n")
                clips[index - 1] = aligned
            clip = aligned
            segment = Path(tmp_dir) / f"segment_{index:03d}.mp4"
            command = [
                ffmpeg,
                "-y",
                "-ss",
                str(max(0.0, clip["start"])),
                "-i",
                material.filepath,
                "-t",
                str(max(1.0, clip["duration"])),
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
            ]
            if filters:
                command.extend(["-vf", ",".join(filters)])
            command.extend([
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-c:a",
                "aac",
                "-ar",
                "44100",
                "-ac",
                "2",
                "-movflags",
                "+faststart",
                str(segment),
            ])
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=get_pipeline_settings().ffmpeg_timeout_seconds,
            )
            if result.returncode != 0:
                raise PipelineRuntimeError(result.stderr[-1200:] or "ffmpeg segment failed")
            segment_paths.append(segment)

        concat_file = Path(tmp_dir) / "concat.txt"
        concat_file.write_text(
            "".join(f"file '{segment.as_posix()}'\n" for segment in segment_paths),
            encoding="utf-8",
        )
        concat_command = [
            ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(target),
        ]
        result = subprocess.run(
            concat_command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=get_pipeline_settings().ffmpeg_timeout_seconds,
        )
        if result.returncode != 0:
            raise PipelineRuntimeError(result.stderr[-1200:] or "ffmpeg concat failed")

    output = OutputVideo(
        id=new_id(),
        job_id=job.id,
        name=plan_name,
        filename=stored_name,
        filepath=str(target),
        size_bytes=Path(target).stat().st_size,
        duration=round(sum(max(0.0, clip["duration"]) for clip in clips), 1),
        review_status="passed",
    )
    db.add(output)
    db.commit()
    db.refresh(output)
    return output


def _timeline_clips(db: Session, job: Job, explanation: Any, target_duration: float) -> list[Dict[str, Any]]:
    if not isinstance(explanation, dict):
        return []
    timeline = explanation.get("timeline")
    if not isinstance(timeline, list):
        return []
    materials = [
        material
        for material in ordered_materials(db, job.workspace_id)
        if Path(material.filename).suffix.lower() == ".mp4" and Path(material.filepath).exists()
    ]
    if not materials:
        return []

    clips: list[Dict[str, Any]] = []
    remaining = max(1.0, target_duration)
    for index, item in enumerate(timeline):
        if remaining <= 0:
            break
        if not isinstance(item, dict):
            continue
        material = _resolve_timeline_material(item, materials, index)
        if not material:
            continue
        source_duration = float(material.duration or 0)
        start = max(0.0, explainability._as_number(item.get("start"), explainability._as_number(item.get("start_time"), 0.0)))
        if source_duration > 0:
            start = min(start, max(0.0, source_duration - 1.0))
        end = explainability._as_number(item.get("end"), explainability._as_number(item.get("end_time"), start + explainability._as_number(item.get("duration"), 5.0)))
        duration = explainability._as_number(item.get("duration"), max(0.0, end - start))
        if duration <= 0:
            duration = max(0.0, end - start) or 5.0
        if source_duration > 0:
            duration = min(duration, max(1.0, source_duration - start))
        duration = min(max(1.0, duration), remaining)
        clips.append({"material": material, "start": round(start, 3), "end": round(start + duration, 3), "duration": round(duration, 3)})
        remaining -= duration
    return clips


def _resolve_timeline_material(item: Dict[str, Any], materials: list[Material], index: int) -> Optional[Material]:
    candidates = [
        item.get("material_id"),
        item.get("materialId"),
        item.get("source"),
        item.get("filename"),
        item.get("stored_filename"),
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        value = str(candidate)
        for material in materials:
            if value in {material.id, material.filename, material.stored_filename, Path(material.filepath).name}:
                return material
    if index < len(materials):
        return materials[index]
    return None


def _video_filters(config: Dict[str, Any]) -> list[str]:
    aspect_ratio = str(config.get("aspectRatio") or "保持原始")
    filters = []
    if aspect_ratio == "9:16":
        filters.append("scale=1080:1920:force_original_aspect_ratio=decrease")
        filters.append("pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black")
    elif aspect_ratio == "16:9":
        filters.append("scale=1920:1080:force_original_aspect_ratio=decrease")
        filters.append("pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black")
    elif aspect_ratio == "1:1":
        filters.append("scale=1080:1080:force_original_aspect_ratio=decrease")
        filters.append("pad=1080:1080:(ow-iw)/2:(oh-ih)/2:black")

    drama_name = str(config.get("dramaName") or "").strip()
    font_color = str(config.get("fontColor") or "#ffff00")
    if drama_name:
        filters.append(
            "drawtext="
            f"text='{_escape_drawtext(drama_name)}':"
            f"x=36:y=36:fontsize=42:fontcolor={font_color}:"
            "box=1:boxcolor=black@0.45:boxborderw=14"
        )
    if config.get("cornerEnabled"):
        filters.append(
            "drawtext="
            "text='SparkCut':x=w-tw-32:y=32:fontsize=28:"
            "fontcolor=white:box=1:boxcolor=black@0.35:boxborderw=10"
        )
    return filters


def _escape_drawtext(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace(",", "\\,")
        .replace("[", "\\[")
        .replace("]", "\\]")
    )

