from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from .db_helpers import job_duration_seconds, latest_material_asr, ordered_materials
from .models import Job, Material, OutputVideo, Workspace
from .utils import json_loads, utcnow


def serialize_material(material: Material, db: Optional[Session] = None) -> Dict[str, Any]:
    transcript = latest_material_asr(db, material.id) if db else None
    return {
        "id": material.id,
        "workspace_id": material.workspace_id,
        "filename": material.filename,
        "size_bytes": material.size_bytes,
        "order_index": material.order_index,
        "duration": material.duration,
        "width": material.width,
        "height": material.height,
        "audio_status": material.audio_status,
        "probe_status": material.probe_status,
        "asr_status": transcript.status if transcript else None,
        "asr_updated_at": transcript.updated_at if transcript else None,
        "asr_error_message": transcript.error_message if transcript else None,
        "created_at": material.created_at,
    }


def serialize_output(output: OutputVideo, feedback: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    feedback = feedback or {}
    return {
        "id": output.id,
        "job_id": output.job_id,
        "name": output.name,
        "filename": output.filename,
        "size_bytes": output.size_bytes,
        "duration": output.duration,
        "review_status": output.review_status,
        "feedback_status": feedback.get("status"),
        "feedback_reason": feedback.get("reason"),
        "feedback_updated_at": feedback.get("updated_at"),
        "created_at": output.created_at,
    }


def serialize_job(job: Job) -> Dict[str, Any]:
    snapshot = json_loads(job.input_snapshot_json)
    feedback = snapshot.get("feedback", {})
    if not isinstance(feedback, dict):
        feedback = {}
    return {
        "id": job.id,
        "workspace_id": job.workspace_id,
        "status": job.status,
        "stage": job.stage,
        "progress": job.progress,
        "input_snapshot": snapshot,
        "explainability": snapshot.get("explainability", {}),
        "error_message": job.error_message,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "duration_seconds": job_duration_seconds(job),
        "source_job_id": job.source_job_id,
        "outputs": [serialize_output(output, feedback.get(output.id)) for output in job.outputs],
    }


def workspace_summary(db: Session, workspace: Workspace) -> Dict[str, Any]:
    material_count = db.query(func.count(Material.id)).filter(Material.workspace_id == workspace.id).scalar()
    job_count = db.query(func.count(Job.id)).filter(Job.workspace_id == workspace.id).scalar()
    latest_job = (
        db.query(Job)
        .filter(Job.workspace_id == workspace.id)
        .order_by(Job.created_at.desc())
        .first()
    )
    return {
        "id": workspace.id,
        "name": workspace.name,
        "created_at": workspace.created_at,
        "updated_at": workspace.updated_at,
        "material_count": int(material_count or 0),
        "job_count": int(job_count or 0),
        "latest_job_status": latest_job.status if latest_job else None,
    }


def create_input_snapshot(db: Session, workspace: Workspace, config: Dict[str, Any]) -> Dict[str, Any]:
    materials = ordered_materials(db, workspace.id)
    return {
        "workspace": {
            "id": workspace.id,
            "name": workspace.name,
        },
        "materials": [serialize_material(material, db) for material in materials],
        "config": config,
        "created_at": utcnow().isoformat() + "Z",
    }
