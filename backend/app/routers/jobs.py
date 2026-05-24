from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..db_helpers import add_log, ordered_materials, save_output_feedback
from ..models import Job, JobLog, OutputVideo, Workspace
from ..schemas import DuplicateOut, FeedbackCreate, JobCreate, JobOut, LogsOut, RefineRequest
from ..serialization import create_input_snapshot, serialize_job
from ..storage import MAX_JOB_MATERIALS
from ..utils import json_dumps, json_loads, new_id, utcnow
from ..worker import start_job


router = APIRouter(prefix="/api", tags=["jobs"])


def create_job_from_config(
    db: Session,
    workspace: Workspace,
    config: dict,
    source_job_id: Optional[str] = None,
) -> Job:
    snapshot = create_input_snapshot(db, workspace, config)
    job = Job(
        id=new_id(),
        workspace_id=workspace.id,
        status="queued",
        stage="queued",
        progress=0,
        input_snapshot_json=json_dumps(snapshot),
        source_job_id=source_job_id,
    )
    db.add(job)
    workspace.updated_at = utcnow()
    db.commit()
    db.refresh(job)
    add_log(db, job, "[系统] 任务已创建，等待执行\n")
    start_job(job.id)
    return job


@router.post("/workspaces/{workspace_id}/jobs", response_model=JobOut)
def create_job(workspace_id: str, payload: JobCreate, db: Session = Depends(get_db)):
    workspace = db.get(Workspace, workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="workspace not found")
    materials = ordered_materials(db, workspace_id)
    if not materials:
        raise HTTPException(status_code=400, detail="at least one video is required")
    if len(materials) > MAX_JOB_MATERIALS:
        raise HTTPException(status_code=400, detail="too many videos for one job")
    job = create_job_from_config(db, workspace, payload.config)
    return serialize_job(job)


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return serialize_job(job)


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: str, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    if job.status in {"done", "error", "cancelled"}:
        return serialize_job(job)
    job.status = "cancelled"
    job.stage = "cancelled"
    job.completed_at = utcnow()
    db.commit()
    add_log(db, job, "[系统] 用户取消任务\n")
    db.refresh(job)
    return serialize_job(job)


@router.post("/jobs/{job_id}/retry", response_model=JobOut)
def retry_job(job_id: str, db: Session = Depends(get_db)):
    old_job = db.get(Job, job_id)
    if not old_job:
        raise HTTPException(status_code=404, detail="job not found")
    if old_job.status in {"queued", "running"}:
        raise HTTPException(status_code=400, detail="running jobs cannot be retried")
    workspace = db.get(Workspace, old_job.workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="workspace not found")
    snapshot = json_loads(old_job.input_snapshot_json)
    job = create_job_from_config(db, workspace, snapshot.get("config", {}), source_job_id=old_job.id)
    return serialize_job(job)


@router.post("/jobs/{job_id}/duplicate", response_model=DuplicateOut)
def duplicate_job(job_id: str, db: Session = Depends(get_db)):
    old_job = db.get(Job, job_id)
    if not old_job:
        raise HTTPException(status_code=404, detail="job not found")
    workspace = db.get(Workspace, old_job.workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="workspace not found")
    snapshot = json_loads(old_job.input_snapshot_json)
    job = create_job_from_config(db, workspace, snapshot.get("config", {}), source_job_id=old_job.id)
    return {"job": serialize_job(job)}


@router.get("/jobs/{job_id}/logs", response_model=LogsOut)
def get_logs(job_id: str, offset: int = 0, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    logs = (
        db.query(JobLog)
        .filter(JobLog.job_id == job_id, JobLog.offset > offset)
        .order_by(JobLog.offset.asc())
        .all()
    )
    next_offset = logs[-1].offset if logs else offset
    return {
        "lines": [log.line for log in logs],
        "next_offset": next_offset,
        "status": job.status,
        "stage": job.stage,
        "progress": job.progress,
    }


@router.get("/jobs/{job_id}/outputs/{output_id}")
def get_output(job_id: str, output_id: str, download: bool = False, db: Session = Depends(get_db)):
    output = db.get(OutputVideo, output_id)
    if not output or output.job_id != job_id:
        raise HTTPException(status_code=404, detail="output not found")
    path = Path(output.filepath)
    if not path.exists():
        raise HTTPException(status_code=404, detail="output file not found")
    return FileResponse(
        path,
        media_type="video/mp4",
        filename=output.filename,
        content_disposition_type="attachment" if download else "inline",
    )


@router.post("/jobs/{job_id}/outputs/{output_id}/feedback", response_model=JobOut)
def submit_output_feedback(
    job_id: str,
    output_id: str,
    payload: FeedbackCreate,
    db: Session = Depends(get_db),
):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    try:
        updated = save_output_feedback(db, job, output_id, payload.status, payload.reason)
    except ValueError as exc:
        raise HTTPException(status_code=404 if "not found" in str(exc) else 400, detail=str(exc)) from exc
    add_log(db, updated, f"[反馈] 输出结果标记为 {payload.status}：{payload.reason or '无补充说明'}\n")
    db.refresh(updated)
    return serialize_job(updated)


@router.post("/jobs/{job_id}/outputs/{output_id}/refine", response_model=JobOut)
def refine_output(
    job_id: str,
    output_id: str,
    payload: RefineRequest,
    db: Session = Depends(get_db),
):
    old_job = db.get(Job, job_id)
    if not old_job:
        raise HTTPException(status_code=404, detail="job not found")
    if not any(output.id == output_id for output in old_job.outputs):
        raise HTTPException(status_code=404, detail="output not found")
    workspace = db.get(Workspace, old_job.workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="workspace not found")

    snapshot = json_loads(old_job.input_snapshot_json)
    new_snapshot = create_input_snapshot(db, workspace, snapshot.get("config", {}))
    new_snapshot["refine_request"] = {
        "action": payload.action,
        "feedback": payload.feedback,
        "original_explainability": snapshot.get("explainability", {}),
    }

    new_job = Job(
        id=new_id(),
        workspace_id=workspace.id,
        status="queued",
        stage="queued",
        progress=0,
        input_snapshot_json=json_dumps(new_snapshot),
        source_job_id=old_job.id,
    )
    db.add(new_job)
    workspace.updated_at = utcnow()
    db.commit()
    db.refresh(new_job)
    add_log(db, new_job, f"[系统] 基于方案优化创建新任务（{payload.action}）\n")
    add_log(db, new_job, f"[优化反馈] {payload.feedback}\n")
    start_job(new_job.id)
    return serialize_job(new_job)
