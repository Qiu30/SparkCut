from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Template
from ..schemas import TemplateCreate, TemplateOut
from ..templates import serialize_template, template_config, update_template_meta
from ..utils import json_dumps, new_id, utcnow


router = APIRouter(prefix="/api", tags=["templates"])


@router.get("/templates", response_model=list[TemplateOut])
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


@router.post("/templates", response_model=TemplateOut)
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


@router.delete("/templates/{template_id}")
def delete_template(template_id: str, db: Session = Depends(get_db)):
    template = db.get(Template, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="template not found")
    db.delete(template)
    db.commit()
    return {"ok": True}


@router.post("/templates/{template_id}/use", response_model=TemplateOut)
def mark_template_used(template_id: str, db: Session = Depends(get_db)):
    template = db.get(Template, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="template not found")
    updated = update_template_meta(db, template, lastUsedAt=utcnow().isoformat() + "Z")
    return serialize_template(updated)


@router.post("/templates/{template_id}/duplicate", response_model=TemplateOut)
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


@router.post("/templates/{template_id}/default", response_model=TemplateOut)
def set_default_template(template_id: str, db: Session = Depends(get_db)):
    template = db.get(Template, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="template not found")
    for same_type in db.query(Template).filter(Template.type == template.type).all():
        update_template_meta(db, same_type, isDefault=(same_type.id == template.id))
    db.refresh(template)
    return serialize_template(template)
