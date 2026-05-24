from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from ..engine import PipelineRuntimeError
from ...db_helpers import add_log
from ...models import AsrTranscript, Job, Material
from ...storage import outputs_dir, workspace_dir
from ...utils import json_dumps, json_loads, new_id, utcnow


VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".webm"}


def _job_video_materials(db: Session, job: Job) -> list[Material]:
    snapshot = json_loads(job.input_snapshot_json)
    snapshot_materials = snapshot.get("materials", [])
    if not isinstance(snapshot_materials, list):
        snapshot_materials = []

    ordered: list[Material] = []
    seen: set[str] = set()
    for item in snapshot_materials:
        if not isinstance(item, dict):
            continue
        material_id = str(item.get("id") or "")
        if not material_id or material_id in seen:
            continue
        material = db.get(Material, material_id)
        if not material:
            continue
        path = Path(material.filepath)
        if path.suffix.lower() not in VIDEO_EXTENSIONS or not path.exists():
            continue
        ordered.append(material)
        seen.add(material.id)
    return ordered


def _file_fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"{digest.hexdigest()}:{path.stat().st_size}"


def _asr_output_file(workspace_id: str, fingerprint: str, model: str, language: str, seconds: float) -> Path:
    fingerprint_hash = fingerprint.split(":", 1)[0]
    safe_model = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in model) or "base"
    safe_language = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in language) or "zh"
    seconds_key = "full" if seconds <= 0 else str(int(seconds)) if float(seconds).is_integer() else str(seconds).replace(".", "_")
    path = workspace_dir(workspace_id) / "asr" / fingerprint_hash
    path.mkdir(parents=True, exist_ok=True)
    return path / f"whisper_{safe_model}_{safe_language}_{seconds_key}.json"


def _query_transcript(
    db: Session,
    workspace_id: str,
    fingerprint: str,
    model: str,
    language: str,
    seconds: float,
    material_id: Optional[str] = None,
    status: Optional[str] = None,
) -> Optional[AsrTranscript]:
    query = db.query(AsrTranscript).filter(
        AsrTranscript.workspace_id == workspace_id,
        AsrTranscript.file_fingerprint == fingerprint,
        AsrTranscript.model == model,
        AsrTranscript.language == language,
        AsrTranscript.seconds == seconds,
    )
    if material_id:
        query = query.filter(AsrTranscript.material_id == material_id)
    if status:
        query = query.filter(AsrTranscript.status == status)
    return query.order_by(AsrTranscript.updated_at.desc(), AsrTranscript.created_at.desc()).first()


def _transcript_segments(transcript: AsrTranscript) -> list[Dict[str, Any]]:
    try:
        parsed = json.loads(transcript.segments_json or "[]")
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _transcript_bundle_item(
    material: Material,
    transcript: Optional[AsrTranscript],
    *,
    cache_hit: bool = False,
    status: Optional[str] = None,
    error_message: Optional[str] = None,
) -> Dict[str, Any]:
    effective_status = status or (transcript.status if transcript else "not_started")
    return {
        "material_id": material.id,
        "filename": material.filename,
        "status": effective_status,
        "cache_hit": cache_hit,
        "transcript_id": transcript.id if transcript else None,
        "output_json_path": transcript.output_json_path if transcript else None,
        "text": transcript.text if transcript and transcript.text else "",
        "segments": _transcript_segments(transcript) if transcript else [],
        "error_message": error_message or (transcript.error_message if transcript else None),
    }


def _format_whisper_command(
    command_template: str,
    *,
    job: Job,
    material: Material,
    fingerprint: str,
    output_file: Path,
    model: str,
    language: str,
    seconds: float,
) -> str:
    if "{output_file}" not in command_template:
        raise PipelineRuntimeError("VIDEO_CUT_WHISPER_COMMAND must include {output_file}")
    return command_template.format(
        input=material.filepath,
        job_id=job.id,
        material_id=material.id,
        workspace_id=job.workspace_id,
        fingerprint=fingerprint,
        output_file=str(output_file),
        model=model,
        language=language,
        seconds=seconds,
    )


