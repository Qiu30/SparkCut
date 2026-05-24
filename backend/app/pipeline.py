from __future__ import annotations

import json
import queue
import os
import hashlib
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from sqlalchemy.orm import Session

from .models import AsrTranscript, Job, Material, OutputVideo
from .llm_models import normalize_llm_urls
from .services import (
    add_log,
    attach_mock_explainability,
    build_mock_explainability,
    create_mock_output,
    first_mp4_material,
    job_step_seconds,
    json_dumps,
    json_loads,
    new_id,
    ordered_materials,
    outputs_dir,
    save_job_explainability,
    utcnow,
    workspace_dir,
)
from .prompts import build_llm_messages, build_review_messages
from .settings import ffmpeg_path, ffprobe_path, get_pipeline_settings


StageGuard = Callable[[], bool]


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
    if not os.environ.get("VIDEO_CUT_LLM_API_KEY"):
        missing_env_vars.append("VIDEO_CUT_LLM_API_KEY")
    if not whisper_command_present:
        missing_env_vars.append("VIDEO_CUT_WHISPER_COMMAND")
    elif not whisper_available:
        missing_env_vars.append("VIDEO_CUT_WHISPER_COMMAND:{output_file}")
    if not ffmpeg_available:
        missing_env_vars.append("ffmpeg")

    if settings.mode == "real":
        if not settings.llm_endpoint:
            blocking_requirements.append("缺少 VIDEO_CUT_LLM_ENDPOINT，无法调用真实 LLM。")
        if not os.environ.get("VIDEO_CUT_LLM_API_KEY"):
            blocking_requirements.append("缺少 VIDEO_CUT_LLM_API_KEY，无法调用真实 LLM。")
        if not whisper_command_present:
            blocking_requirements.append("缺少 VIDEO_CUT_WHISPER_COMMAND，无法执行真实转写。")
        elif not whisper_available:
            blocking_requirements.append("已配置 VIDEO_CUT_WHISPER_COMMAND，但命令不可用、缺少 {output_file}，或当前环境缺少 Whisper 依赖。")
        if not ffmpeg_available:
            blocking_requirements.append("当前环境未检测到 ffmpeg，无法执行真实合成。")
        if not ffprobe_available:
            warnings.append("当前环境未检测到 ffprobe，素材探查会退化。")
    elif settings.mode == "auto":
        if not settings.llm_endpoint or not os.environ.get("VIDEO_CUT_LLM_API_KEY"):
            warnings.append("未完整配置真实 LLM，任务会在分析阶段回退到 mock 方案。")
        if not whisper_command_present:
            warnings.append("未配置 Whisper 命令，任务会跳过真实转写。")
        elif not whisper_available:
            warnings.append("已配置 Whisper 命令，但命令不可用、缺少 {output_file}，或当前环境缺少 Whisper 依赖，任务会跳过真实转写。")
        if not ffmpeg_available:
            warnings.append("当前环境未检测到 ffmpeg，任务会回退到 mock 输出。")
        if not ffprobe_available:
            warnings.append("当前环境未检测到 ffprobe，素材探查会退化。")

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
    settings = get_pipeline_settings()
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
            _probe_stage(db, job)
        elif stage == "asr":
            _asr_stage(db, job, settings)
        elif stage == "analysis":
            explanation = _analysis_stage(db, job, settings, is_cancelled)
        elif stage == "review":
            _review_stage(db, job, explanation, settings, is_cancelled)
        elif stage == "compose":
            outputs = _compose_stage(db, job, settings, explanation)
        elif stage == "package":
            _package_stage(db, job, outputs)

        time.sleep(job_step_seconds())

    return outputs


def _raise_if_cancelled(is_cancelled: StageGuard) -> None:
    if is_cancelled():
        raise PipelineCancelled()


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
        if settings.mode == "real":
            raise
        return _transcript_bundle_item(material, transcript, status="error", error_message=str(exc))


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


