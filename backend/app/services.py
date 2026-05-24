from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from .database import STORAGE_DIR
from .models import AsrTranscript, Job, JobLog, Material, OutputVideo, Template, Workspace
from .settings import ffprobe_path


ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".webm"}
MAX_VIDEO_BYTES = int(os.environ.get("VIDEO_CUT_MAX_VIDEO_BYTES", str(2 * 1024 * 1024 * 1024)))
MAX_WORKSPACE_MATERIALS = int(os.environ.get("VIDEO_CUT_MAX_WORKSPACE_MATERIALS", "100"))
MAX_JOB_MATERIALS = int(os.environ.get("VIDEO_CUT_MAX_JOB_MATERIALS", "100"))


def new_id(length: int = 12) -> str:
    return uuid.uuid4().hex[:length]


def utcnow() -> datetime:
    return datetime.utcnow()


def json_loads(value: str) -> Dict[str, Any]:
    return json.loads(value) if value else {}


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat() + "Z"
    return str(value)


def json_dumps(value: Dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, default=_json_default)


def workspace_dir(workspace_id: str) -> Path:
    path = STORAGE_DIR / "workspaces" / workspace_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def uploads_dir(workspace_id: str) -> Path:
    path = workspace_dir(workspace_id) / "uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def outputs_dir(workspace_id: str, job_id: str) -> Path:
    path = workspace_dir(workspace_id) / "outputs" / job_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def assert_video_extension(filename: str) -> None:
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_VIDEO_EXTENSIONS:
        raise ValueError("unsupported video format")


def unique_stored_filename(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    safe_stem = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in Path(filename).stem)
    safe_stem = safe_stem[:80] or "video"
    return f"{safe_stem}_{new_id(8)}{ext}"


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


def job_rule_summary(job: Job) -> str:
    snapshot = json_loads(job.input_snapshot_json)
    config = snapshot.get("config", {})
    text = config.get("clipRule") or config.get("contentType") or "未填写剪辑规则"
    return str(text)


def job_whisper_model(job: Job) -> str:
    snapshot = json_loads(job.input_snapshot_json)
    config = snapshot.get("config", {})
    return str(config.get("whisperModel") or "base")


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


