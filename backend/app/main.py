from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .database import get_db, init_db
from .llm_models import fetch_llm_models
from .models import Job, JobLog, Material, OutputVideo, Template, Workspace
from .schemas import (
    DuplicateOut,
    FeedbackCreate,
    JobCreate,
    JobOut,
    LlmModelsOut,
    LogsOut,
    MaterialOrderUpdate,
    MaterialOut,
    PipelineStatus,
    RefineRequest,
    RuntimeSettingsOut,
    RuntimeSettingsUpdate,
    StorageSummary,
    TemplateCreate,
    TemplateOut,
    WorkspaceCreate,
    WorkspaceDetail,
    WorkspaceSummary,
)
from .services import (
    add_log,
    assert_video_extension,
    create_input_snapshot,
    json_dumps,
    json_loads,
    job_duration_seconds,
    job_rule_summary,
    job_whisper_model,
    MAX_JOB_MATERIALS,
    MAX_VIDEO_BYTES,
    MAX_WORKSPACE_MATERIALS,
    new_id,
    ordered_materials,
    probe_video_with_ffprobe,
    seed_templates,
    serialize_job,
    serialize_material,
    serialize_template,
    save_output_feedback,
    storage_summary,
    template_config,
    update_template_meta,
    touch_workspace,
    unique_stored_filename,
    uploads_dir,
    utcnow,
    workspace_summary,
)
from .pipeline import pipeline_status
from .settings import get_pipeline_settings, read_local_env_values, update_runtime_env
from .worker import recover_incomplete_jobs, runner_status, start_mock_job