def _probe_stage(db: Session, job: Job) -> None:
    snapshot = json_loads(job.input_snapshot_json)
    materials = snapshot.get("materials", [])
    add_log(db, job, f"[Pipeline] 输入素材 {len(materials) if isinstance(materials, list) else 0} 个\n")
    add_log(
        db,
        job,
        f"[Pipeline] ffprobe {'可用' if ffprobe_path() else '不可用'}，"
        "v0.4 会优先使用上传时保存的 metadata\n",
    )


def _asr_stage(db: Session, job: Job, settings) -> None:
    if settings.mode == "mock":
        add_log(db, job, "[Mock] 跳过真实 ASR，沿用模拟对白线索\n")
        return
    if not settings.whisper_configured:
        message = "[Pipeline] Whisper 命令不可用或缺少 {output_file}，ASR 阶段降级为模拟\n"
        if settings.mode == "real":
            raise PipelineRuntimeError("usable VIDEO_CUT_WHISPER_COMMAND with {output_file} is required in real mode")
        add_log(db, job, message)
        return

    materials = _job_video_materials(db, job)
    if not materials:
        if settings.mode == "real":
            raise PipelineRuntimeError("at least one video material is required for ASR in real mode")
        add_log(db, job, "[Pipeline] 没有可用于 ASR 的视频素材\n")
        return

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
        f"[Pipeline] ASR 完成：新增转写 {new_count} 个，复用 {reused_count} 个，失败 {failed_count} 个\n",
    )
    if settings.mode == "real" and failed_count:
        raise PipelineRuntimeError("ASR failed for one or more materials in real mode")


def _analysis_stage(db: Session, job: Job, settings, is_cancelled: Optional[StageGuard] = None) -> Dict[str, Any]:
    snapshot = json_loads(job.input_snapshot_json)
    clip_model = _llm_model_for_snapshot(snapshot, settings, "clipModel")

    refine_request = snapshot.get("refine_request")
    if isinstance(refine_request, dict) and refine_request.get("feedback"):
        return _refine_analysis(db, job, settings, snapshot, refine_request, is_cancelled)

    if settings.mode == "mock" or not settings.llm_configured:
        if settings.mode == "real" and not settings.llm_configured:
            raise PipelineRuntimeError("VIDEO_CUT_LLM_ENDPOINT and VIDEO_CUT_LLM_API_KEY are required in real mode")
        if settings.mode != "mock":
            add_log(db, job, "[Pipeline] 未配置 LLM endpoint/key，剧情分析降级为 mock 解释\n")
        explanation = attach_mock_explainability(db, job)
        add_log(
            db,
            job,
            f"[Pipeline] 已生成可解释方案：{len(explanation.get('timeline', []))} 个入选片段，"
            f"{len(explanation.get('excluded', []))} 个排除片段\n",
        )
        return explanation

    base = build_mock_explainability(snapshot)
    try:
        content = _call_llm(snapshot, settings, is_cancelled)
        parsed = _extract_json_object(content)
        if parsed:
            for key in ["summary", "timeline", "timelines", "excluded", "review_report", "comparison"]:
                if key in parsed:
                    base[key] = parsed[key]
            base["llm_source"] = {"model": clip_model, "parsed": True}
        else:
            base["llm_source"] = {
                "model": clip_model,
                "parsed": False,
                "notes": content[:2000],
            }
    except PipelineCancelled:
        raise
    except Exception as exc:
        if settings.mode == "real":
            raise PipelineRuntimeError(f"LLM analysis failed: {exc}") from exc
        add_log(db, job, f"[Pipeline] LLM 调用失败，已降级为 mock：{exc}\n")
        base["llm_source"] = {"model": clip_model, "parsed": False, "error": "fallback"}
    explanation = save_job_explainability(db, job, _normalize_explainability(base, snapshot))
    add_log(db, job, "[Pipeline] LLM 剧情分析阶段完成\n")
    return explanation


