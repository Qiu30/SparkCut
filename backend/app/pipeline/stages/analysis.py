from __future__ import annotations

from typing import Any, Dict

from .. import explainability, llm
from ..engine import PipelineCancelled, PipelineRuntimeError
from ...db_helpers import add_log, save_job_explainability
from ...prompts import build_refine_messages
from ...utils import json_loads


def _analysis_stage(ctx) -> Dict[str, Any]:
    db, job, settings, is_cancelled = ctx.db, ctx.job, ctx.settings, ctx.is_cancelled
    snapshot = json_loads(job.input_snapshot_json)
    clip_model = llm._llm_model_for_snapshot(snapshot, settings, "clipModel")

    refine_request = snapshot.get("refine_request")
    if isinstance(refine_request, dict) and refine_request.get("feedback"):
        return _refine_analysis(ctx, snapshot, refine_request)

    if not settings.llm_configured:
        raise PipelineRuntimeError("VIDEO_CUT_LLM_ENDPOINT and VIDEO_CUT_LLM_API_KEY are required")

    try:
        content = llm._call_llm(snapshot, settings, is_cancelled)
        parsed = llm._extract_json_object(content)
    except PipelineCancelled:
        raise
    except PipelineRuntimeError:
        raise
    except Exception as exc:
        raise PipelineRuntimeError(f"LLM analysis failed: {exc}") from exc

    if not parsed:
        raise PipelineRuntimeError("LLM analysis returned invalid JSON")

    parsed["llm_source"] = {"model": clip_model, "parsed": True}
    explanation = explainability._normalize_explainability(parsed, snapshot)
    if not explainability._has_timeline_clips(explanation):
        raise PipelineRuntimeError("LLM analysis returned no timeline")

    explanation = save_job_explainability(db, job, explanation)
    add_log(db, job, "[Pipeline] LLM analysis completed\n")
    return explanation


def _refine_analysis(
    ctx, snapshot: Dict[str, Any], refine_request: Dict[str, Any],
) -> Dict[str, Any]:
    db, job, settings, is_cancelled = ctx.db, ctx.job, ctx.settings, ctx.is_cancelled
    action = refine_request.get("action", "adjust")
    feedback = refine_request.get("feedback", "")
    clip_model = llm._llm_model_for_snapshot(snapshot, settings, "clipModel")
    add_log(db, job, f"[Pipeline] Starting AI refinement: {action}\n")

    if not settings.llm_configured:
        raise PipelineRuntimeError("VIDEO_CUT_LLM_ENDPOINT and VIDEO_CUT_LLM_API_KEY are required")

    messages = build_refine_messages(action, snapshot, feedback)
    try:
        content = llm._call_llm_with_messages(messages, settings, model=clip_model, is_cancelled=is_cancelled)
        parsed = llm._extract_json_object(content)
    except PipelineCancelled:
        raise
    except PipelineRuntimeError:
        raise
    except Exception as exc:
        raise PipelineRuntimeError(f"Refinement LLM call failed: {exc}") from exc

    if not parsed:
        raise PipelineRuntimeError("Refinement LLM returned invalid JSON")

    base: Dict[str, Any] = {}
    original_explainability = refine_request.get("original_explainability")
    if isinstance(original_explainability, dict):
        for key in ["summary", "timeline", "timelines", "excluded", "review_report", "comparison"]:
            if key in original_explainability:
                base[key] = original_explainability[key]
        if action != "regenerate":
            _drop_default_refine_titles(parsed)

    for key in ["summary", "timeline", "timelines", "excluded", "review_report", "comparison"]:
        if key in parsed:
            parsed_value = parsed[key]
            if key in {"summary", "review_report"} and isinstance(base.get(key), dict) and isinstance(parsed_value, dict):
                base[key] = {**base[key], **parsed_value}
            else:
                base[key] = parsed_value
    if isinstance(base.get("comparison"), list) and len(base["comparison"]) > 1:
        base["comparison"] = base["comparison"][:1]
    base["llm_source"] = {"model": clip_model, "parsed": True, "refine_action": action}

    explanation = explainability._normalize_explainability(base, snapshot)
    if not explainability._has_timeline_clips(explanation):
        raise PipelineRuntimeError("Refinement LLM returned no timeline")

    explanation = save_job_explainability(db, job, explanation)
    add_log(db, job, f"[Pipeline] AI refinement completed: {len(explanation.get('timeline', []))} clips\n")
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

