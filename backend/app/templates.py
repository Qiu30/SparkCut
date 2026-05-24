from __future__ import annotations

from typing import Any, Dict

from sqlalchemy.orm import Session

from .models import Template
from .utils import json_dumps, json_loads, utcnow


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