def _refine_analysis(
    db: Session, job: Job, settings, snapshot: Dict[str, Any], refine_request: Dict[str, Any],
    is_cancelled: Optional[StageGuard] = None,
) -> Dict[str, Any]:
    from .prompts import build_refine_messages

    action = refine_request.get("action", "adjust")
    feedback = refine_request.get("feedback", "")
    clip_model = _llm_model_for_snapshot(snapshot, settings, "clipModel")
    add_log(db, job, f"[Pipeline] 开始 AI 优化（{action}）\n")

    if not settings.llm_configured:
        add_log(db, job, "[Pipeline] LLM 未配置，优化降级为 mock\n")
        return attach_mock_explainability(db, job)

    messages = build_refine_messages(action, snapshot, feedback)
    try:
        content = _call_llm_with_messages(messages, settings, model=clip_model, is_cancelled=is_cancelled)
        parsed = _extract_json_object(content)
    except PipelineCancelled:
        raise
    except Exception as exc:
        if settings.mode == "real":
            raise PipelineRuntimeError(f"Refinement LLM call failed: {exc}") from exc
        add_log(db, job, f"[Pipeline] AI 优化失败，已降级为 mock：{exc}\n")
        return attach_mock_explainability(db, job)

    if not parsed:
        if settings.mode == "real":
            raise PipelineRuntimeError("Refinement LLM returned invalid response")
        add_log(db, job, "[Pipeline] AI 优化返回无效 JSON，已降级为 mock\n")
        return attach_mock_explainability(db, job)

    base = build_mock_explainability(snapshot)
    original_explainability = refine_request.get("original_explainability")
    if isinstance(original_explainability, dict):
        for key in ["summary", "timeline", "timelines", "excluded", "review_report", "comparison"]:
            if key in original_explainability:
                base[key] = original_explainability[key]
        if action != "regenerate":
            _drop_default_refine_titles(parsed)
    for key in ["summary", "timeline", "excluded", "review_report", "comparison"]:
        if key in parsed:
            parsed_value = parsed[key]
            if key in {"summary", "review_report"} and isinstance(base.get(key), dict) and isinstance(parsed_value, dict):
                base[key] = {**base[key], **parsed_value}
            else:
                base[key] = parsed_value
    base.pop("timelines", None)
    if isinstance(base.get("comparison"), list) and len(base["comparison"]) > 1:
        base["comparison"] = base["comparison"][:1]
    base["llm_source"] = {"model": clip_model, "parsed": True, "refine_action": action}

    explanation = save_job_explainability(db, job, _normalize_explainability(base, snapshot))
    add_log(
        db, job,
        f"[Pipeline] AI 优化完成：{len(explanation.get('timeline', []))} 个入选片段\n",
    )
    return explanation


def _drop_default_refine_titles(parsed: Dict[str, Any]) -> None:
    summary = parsed.get("summary")
    if isinstance(summary, dict) and str(summary.get("title") or "").strip() in {"演示精剪版", "演示精简版"}:
        summary.pop("title", None)
    comparison = parsed.get("comparison")
    if isinstance(comparison, list):
        for item in comparison:
            if isinstance(item, dict) and str(item.get("name") or "").strip() in {"演示精剪版", "演示精简版"}:
                item.pop("name", None)


def _llm_model_for_snapshot(snapshot: Dict[str, Any], settings, config_key: str = "clipModel") -> str:
    config = snapshot.get("config", {})
    if not isinstance(config, dict):
        config = {}
    selected = str(config.get(config_key) or "").strip()
    return selected or settings.llm_model


