from __future__ import annotations

from typing import Any, Dict

from .. import explainability, llm
from ..engine import PipelineCancelled, PipelineRuntimeError
from ...db_helpers import add_log, save_job_explainability
from ...prompts import build_review_messages
from ...utils import json_loads


def _review_stage(ctx, explanation: Dict[str, Any]) -> None:
    db, job, settings, is_cancelled = ctx.db, ctx.job, ctx.settings, ctx.is_cancelled
    snapshot = json_loads(job.input_snapshot_json)
    review_model = llm._llm_model_for_snapshot(snapshot, settings, "reviewModel")
    if not settings.llm_configured:
        raise PipelineRuntimeError("VIDEO_CUT_LLM_ENDPOINT and VIDEO_CUT_LLM_API_KEY are required")

    try:
        content = llm._call_llm_with_messages(
            build_review_messages(snapshot, explanation),
            settings,
            model=review_model,
            is_cancelled=is_cancelled,
        )
        parsed = llm._extract_json_object(content)
    except PipelineCancelled:
        raise
    except PipelineRuntimeError:
        raise
    except Exception as exc:
        raise PipelineRuntimeError(f"Review LLM call failed: {exc}") from exc

    if not parsed:
        raise PipelineRuntimeError("Review LLM returned invalid JSON")

    report_value = parsed.get("review_report") if isinstance(parsed.get("review_report"), dict) else parsed
    explanation["review_report"] = explainability._normalize_review_report(
        report_value,
        explainability._default_explainability(snapshot).get("review_report", {}),
    )
    explanation["review_report"]["model"] = review_model
    explanation = save_job_explainability(db, job, explainability._normalize_explainability(explanation, snapshot))
    add_log(db, job, f"[Pipeline] LLM review completed: {review_model}\n")

    report = explanation.get("review_report") if isinstance(explanation, dict) else None
    if not isinstance(report, dict):
        raise PipelineRuntimeError("review report is missing")
    add_log(
        db,
        job,
        f"[Pipeline] Review status: {report.get('status', 'unknown')}; risk: {report.get('risk_level', 'unknown')}\n",
    )
