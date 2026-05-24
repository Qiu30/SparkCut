from __future__ import annotations

from typing import Any, Dict, Optional


def _default_explainability(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    config = snapshot.get("config", {})
    if not isinstance(config, dict):
        config = {}
    title = str(config.get("dramaName") or config.get("contentType") or "SparkCut output")
    review_model = str(config.get("reviewModel") or config.get("clipModel") or "review-model")
    return {
        "summary": {
            "title": title,
            "storyline": "",
            "pacing": str(config.get("pace") or ""),
            "clip_count": 0,
            "estimated_duration": 30.0,
            "target_platform": str(config.get("targetPlatform") or ""),
            "aspect_ratio": str(config.get("aspectRatio") or "9:16"),
        },
        "timeline": [],
        "excluded": [],
        "review_report": {
            "status": "not_checked",
            "risk_level": "unknown",
            "model": review_model,
            "items": [],
        },
        "comparison": [],
    }


def _normalize_explainability(candidate: Dict[str, Any], snapshot: Dict[str, Any]) -> Dict[str, Any]:
    defaults = _default_explainability(snapshot)
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

    summary = _normalize_summary(candidate.get("summary"), defaults.get("summary", {}))
    timeline = _normalize_timeline(candidate.get("timeline"), defaults.get("timeline", []), material_names, asr_status_by_source)
    excluded = _normalize_excluded(candidate.get("excluded"), defaults.get("excluded", []))
    review_report = _normalize_review_report(candidate.get("review_report"), defaults.get("review_report", {}))
    review_report["model"] = str(config.get("reviewModel") or review_report.get("model") or "review-model")
    comparison = _normalize_comparison(candidate.get("comparison"), defaults.get("comparison", []), timeline, summary)

    normalized = dict(candidate)
    normalized["summary"] = summary
    normalized["timeline"] = timeline
    normalized["timelines"] = _normalize_timelines(candidate.get("timelines"), timeline, material_names, asr_status_by_source)
    normalized["excluded"] = excluded
    normalized["review_report"] = review_report
    normalized["comparison"] = comparison
    return normalized


def _has_timeline_clips(explanation: Dict[str, Any]) -> bool:
    timeline = explanation.get("timeline")
    if isinstance(timeline, list) and len(timeline) > 0:
        return True
    timelines = explanation.get("timelines")
    if not isinstance(timelines, list):
        return False
    for plan in timelines:
        if isinstance(plan, dict) and isinstance(plan.get("timeline"), list) and plan["timeline"]:
            return True
    return False


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