def _as_float(value: Any, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def build_mock_explainability(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    materials = snapshot.get("materials", [])
    if not isinstance(materials, list):
        materials = []
    config = snapshot.get("config", {})
    if not isinstance(config, dict):
        config = {}

    selected = materials[:3]
    timeline = []
    cursor = 0.0
    for index, material in enumerate(selected):
        if not isinstance(material, dict):
            continue
        source_duration = _as_float(material.get("duration"), 18.0 + index * 4)
        clip_duration = min(max(source_duration * 0.35, 5.0), 12.0)
        start = min(cursor, max(source_duration - clip_duration, 0.0))
        end = min(start + clip_duration, source_duration)
        timeline.append(
            {
                "source": material.get("filename") or f"素材 {index + 1}",
                "start": round(start, 1),
                "end": round(end, 1),
                "duration": round(max(end - start, 0.0), 1),
                "score": round(9.2 - index * 0.5, 1),
                "reason": [
                    "开头信息密度高，适合作为前三秒钩子。",
                    "情绪变化明确，能承接主线并制造节奏抬升。",
                    "画面完整度较高，适合放在结尾保留悬念。",
                ][min(index, 2)],
                "evidence_source": "metadata",
                "evidence_text": "",
            }
        )
        cursor += 3.0

    excluded = []
    for index, material in enumerate(materials[len(selected):], start=1):
        if not isinstance(material, dict):
            continue
        excluded.append(
            {
                "source": material.get("filename") or f"未命名素材 {index}",
                "reason": "v0.3 mock 评分较低：节奏重复或与当前主线关联弱。",
            }
        )

    total_duration = round(sum(item["duration"] for item in timeline), 1)
    review_rule = str(config.get("reviewRule") or "").strip()
    review_items = [
        {
            "rule": review_rule or "通用合规审查",
            "time": "全片",
            "result": "未命中明确风险",
            "action": "允许输出",
        }
    ]
    if config.get("keepSuspense"):
        review_items.append(
            {
                "rule": "悬念保留",
                "time": "结尾",
                "result": "结尾未泄露完整反转",
                "action": "保留截断点",
            }
        )

    output_count = int(config.get("outputCount") or 1)
    comparison = []
    for index in range(max(1, min(output_count, 3))):
        comparison.append(
            {
                "name": "演示精剪版" if index == 0 else f"备选方案 {index + 1}",
                "duration_seconds": total_duration + index * 4,
                "clip_count": len(timeline),
                "strength": ["钩子最强", "剧情更完整", "节奏更稳"][min(index, 2)],
                "tradeoff": ["信息压缩较强", "高潮出现稍晚", "反转力度较弱"][min(index, 2)],
            }
        )

    title = str(config.get("dramaName") or "演示精剪版")
    return {
        "summary": {
            "title": title,
            "storyline": f"围绕「{config.get('contentType') or '高光'}」目标，优先选择冲突清晰、信息密度高的片段。",
            "pacing": str(config.get("pace") or "剧情向"),
            "clip_count": len(timeline),
            "estimated_duration": total_duration,
            "target_platform": str(config.get("targetPlatform") or "通用"),
            "aspect_ratio": str(config.get("aspectRatio") or "9:16"),
        },
        "timeline": timeline,
        "excluded": excluded,
        "review_report": {
            "status": "passed",
            "risk_level": "低",
            "model": str(config.get("reviewModel") or "GLM-5.1"),
            "items": review_items,
        },
        "comparison": comparison,
    }


def attach_mock_explainability(db: Session, job: Job) -> Dict[str, Any]:
    snapshot = json_loads(job.input_snapshot_json)
    explainability = build_mock_explainability(snapshot)
    return save_job_explainability(db, job, explainability)


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


def create_mock_output(db: Session, job: Job, name: str = "演示精剪版", suffix: str = "") -> Optional[OutputVideo]:
    source = first_mp4_material(db, job.workspace_id)
    if not source:
        return None
    stored_name = f"videocut_{job.id}{suffix}_demo_cut.mp4"
    target = outputs_dir(job.workspace_id, job.id) / stored_name
    shutil.copyfile(source.filepath, target)
    output = OutputVideo(
        id=new_id(),
        job_id=job.id,
        name=name,
        filename=stored_name,
        filepath=str(target),
        size_bytes=target.stat().st_size,
        duration=source.duration,
        review_status="passed",
    )
    db.add(output)
    db.commit()
    db.refresh(output)
    return output


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


def template_config(template: Template) -> Dict[str, Any]:
    return json_loads(template.config_json)


def template_meta(template: Template) -> Dict[str, Any]:
    config = template_config(template)
    meta = config.get("_meta")
    return meta if isinstance(meta, dict) else {}


def serialize_template(template: Template) -> Dict[str, Any]:
    config = template_config(template)
    meta = template_meta(template)
    public_config = dict(config)
    public_config.pop("_meta", None)
    return {
        "id": template.id,
        "name": template.name,
        "type": template.type,
        "config": public_config,
        "is_default": bool(meta.get("isDefault")),
        "last_used_at": meta.get("lastUsedAt"),
        "created_at": template.created_at,
        "updated_at": template.updated_at,
    }


def update_template_meta(db: Session, template: Template, **updates: Any) -> Template:
    config = template_config(template)
    meta = config.get("_meta")
    if not isinstance(meta, dict):
        meta = {}
    meta.update(updates)
    config["_meta"] = meta
    template.config_json = json_dumps(config)
    template.updated_at = utcnow()
    db.commit()
    db.refresh(template)
    return template


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


def seed_templates(db: Session) -> None:
    if db.query(Template).first():
        return
    now = utcnow()
    defaults = [
        (
            "clip_highlight_standard",
            "标准高光剪辑",
            "clip",
            {
                "contentType": "高光",
                "durationRange": "2-6 分钟",
                "outputCount": 2,
                "pace": "剧情向",
                "targetPlatform": "通用",
                "aspectRatio": "9:16",
                "keepSuspense": False,
                "clipRule": "选取高光时段，成片视频2-6分钟，需要产出2套方案（精剪版/加长版）",
                "clipModel": "GLM-5.1",
                "whisperModel": "base",
            },
        ),
        (
            "clip_reversal_30s",
            "30秒强反转",
            "clip",
            {
                "contentType": "高光",
                "durationRange": "30 秒",
                "outputCount": 1,
                "pace": "强反转",
                "targetPlatform": "抖音",
                "aspectRatio": "9:16",
                "keepSuspense": True,
                "clipRule": "前5秒必须有冲突或反转，成片30秒，结尾保留悬念。",
                "clipModel": "GLM-5.1",
                "whisperModel": "base",
            },
        ),
        (
            "clip_suspense",
            "悬疑剧情剪辑",
            "clip",
            {
                "contentType": "悬疑",
                "durationRange": "3-5 分钟",
                "outputCount": 1,
                "pace": "剧情向",
                "targetPlatform": "通用",
                "aspectRatio": "9:16",
                "keepSuspense": True,
                "clipRule": "选取悬疑高能片段，突出剧情冲突，结尾保留悬念截断。",
                "clipModel": "GLM-5.1",
                "whisperModel": "base",
            },
        ),
        (
            "review_no_money",
            "禁止人民币",
            "review",
            {
                "reviewRule": "画面不能出现人民币、现金交易场景、银行界面。",
                "reviewModel": "GLM-5.1",
            },
        ),
        (
            "review_no_watermark",
            "禁止广告水印",
            "review",
            {
                "reviewRule": "画面不能出现广告、水印、二维码、第三方平台标识。",
                "reviewModel": "GLM-5.1",
            },
        ),
        (
            "review_clean",
            "通用合规审查",
            "review",
            {
                "reviewRule": "画面不能出现违规内容，包括人民币、暴力、色情、敏感信息、广告等。",
                "reviewModel": "GLM-5.1",
            },
        ),
    ]
    for template_id, name, template_type, config in defaults:
        db.add(
            Template(
                id=template_id,
                name=name,
                type=template_type,
                config_json=json_dumps(config),
                created_at=now,
                updated_at=now,
            )
        )
    db.commit()


def job_step_seconds() -> float:
    try:
        return float(os.environ.get("VIDEO_CUT_JOB_STEP_SECONDS", "0.8"))
    except ValueError:
        return 0.8