def _normalize_explainability(candidate: Dict[str, Any], snapshot: Dict[str, Any]) -> Dict[str, Any]:
    fallback = build_mock_explainability(snapshot)
    config = snapshot.get("config", {})
    if not isinstance(config, dict):
        config = {}
    materials = snapshot.get("materials", [])
    material_names = {
        str(material.get("id")): material.get("filename")
        for material in materials
        if isinstance(material, dict) and material.get("id")
    }
    asr_status_by_source = _asr_status_by_source(snapshot)

    summary = _normalize_summary(candidate.get("summary"), fallback.get("summary", {}))
    timeline = _normalize_timeline(candidate.get("timeline"), fallback.get("timeline", []), material_names, asr_status_by_source)
    excluded = _normalize_excluded(candidate.get("excluded"), fallback.get("excluded", []))
    review_report = _normalize_review_report(candidate.get("review_report"), fallback.get("review_report", {}))
    review_report["model"] = str(config.get("reviewModel") or review_report.get("model") or "GLM-5.1")
    comparison = _normalize_comparison(candidate.get("comparison"), fallback.get("comparison", []), timeline, summary)

    normalized = dict(candidate)
    normalized["summary"] = summary
    normalized["timeline"] = timeline
    normalized["timelines"] = _normalize_timelines(candidate.get("timelines"), timeline, material_names, asr_status_by_source)
    normalized["excluded"] = excluded
    normalized["review_report"] = review_report
    normalized["comparison"] = comparison
    return normalized


def _asr_status_by_source(snapshot: Dict[str, Any]) -> Dict[str, str]:
    bundle = snapshot.get("asr_bundle")
    if not isinstance(bundle, dict):
        return {}
    items = bundle.get("materials")
    if not isinstance(items, list):
        return {}
    result: Dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "")
        for key in [item.get("material_id"), item.get("filename")]:
            if key:
                result[str(key)] = status
    return result


def _normalize_summary(value: Any, fallback: Dict[str, Any]) -> Dict[str, Any]:
    summary = dict(fallback) if isinstance(fallback, dict) else {}
    if isinstance(value, dict):
        summary.update({key: item for key, item in value.items() if item is not None})
    elif isinstance(value, str) and value.strip():
        summary["storyline"] = value.strip()
    summary.setdefault("title", "演示精剪版")
    summary.setdefault("storyline", "基于输入素材生成的混剪方案。")
    summary.setdefault("pacing", "剧情向")
    summary["clip_count"] = int(_as_number(summary.get("clip_count"), 0))
    summary["estimated_duration"] = _as_number(summary.get("estimated_duration"), 30.0)
    summary.setdefault("target_platform", "通用")
    summary.setdefault("aspect_ratio", "9:16")
    return summary


def _normalize_timeline(
    value: Any,
    fallback: list[Dict[str, Any]],
    material_names: Dict[str, Any],
    asr_status_by_source: Optional[Dict[str, str]] = None,
) -> list[Dict[str, Any]]:
    asr_status_by_source = asr_status_by_source or {}
    source_items = value if isinstance(value, list) else fallback
    timeline = []
    for index, item in enumerate(source_items):
        if not isinstance(item, dict):
            continue
        source = item.get("source") or material_names.get(str(item.get("material_id"))) or item.get("filename")
        source_text = str(source or f"片段 {index + 1}")
        evidence_source = str(item.get("evidence_source") or item.get("evidenceSource") or "").strip()
        if not evidence_source:
            evidence_source = "asr" if asr_status_by_source.get(source_text) == "done" else "metadata"
        start = _as_number(item.get("start"), _as_number(item.get("start_time"), 0.0))
        end = _as_number(item.get("end"), _as_number(item.get("end_time"), start + _as_number(item.get("duration"), 5.0)))
        duration = _as_number(item.get("duration"), max(0.0, end - start))
        timeline.append(
            {
                "source": source_text,
                "start": round(start, 1),
                "end": round(end, 1),
                "duration": round(duration, 1),
                "score": round(_as_number(item.get("score"), 8.5), 1),
                "reason": str(
                    item.get("reason")
                    or item.get("selection_reason")
                    or item.get("text_overlay")
                    or "LLM 建议入选该片段。"
                ),
                "evidence_source": evidence_source,
                "evidence_text": str(item.get("evidence_text") or item.get("evidenceText") or ""),
            }
        )
    return timeline or fallback


