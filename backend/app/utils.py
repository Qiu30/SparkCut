from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Dict


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