def _load_asr_payload(output_file: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(output_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PipelineRuntimeError(f"invalid ASR output: {exc}") from exc
    if not isinstance(payload, dict):
        raise PipelineRuntimeError("ASR output must be a JSON object")
    return payload


def _ensure_material_asr(db: Session, job: Job, material: Material, settings) -> Dict[str, Any]:
    snapshot = json_loads(job.input_snapshot_json)
    config = snapshot.get("config", {})
    if not isinstance(config, dict):
        config = {}
    model = str(config.get("whisperModel") or settings.default_whisper_model or "base")
    language = settings.asr_language
    seconds = float(settings.asr_clip_seconds)
    fingerprint = _file_fingerprint(Path(material.filepath))

    direct = _query_transcript(db, job.workspace_id, fingerprint, model, language, seconds, material_id=material.id)
    if direct and direct.status == "done":
        add_log(db, job, f"[ASR] 复用已完成转写：{material.filename}\n")
        return _transcript_bundle_item(material, direct, cache_hit=True)

    cached = _query_transcript(db, job.workspace_id, fingerprint, model, language, seconds, status="done")
    if cached:
        reused = AsrTranscript(
            id=new_id(),
            workspace_id=job.workspace_id,
            material_id=material.id,
            file_fingerprint=fingerprint,
            model=model,
            language=language,
            seconds=seconds,
            status="done",
            output_json_path=cached.output_json_path,
            text=cached.text,
            segments_json=cached.segments_json,
            completed_at=cached.completed_at,
        )
        db.add(reused)
        db.commit()
        db.refresh(reused)
        add_log(db, job, f"[ASR] 命中文件指纹缓存：{material.filename}\n")
        return _transcript_bundle_item(material, reused, cache_hit=True)

    transcript = direct or AsrTranscript(
        id=new_id(),
        workspace_id=job.workspace_id,
        material_id=material.id,
        file_fingerprint=fingerprint,
        model=model,
        language=language,
        seconds=seconds,
        status="pending",
    )
    if not direct:
        db.add(transcript)

    output_file = _asr_output_file(job.workspace_id, fingerprint, model, language, seconds)
    transcript.status = "running"
    transcript.output_json_path = str(output_file)
    transcript.error_message = None
    transcript.updated_at = utcnow()
    db.commit()
    db.refresh(transcript)

    add_log(db, job, f"[ASR] 开始转写：{material.filename}\n")
    try:
        command = _format_whisper_command(
            settings.whisper_command or "",
            job=job,
            material=material,
            fingerprint=fingerprint,
            output_file=output_file,
            model=model,
            language=language,
            seconds=seconds,
        )
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=settings.asr_timeout_seconds,
        )
        if result.returncode != 0:
            raise PipelineRuntimeError(result.stderr[-1200:] or "ASR command failed")
        if not output_file.exists():
            raise PipelineRuntimeError(f"ASR command did not write output_file: {output_file}")
        payload = _load_asr_payload(output_file)
        segments = payload.get("segments")
        if not isinstance(segments, list):
            segments = []
        transcript.status = "done"
        transcript.text = str(payload.get("text") or "").strip()
        transcript.segments_json = json.dumps(segments, ensure_ascii=False)
        transcript.error_message = None
        transcript.completed_at = utcnow()
        transcript.updated_at = transcript.completed_at
        db.commit()
        db.refresh(transcript)
        add_log(db, job, f"[ASR] 转写完成：{material.filename}\n")
        return _transcript_bundle_item(material, transcript)
    except Exception as exc:
        transcript.status = "error"
        transcript.error_message = str(exc)
        transcript.updated_at = utcnow()
        db.commit()
        db.refresh(transcript)
        add_log(db, job, f"[ASR] 转写失败：{material.filename}，{exc}\n")
        raise


def _write_asr_bundle(job: Job, items: list[Dict[str, Any]]) -> Path:
    target = outputs_dir(job.workspace_id, job.id) / "asr_bundle.json"
    target.write_text(
        json.dumps(
            {
                "job_id": job.id,
                "workspace_id": job.workspace_id,
                "materials": items,
                "created_at": utcnow().isoformat() + "Z",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return target


def _asr_stage(ctx) -> None:
    db, job, settings = ctx.db, ctx.job, ctx.settings
    if not settings.whisper_configured:
        raise PipelineRuntimeError("usable VIDEO_CUT_WHISPER_COMMAND with {output_file} is required")

    materials = _job_video_materials(db, job)
    if not materials:
        raise PipelineRuntimeError("at least one video material is required for ASR")

    bundle_items = []
    new_count = 0
    reused_count = 0
    failed_count = 0
    for material in materials:
        result = _ensure_material_asr(db, job, material, settings)
        bundle_items.append(result)
        if result.get("cache_hit"):
            reused_count += 1
        elif result.get("status") == "done":
            new_count += 1
        elif result.get("status") == "error":
            failed_count += 1

    bundle_path = _write_asr_bundle(job, bundle_items)
    snapshot = json_loads(job.input_snapshot_json)
    snapshot["asr_bundle"] = {
        "path": str(bundle_path),
        "materials": bundle_items,
        "created_at": utcnow().isoformat() + "Z",
    }
    job.input_snapshot_json = json_dumps(snapshot)
    db.commit()

    add_log(
        db,
        job,
        f"[Pipeline] ASR completed: {new_count} new, {reused_count} reused, {failed_count} failed\n",
    )
    if failed_count:
        raise PipelineRuntimeError("ASR failed for one or more materials")