def _normalize_excluded(value: Any, fallback: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    if not isinstance(value, list):
        return fallback
    excluded = []
    for index, item in enumerate(value):
        if isinstance(item, dict):
            excluded.append(
                {
                    "source": str(item.get("source") or item.get("filename") or f"排除片段 {index + 1}"),
                    "reason": str(item.get("reason") or item.get("detail") or "LLM 建议排除。"),
                }
            )
        elif isinstance(item, str):
            excluded.append({"source": f"排除片段 {index + 1}", "reason": item})
    return excluded


def _normalize_review_report(value: Any, fallback: Dict[str, Any]) -> Dict[str, Any]:
    report = dict(fallback) if isinstance(fallback, dict) else {}
    if isinstance(value, dict):
        report.update({key: item for key, item in value.items() if item is not None})
    report.setdefault("status", "passed")
    report.setdefault("risk_level", "低")
    report.setdefault("model", "review-model")
    items = report.get("items")
    if not isinstance(items, list):
        issues = report.get("issues")
        details = report.get("details") or report.get("reason")
        items = []
        if isinstance(issues, list):
            for issue in issues:
                items.append(
                    {
                        "rule": str(issue.get("rule", "LLM 审查") if isinstance(issue, dict) else "LLM 审查"),
                        "time": str(issue.get("time", "全片") if isinstance(issue, dict) else "全片"),
                        "result": str(issue.get("result", issue) if isinstance(issue, dict) else issue),
                        "action": str(issue.get("action", "人工复核") if isinstance(issue, dict) else "人工复核"),
                    }
                )
        if not items:
            items.append(
                {
                    "rule": "LLM 审查",
                    "time": "全片",
                    "result": str(details or "未命中明确风险"),
                    "action": "允许输出" if report.get("status") == "passed" else "人工复核",
                }
            )
    report["items"] = items
    return report


def _normalize_comparison(
    value: Any,
    fallback: list[Dict[str, Any]],
    timeline: list[Dict[str, Any]],
    summary: Dict[str, Any],
) -> list[Dict[str, Any]]:
    if isinstance(value, list):
        source_items = value
    elif isinstance(value, dict):
        source_items = [
            {
                "name": "LLM 方案对比",
                "duration_seconds": summary.get("estimated_duration", 30),
                "clip_count": len(timeline),
                "strength": value.get("value_gain") or value.get("new_structure") or "LLM 生成方案",
                "tradeoff": value.get("original_structure") or "需结合人工复核判断",
            }
        ]
    else:
        source_items = fallback
    comparison = []
    for index, item in enumerate(source_items):
        if not isinstance(item, dict):
            continue
        comparison.append(
            {
                "name": str(item.get("name") or f"方案 {index + 1}"),
                "duration_seconds": _as_number(item.get("duration_seconds"), summary.get("estimated_duration", 30)),
                "clip_count": int(_as_number(item.get("clip_count"), len(timeline))),
                "strength": str(item.get("strength") or item.get("summary") or "优势待复核"),
                "tradeoff": str(item.get("tradeoff") or item.get("risk") or "取舍待复核"),
            }
        )
    return comparison or fallback


def _normalize_timelines(
    value: Any,
    default_timeline: list[Dict[str, Any]],
    material_names: Dict[str, Any],
    asr_status_by_source: Optional[Dict[str, str]] = None,
) -> list[Dict[str, Any]]:
    if not isinstance(value, list) or not value:
        return []
    timelines = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or f"方案 {index + 1}")
        tl = item.get("timeline")
        normalized_tl = (
            _normalize_timeline(tl, default_timeline, material_names, asr_status_by_source)
            if isinstance(tl, list)
            else list(default_timeline)
        )
        timelines.append({"name": name, "timeline": normalized_tl})
    return timelines


