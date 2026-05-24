from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from .models import AsrTranscript, Job, JobLog, Material, OutputVideo, Workspace
from .settings import ffprobe_path
from .utils import json_dumps, json_loads, utcnow


def touch_workspace(db: Session, workspace_id: str) -> None:
    workspace = db.get(Workspace, workspace_id)
    if workspace:
        workspace.updated_at = utcnow()


def job_duration_seconds(job: Job) -> Optional[float]:
    if not job.started_at:
        return None
    end = job.completed_at or utcnow()
    return round(max(0.0, (end - job.started_at).total_seconds()), 2)


def ordered_materials(db: Session, workspace_id: str) -> List[Material]:
    return (
        db.query(Material)
        .filter(Material.workspace_id == workspace_id)
        .order_by(Material.order_index.asc(), Material.created_at.asc())
        .all()
    )


def latest_material_asr(db: Session, material_id: str) -> Optional[AsrTranscript]:
    return (
        db.query(AsrTranscript)
        .filter(AsrTranscript.material_id == material_id)
        .order_by(AsrTranscript.updated_at.desc(), AsrTranscript.created_at.desc())
        .first()
    )


def job_rule_summary(job: Job) -> str:
    snapshot = json_loads(job.input_snapshot_json)
    config = snapshot.get("config", {})
    text = config.get("clipRule") or config.get("contentType") or "未填写剪辑规则"
    return str(text)


def job_whisper_model(job: Job) -> str:
    snapshot = json_loads(job.input_snapshot_json)
    config = snapshot.get("config", {})
    return str(config.get("whisperModel") or "base")


def save_job_explainability(db: Session, job: Job, explainability: Dict[str, Any]) -> Dict[str, Any]:
    snapshot = json_loads(job.input_snapshot_json)
    snapshot["explainability"] = explainability
    job.input_snapshot_json = json_dumps(snapshot)
    db.commit()
    db.refresh(job)
    return explainability


def save_output_feedback(
    db: Session,
    job: Job,
    output_id: str,
    status: str,
    reason: str,
) -> Job:
    feedback_labels = {"usable", "needs_edit", "rejected"}
    if status not in feedback_labels:
        raise ValueError("unsupported feedback status")
    if not any(output.id == output_id for output in job.outputs):
        raise ValueError("output not found")

    snapshot = json_loads(job.input_snapshot_json)
    feedback = snapshot.get("feedback")
    if not isinstance(feedback, dict):
        feedback = {}
    feedback[output_id] = {
        "status": status,
        "reason": reason.strip(),
        "updated_at": utcnow().isoformat() + "Z",
    }
    snapshot["feedback"] = feedback
    job.input_snapshot_json = json_dumps(snapshot)
    db.commit()
    db.refresh(job)
    return job


def add_log(db: Session, job: Job, line: str) -> None:
    max_offset = (
        db.query(func.max(JobLog.offset))
        .filter(JobLog.job_id == job.id)
        .scalar()
    )
    next_offset = int(max_offset or 0) + 1
    db.add(JobLog(job_id=job.id, offset=next_offset, line=line))
    db.commit()


def add_many_logs(db: Session, job: Job, lines: Iterable[str]) -> None:
    for line in lines:
        add_log(db, job, line)


def first_mp4_material(db: Session, workspace_id: str) -> Optional[Material]:
    for material in ordered_materials(db, workspace_id):
        if Path(material.filename).suffix.lower() == ".mp4" and Path(material.filepath).exists():
            return material
    return None


def probe_video_with_ffprobe(path: Path) -> Dict[str, Any]:
    ffprobe = ffprobe_path()
    if not ffprobe:
        return {"probe_status": "unknown", "audio_status": "unknown"}
    command = [
        ffprobe,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        str(path),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=True,
        )
        payload = json.loads(result.stdout)
    except Exception:
        return {"probe_status": "unreadable", "audio_status": "unknown"}
    streams = payload.get("streams", [])
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    duration = video.get("duration") or payload.get("format", {}).get("duration")
    return {
        "duration": float(duration) if duration else None,
        "width": int(video["width"]) if video.get("width") else None,
        "height": int(video["height"]) if video.get("height") else None,
        "audio_status": "present" if audio else "missing",
        "probe_status": "ffprobe",
    }


def storage_summary(db: Session) -> Dict[str, Any]:
    storage_bytes = 0
    missing_files = 0
    materials = db.query(Material).all()
    outputs = db.query(OutputVideo).all()
    for item in [*materials, *outputs]:
        path = Path(item.filepath)
        if path.exists():
            storage_bytes += path.stat().st_size
        else:
            missing_files += 1
    return {
        "storage_bytes": storage_bytes,
        "material_count": len(materials),
        "output_count": len(outputs),
        "missing_files": missing_files,
        "cleanup_available": missing_files > 0,
    }
