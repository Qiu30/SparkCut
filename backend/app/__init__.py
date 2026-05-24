"""SparkCut demo backend package."""

from __future__ import annotations

import os
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent
LOCAL_ENV_FILE = BACKEND_DIR / ".env"
LOCAL_FFMPEG_BIN = PROJECT_DIR / "tools" / "ffmpeg" / "bin"


def _load_local_env() -> None:
    if not LOCAL_ENV_FILE.exists():
        return
    for line in LOCAL_ENV_FILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _prepend_local_ffmpeg() -> None:
    if not LOCAL_FFMPEG_BIN.exists():
        return
    bin_path = str(LOCAL_FFMPEG_BIN)
    paths = os.environ.get("PATH", "").split(os.pathsep)
    if not any(path.lower() == bin_path.lower() for path in paths):
        os.environ["PATH"] = bin_path + os.pathsep + os.environ.get("PATH", "")


_load_local_env()
_prepend_local_ffmpeg()