def _as_number(value: Any, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float(fallback)
    return parsed


def _review_stage(
    db: Session,
    job: Job,
    explanation: Dict[str, Any],
    settings,
    is_cancelled: Optional[StageGuard] = None,
) -> None:
    snapshot = json_loads(job.input_snapshot_json)
    review_model = _llm_model_for_snapshot(snapshot, settings, "reviewModel")
    if settings.mode != "mock" and settings.llm_configured:
        try:
            content = _call_llm_with_messages(
                build_review_messages(snapshot, explanation),
                settings,
                model=review_model,
                is_cancelled=is_cancelled,
            )
            parsed = _extract_json_object(content)
            if parsed:
                report_value = parsed.get("review_report") if isinstance(parsed.get("review_report"), dict) else parsed
                explanation["review_report"] = _normalize_review_report(
                    report_value,
                    build_mock_explainability(snapshot).get("review_report", {}),
                )
                explanation["review_report"]["model"] = review_model
                explanation = save_job_explainability(db, job, _normalize_explainability(explanation, snapshot))
                add_log(db, job, f"[Pipeline] LLM 审查阶段完成：{review_model}\n")
        except PipelineCancelled:
            raise
        except Exception as exc:
            if settings.mode == "real":
                raise PipelineRuntimeError(f"Review LLM call failed: {exc}") from exc
            add_log(db, job, f"[Pipeline] LLM 审查失败，沿用分析阶段审查报告：{exc}\n")

    report = explanation.get("review_report") if isinstance(explanation, dict) else None
    if isinstance(report, dict):
        add_log(
            db,
            job,
            f"[Pipeline] 审查状态 {report.get('status', 'unknown')}，风险等级 {report.get('risk_level', '未知')}\n",
        )
    elif settings.mode == "real":
        raise PipelineRuntimeError("review report is missing")
    else:
        add_log(db, job, "[Pipeline] 审查报告缺失，已按 not_checked 处理\n")


def _compose_stage(
    db: Session, job: Job, settings, explanation: Dict[str, Any],
) -> list[OutputVideo]:
    timelines = explanation.get("timelines") if isinstance(explanation, dict) else None
    has_multiple = isinstance(timelines, list) and len(timelines) > 1

    if settings.mode == "mock":
        return _compose_mock_outputs(db, job, has_multiple)

    ffmpeg = ffmpeg_path()
    if not ffmpeg:
        if settings.mode == "real":
            raise PipelineRuntimeError("ffmpeg is required in real mode")
        add_log(db, job, "[Pipeline] 未检测到 ffmpeg，视频合成降级为复制首个 MP4\n")
        return _compose_mock_outputs(db, job, has_multiple)

    return _compose_real_outputs(db, job, settings, ffmpeg, explanation, has_multiple)


def _compose_mock_outputs(db: Session, job: Job, has_multiple: bool) -> list[OutputVideo]:
    outputs: list[OutputVideo] = []
    count = 2 if has_multiple else 1
    for index in range(count):
        suffix = f"_plan{index + 1}" if count > 1 else ""
        name = f"演示精剪版" if index == 0 else f"备选方案 {index + 1}"
        output = create_mock_output(db, job, name=name, suffix=suffix)
        if output:
            outputs.append(output)
    return outputs


def _compose_real_outputs(
    db: Session,
    job: Job,
    settings,
    ffmpeg: str,
    explanation: Dict[str, Any],
    has_multiple: bool,
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
        timelines = [{"name": summary.get("title", "真实混剪输出"), "timeline": explanation.get("timeline", [])}]

    for index, plan in enumerate(timelines):
        if not isinstance(plan, dict):
            continue
        plan_name = str(plan.get("name") or f"方案 {index + 1}")
        plan_tl = plan.get("timeline", [])
        clips = _timeline_clips(db, job, {"timeline": plan_tl}, target_duration)
        suffix = f"_plan{index + 1}" if len(timelines) > 1 else ""
        try:
            output = _render_ffmpeg_output(
                db, job, ffmpeg, clips,
                plan_name=plan_name, plan_suffix=suffix,
                target_duration=target_duration,
            )
            outputs.append(output)
        except Exception as exc:
            if settings.mode == "real":
                raise
            add_log(db, job, f"[Pipeline] 方案「{plan_name}」ffmpeg 合成失败，已降级：{exc}\n")
            mock_output = create_mock_output(db, job, name=plan_name, suffix=suffix)
            if mock_output:
                outputs.append(mock_output)
    return outputs


def _package_stage(db: Session, job: Job, outputs: list[OutputVideo]) -> None:
    if outputs:
        for output in outputs:
            add_log(db, job, f"[Pipeline] 输出文件就绪：{output.name}（{output.filename}）\n")
    else:
        add_log(db, job, "[Pipeline] 没有可预览 MP4 输出，保留任务日志和解释报告\n")


def _call_llm(snapshot: Dict[str, Any], settings, is_cancelled: Optional[StageGuard] = None) -> str:
    model = _llm_model_for_snapshot(snapshot, settings, "clipModel")
    messages = build_llm_messages(snapshot, model)
    return _call_llm_with_messages(messages, settings, model=model, is_cancelled=is_cancelled)


def _call_llm_with_messages(
    messages: list[Dict[str, str]],
    settings,
    model: Optional[str] = None,
    is_cancelled: Optional[StageGuard] = None,
) -> str:
    api_key = os.environ.get("VIDEO_CUT_LLM_API_KEY")
    if not settings.llm_endpoint or not api_key:
        raise PipelineRuntimeError("LLM endpoint/key not configured")
    request_model = model or settings.llm_model
    payload = {
        "model": request_model,
        "messages": messages,
        "temperature": 0.2,
    }
    llm_urls = normalize_llm_urls(settings.llm_endpoint)
    if not llm_urls.chat_completions_url:
        raise PipelineRuntimeError("LLM endpoint/key not configured")
    request = urllib.request.Request(
        llm_urls.chat_completions_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        data = _request_json_cancellable(request, settings.llm_timeout_seconds, is_cancelled)
    except urllib.error.HTTPError as exc:
        raise PipelineRuntimeError(f"LLM HTTP {exc.code}") from exc
    choices = data.get("choices") or []
    if not choices:
        raise PipelineRuntimeError("LLM returned no choices")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if not content:
        raise PipelineRuntimeError("LLM returned empty content")
    return str(content)


def _send_json_request(request: urllib.request.Request, timeout: int) -> Dict[str, Any]:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise PipelineRuntimeError("LLM returned invalid JSON payload")
    return data


def _request_json_cancellable(
    request: urllib.request.Request,
    timeout: int,
    is_cancelled: Optional[StageGuard],
) -> Dict[str, Any]:
    if is_cancelled is None:
        return _send_json_request(request, timeout)
    if is_cancelled():
        raise PipelineCancelled()

    result_queue: "queue.Queue[tuple[str, Any]]" = queue.Queue(maxsize=1)

    def target() -> None:
        try:
            result_queue.put(("ok", _send_json_request(request, timeout)), block=False)
        except Exception as exc:  # pragma: no cover - exercised through queue result
            result_queue.put(("error", exc), block=False)

    threading.Thread(target=target, daemon=True).start()
    while True:
        if is_cancelled():
            raise PipelineCancelled()
        try:
            status, payload = result_queue.get(timeout=0.2)
        except queue.Empty:
            continue
        if status == "error":
            raise payload
        if not isinstance(payload, dict):
            raise PipelineRuntimeError("LLM returned invalid JSON payload")
        return payload


def _extract_json_object(content: str) -> Optional[Dict[str, Any]]:
    start = content.find("{")
    end = content.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(content[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _load_asr_segments(db: Session, material_id: str) -> list[Dict[str, Any]]:
    transcript = (
        db.query(AsrTranscript)
        .filter(AsrTranscript.material_id == material_id, AsrTranscript.status == "done")
        .order_by(AsrTranscript.updated_at.desc(), AsrTranscript.created_at.desc())
        .first()
    )
    return _transcript_segments(transcript) if transcript else []


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
        seg_end = _as_number(seg.get("end"), 0)
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
        clips = [{"material": fallback_source, "start": 0.0, "duration": max(1.0, target_duration)}]
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
        start = max(0.0, _as_number(item.get("start"), _as_number(item.get("start_time"), 0.0)))
        if source_duration > 0:
            start = min(start, max(0.0, source_duration - 1.0))
        end = _as_number(item.get("end"), _as_number(item.get("end_time"), start + _as_number(item.get("duration"), 5.0)))
        duration = _as_number(item.get("duration"), max(0.0, end - start))
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