app = FastAPI(title="SparkCut API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    for key, value in read_local_env_values().items():
        os.environ.setdefault(key, value)
    init_db()
    db = next(get_db())
    try:
        seed_templates(db)
        recover_incomplete_jobs(db)
    finally:
        db.close()


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/workspaces", response_model=list[WorkspaceSummary])
def list_workspaces(db: Session = Depends(get_db)):
    workspaces = db.query(Workspace).order_by(Workspace.updated_at.desc()).all()
    return [workspace_summary(db, workspace) for workspace in workspaces]


@app.post("/api/workspaces", response_model=WorkspaceSummary)
def create_workspace(payload: WorkspaceCreate, db: Session = Depends(get_db)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="workspace name is required")
    workspace = Workspace(id=new_id(), name=name)
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    return workspace_summary(db, workspace)


@app.get("/api/workspaces/{workspace_id}", response_model=WorkspaceDetail)
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


@app.post("/api/workspaces/{workspace_id}/videos", response_model=MaterialOut)
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


@app.delete("/api/workspaces/{workspace_id}/videos/{video_id}")
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


@app.patch("/api/workspaces/{workspace_id}/videos/order", response_model=list[MaterialOut])
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


@app.get("/api/templates", response_model=list[TemplateOut])
def list_templates(type: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(Template)
    if type:
        query = query.filter(Template.type == type)
    templates = query.order_by(Template.created_at.asc()).all()
    serialized = [serialize_template(template) for template in templates]
    return sorted(
        serialized,
        key=lambda item: (
            item["type"],
            not item["is_default"],
            item["last_used_at"] or "",
            item["created_at"],
        ),
    )


@app.post("/api/templates", response_model=TemplateOut)
def create_template(payload: TemplateCreate, db: Session = Depends(get_db)):
    template = Template(
        id=new_id(16),
        name=payload.name.strip(),
        type=payload.type,
        config_json=json_dumps(payload.config),
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return serialize_template(template)


@app.delete("/api/templates/{template_id}")
def delete_template(template_id: str, db: Session = Depends(get_db)):
    template = db.get(Template, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="template not found")
    db.delete(template)
    db.commit()
    return {"ok": True}


@app.post("/api/templates/{template_id}/use", response_model=TemplateOut)
def mark_template_used(template_id: str, db: Session = Depends(get_db)):
    template = db.get(Template, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="template not found")
    updated = update_template_meta(db, template, lastUsedAt=utcnow().isoformat() + "Z")
    return serialize_template(updated)


@app.post("/api/templates/{template_id}/duplicate", response_model=TemplateOut)
def duplicate_template(template_id: str, db: Session = Depends(get_db)):
    template = db.get(Template, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="template not found")
    config = template_config(template)
    config["_meta"] = {"sourceTemplateId": template.id}
    duplicate = Template(
        id=new_id(16),
        name=f"{template.name} 副本",
        type=template.type,
        config_json=json_dumps(config),
    )
    db.add(duplicate)
    db.commit()
    db.refresh(duplicate)
    return serialize_template(duplicate)


@app.post("/api/templates/{template_id}/default", response_model=TemplateOut)
def set_default_template(template_id: str, db: Session = Depends(get_db)):
    template = db.get(Template, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="template not found")
    for same_type in db.query(Template).filter(Template.type == template.type).all():
        update_template_meta(db, same_type, isDefault=(same_type.id == template.id))
    db.refresh(template)
    return serialize_template(template)


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
    start_mock_job(job.id)
    return job


@app.post("/api/workspaces/{workspace_id}/jobs", response_model=JobOut)
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


@app.get("/api/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return serialize_job(job)


@app.post("/api/jobs/{job_id}/cancel", response_model=JobOut)
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


@app.post("/api/jobs/{job_id}/retry", response_model=JobOut)
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


@app.post("/api/jobs/{job_id}/duplicate", response_model=DuplicateOut)
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


@app.get("/api/jobs/{job_id}/logs", response_model=LogsOut)
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


@app.get("/api/storage/summary", response_model=StorageSummary)
def get_storage_summary(db: Session = Depends(get_db)):
    return storage_summary(db)


@app.get("/api/pipeline/status", response_model=PipelineStatus)
def get_pipeline_status():
    return pipeline_status(runner_status())


@app.get("/api/llm/models", response_model=LlmModelsOut)
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
        "default_whisper_model": settings.default_whisper_model,
        "asr_clip_seconds": settings.asr_clip_seconds,
    }


@app.get("/api/settings/runtime", response_model=RuntimeSettingsOut)
def get_runtime_settings():
    return _runtime_settings_payload()


@app.put("/api/settings/runtime", response_model=RuntimeSettingsOut)
def update_runtime_settings(payload: RuntimeSettingsUpdate):
    updates = {}
    if payload.pipeline_mode is not None:
        mode = payload.pipeline_mode.strip().lower()
        if mode not in {"mock", "auto", "real"}:
            raise HTTPException(status_code=400, detail="invalid pipeline mode")
        updates["VIDEO_CUT_PIPELINE_MODE"] = mode
    if payload.llm_endpoint is not None:
        updates["VIDEO_CUT_LLM_ENDPOINT"] = payload.llm_endpoint.strip()
    if payload.llm_api_key is not None:
        updates["VIDEO_CUT_LLM_API_KEY"] = payload.llm_api_key.strip()
    if payload.llm_model is not None:
        updates["VIDEO_CUT_LLM_MODEL"] = payload.llm_model.strip()
    if payload.default_whisper_model is not None:
        updates["VIDEO_CUT_DEFAULT_WHISPER_MODEL"] = payload.default_whisper_model.strip()
    if payload.asr_clip_seconds is not None:
        updates["VIDEO_CUT_ASR_CLIP_SECONDS"] = max(0.0, payload.asr_clip_seconds)
    update_runtime_env(updates)
    return _runtime_settings_payload()


@app.get("/api/jobs/{job_id}/outputs/{output_id}")
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


@app.post("/api/jobs/{job_id}/outputs/{output_id}/feedback", response_model=JobOut)
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


@app.post("/api/jobs/{job_id}/outputs/{output_id}/refine", response_model=JobOut)
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
    start_mock_job(new_job.id)
    return serialize_job(new_job)
