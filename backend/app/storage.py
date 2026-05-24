from __future__ import annotations

import os
from pathlib import Path

from .database import STORAGE_DIR
from .utils import new_id


ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".webm"}
MAX_VIDEO_BYTES = int(os.environ.get("VIDEO_CUT_MAX_VIDEO_BYTES", str(2 * 1024 * 1024 * 1024)))
MAX_WORKSPACE_MATERIALS = int(os.environ.get("VIDEO_CUT_MAX_WORKSPACE_MATERIALS", "100"))
MAX_JOB_MATERIALS = int(os.environ.get("VIDEO_CUT_MAX_JOB_MATERIALS", "100"))


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
