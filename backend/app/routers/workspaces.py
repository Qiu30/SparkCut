from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..database import get_db
from ..db_helpers import (
    job_duration_seconds,
    job_rule_summary,
    job_whisper_model,
    ordered_materials,
    probe_video_with_ffprobe,
    touch_workspace,
)
from ..models import Job, Material, Workspace
from ..schemas import MaterialOrderUpdate, MaterialOut, WorkspaceCreate, WorkspaceDetail, WorkspaceSummary
from ..serialization import serialize_material, workspace_summary
from ..storage import (
    MAX_VIDEO_BYTES,
    MAX_WORKSPACE_MATERIALS,
    assert_video_extension,
    unique_stored_filename,
    uploads_dir,
)
from ..utils import new_id


router = APIRouter(prefix="/api", tags=["workspaces"])


@router.get("/workspaces", response_model=list[WorkspaceSummary])
def list_workspaces(db: Session = Depends(get_db)):
    workspaces = db.query(Workspace).order_by(Workspace.updated_at.desc()).all()
    return [workspace_summary(db, workspace) for workspace in workspaces]


@router.post("/workspaces", response_model=WorkspaceSummary)
def create_workspace(payload: WorkspaceCreate, db: Session = Depends(get_db)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="workspace name is required")
    workspace = Workspace(id=new_id(), name=name)
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    return workspace_summary(db, workspace)


@router.get("/workspaces/{workspace_id}", response_model=WorkspaceDetail)
def get_workspace(workspace_id: str, db: Session = Depends(get_db)):
    workspace = db.get(Workspace, workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="workspace not found")
    materials = [serialize_material(item, db) for item in ordered_materials(db, workspace_id)]
    jobs = (
        db.query(Job)
        .filter(Job.workspace_id == workspace_id)
        .order_by(Job.created_at.desc())
        .all()
    )
    return {
        "id": workspace.id,
        "name": workspace.name,
        "created_at": workspace.created_at,
        "updated_at": workspace.updated_at,
        "materials": materials,
        "jobs": [
            {
                "id": job.id,
                "workspace_id": job.workspace_id,
                "status": job.status,
                "stage": job.stage,
                "progress": job.progress,
                "rule_summary": job_rule_summary(job),
                "whisper_model": job_whisper_model(job),
                "output_count": len(job.outputs),
                "created_at": job.created_at,
                "started_at": job.started_at,
                "completed_at": job.completed_at,
                "duration_seconds": job_duration_seconds(job),
            }
            for job in jobs
        ],
    }


@router.post("/workspaces/{workspace_id}/videos", response_model=MaterialOut)
def upload_video(
    workspace_id: str,
    file: UploadFile = File(...),
    duration: Optional[float] = Form(None),
    width: Optional[int] = Form(None),
    height: Optional[int] = Form(None),
    probe_status: str = Form("unknown"),
    audio_status: str = Form("unknown"),
    db: Session = Depends(get_db),
):
    workspace = db.get(Workspace, workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="workspace not found")
    try:
        assert_video_extension(file.filename or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if len(ordered_materials(db, workspace_id)) >= MAX_WORKSPACE_MATERIALS:
        raise HTTPException(status_code=400, detail="workspace material limit reached")

    stored_filename = unique_stored_filename(file.filename or "video.mp4")
    target = uploads_dir(workspace_id) / stored_filename
    with target.open("wb") as out:
        while chunk := file.file.read(1024 * 1024):
            out.write(chunk)

    if target.stat().st_size > MAX_VIDEO_BYTES:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="video file is too large")

    if not duration and not width and not height:
        probed = probe_video_with_ffprobe(target)
        duration = probed.get("duration")
        width = probed.get("width")
        height = probed.get("height")
        probe_status = probed.get("probe_status", probe_status)
        audio_status = probed.get("audio_status", audio_status)

    max_order = max([material.order_index for material in ordered_materials(db, workspace_id)] or [-1])
    material = Material(
        id=new_id(),
        workspace_id=workspace_id,
        filename=file.filename or stored_filename,
        stored_filename=stored_filename,
        filepath=str(target),
        size_bytes=target.stat().st_size,
        order_index=max_order + 1,
        duration=duration,
        width=width,
        height=height,
        audio_status=audio_status,
        probe_status=probe_status,
    )
    db.add(material)
    touch_workspace(db, workspace_id)
    db.commit()
    db.refresh(material)
    return serialize_material(material, db)


@router.delete("/workspaces/{workspace_id}/videos/{video_id}")
def delete_video(workspace_id: str, video_id: str, db: Session = Depends(get_db)):
    material = db.get(Material, video_id)
    if not material or material.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="video not found")
    path = Path(material.filepath)
    if path.exists():
        path.unlink()
    db.delete(material)
    touch_workspace(db, workspace_id)
    db.commit()
    return {"ok": True}


@router.patch("/workspaces/{workspace_id}/videos/order", response_model=list[MaterialOut])
def reorder_videos(
    workspace_id: str,
    payload: MaterialOrderUpdate,
    db: Session = Depends(get_db),
):
    materials = {material.id: material for material in ordered_materials(db, workspace_id)}
    if set(payload.material_ids) != set(materials.keys()):
        raise HTTPException(status_code=400, detail="material_ids must match workspace videos")
    for index, material_id in enumerate(payload.material_ids):
        materials[material_id].order_index = index
    touch_workspace(db, workspace_id)
    db.commit()
    return [serialize_material(item, db) for item in ordered_materials(db, workspace_id)]
