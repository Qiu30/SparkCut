from __future__ import annotations

import os
import shutil
import shlex
import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

DEFAULT_LLM_MODEL = "GLM-5.1"
DEFAULT_WHISPER_MODEL = "base"
DEFAULT_ASR_CLIP_SECONDS = 0.0
BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = Path(__file__).resolve().parents[2]
LOCAL_ENV_FILE = BACKEND_DIR / ".env"
LOCAL_FFMPEG_BIN = PROJECT_DIR / "tools" / "ffmpeg" / "bin"
RUNTIME_SETTING_KEYS = [
    "VIDEO_CUT_LLM_ENDPOINT",
    "VIDEO_CUT_LLM_API_KEY",
    "VIDEO_CUT_LLM_MODEL",
    "VIDEO_CUT_LLM_TIMEOUT_SECONDS",
    "VIDEO_CUT_DEFAULT_WHISPER_MODEL",
    "VIDEO_CUT_ASR_CLIP_SECONDS",
]


def env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


def command_seconds(command: Optional[str], default: float = 0.0) -> float:
    if not command:
        return default
    try:
        parts = shlex.split(command, posix=os.name != "nt")
    except ValueError:
        return default
    for index, part in enumerate(parts):
        if part == "--seconds" and index + 1 < len(parts):
            try:
                return float(parts[index + 1])
            except ValueError:
                return default
        if part.startswith("--seconds="):
            try:
                return float(part.split("=", 1)[1])
            except ValueError:
                return default
    return default


@dataclass(frozen=True)
class PipelineSettings:
    mode: str
    max_concurrent_jobs: int
    recover_jobs: bool
    llm_endpoint: Optional[str]
    llm_model: str
    llm_timeout_seconds: int
    whisper_command: Optional[str]
    default_whisper_model: str
    asr_language: str
    asr_clip_seconds: float
    asr_timeout_seconds: int
    ffmpeg_timeout_seconds: int

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_endpoint and os.environ.get("VIDEO_CUT_LLM_API_KEY"))

    @property
    def whisper_configured(self) -> bool:
        return whisper_command_available(self.whisper_command)


def whisper_command_available(command: Optional[str]) -> bool:
    if not command:
        return False
    if "{output_file}" not in command:
        return False
    try:
        parts = shlex.split(command, posix=os.name != "nt")
    except ValueError:
        return False
    if not parts:
        return False

    executable = parts[0].strip("\"'")
    if shutil.which(executable) is None and not Path(executable).exists():
        return False

    uses_local_whisper_script = any(part.endswith("run_whisper_base.py") for part in parts)
    if uses_local_whisper_script and importlib.util.find_spec("whisper") is None:
        return False

    return True


def get_pipeline_settings() -> PipelineSettings:
    whisper_command = os.environ.get("VIDEO_CUT_WHISPER_COMMAND")
    return PipelineSettings(
        mode="real",
        max_concurrent_jobs=max(1, env_int("VIDEO_CUT_MAX_CONCURRENT_JOBS", 1)),
        recover_jobs=env_bool("VIDEO_CUT_RECOVER_JOBS", True),
        llm_endpoint=os.environ.get("VIDEO_CUT_LLM_ENDPOINT"),
        llm_model=os.environ.get("VIDEO_CUT_LLM_MODEL", DEFAULT_LLM_MODEL),
        llm_timeout_seconds=max(5, env_int("VIDEO_CUT_LLM_TIMEOUT_SECONDS", 300)),
        whisper_command=whisper_command,
        default_whisper_model=os.environ.get("VIDEO_CUT_DEFAULT_WHISPER_MODEL", DEFAULT_WHISPER_MODEL),
        asr_language=os.environ.get("VIDEO_CUT_ASR_LANGUAGE", "zh"),
        asr_clip_seconds=max(0.0, env_float("VIDEO_CUT_ASR_CLIP_SECONDS", command_seconds(whisper_command, DEFAULT_ASR_CLIP_SECONDS))),
        asr_timeout_seconds=max(30, env_int("VIDEO_CUT_ASR_TIMEOUT_SECONDS", 1800)),
        ffmpeg_timeout_seconds=max(30, env_int("VIDEO_CUT_FFMPEG_TIMEOUT_SECONDS", 600)),
    )


def ffmpeg_path() -> Optional[str]:
    configured = os.environ.get("VIDEO_CUT_FFMPEG_PATH")
    if configured and Path(configured).exists():
        return configured
    found = shutil.which("ffmpeg")
    if found:
        return found
    bundled = LOCAL_FFMPEG_BIN / "ffmpeg.exe"
    return str(bundled) if bundled.exists() else None


def ffprobe_path() -> Optional[str]:
    configured = os.environ.get("VIDEO_CUT_FFPROBE_PATH")
    if configured and Path(configured).exists():
        return configured
    found = shutil.which("ffprobe")
    if found:
        return found
    bundled = LOCAL_FFMPEG_BIN / "ffprobe.exe"
    return str(bundled) if bundled.exists() else None


def _parse_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    key, value = stripped.split("=", 1)
    return key.strip(), value.strip()


def _quote_env_value(value: str) -> str:
    if any(ch.isspace() for ch in value) or "#" in value:
        return '"' + value.replace('"', '\\"') + '"'
    return value


def _unquote_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def read_local_env_values() -> dict[str, str]:
    values: dict[str, str] = {}
    if not LOCAL_ENV_FILE.exists():
        return values
    for line in LOCAL_ENV_FILE.read_text(encoding="utf-8").splitlines():
        parsed = _parse_env_line(line)
        if parsed:
            key, value = parsed
            values[key] = _unquote_env_value(value)
    return values


def update_runtime_env(updates: dict[str, Any]) -> None:
    clean_updates: dict[str, str] = {}
    for key, value in updates.items():
        if key not in RUNTIME_SETTING_KEYS or value is None:
            continue
        if key == "VIDEO_CUT_LLM_API_KEY" and str(value) == "":
            continue
        clean_updates[key] = str(value)
    if not clean_updates:
        return

    lines = LOCAL_ENV_FILE.read_text(encoding="utf-8").splitlines() if LOCAL_ENV_FILE.exists() else []
    seen: set[str] = set()
    next_lines: list[str] = []
    for line in lines:
        parsed = _parse_env_line(line)
        if not parsed:
            next_lines.append(line)
            continue
        key, _ = parsed
        if key in clean_updates:
            next_lines.append(f"{key}={_quote_env_value(clean_updates[key])}")
            seen.add(key)
        else:
            next_lines.append(line)

    for key in RUNTIME_SETTING_KEYS:
        if key in clean_updates and key not in seen:
            next_lines.append(f"{key}={_quote_env_value(clean_updates[key])}")

    LOCAL_ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_ENV_FILE.write_text("\n".join(next_lines).rstrip() + "\n", encoding="utf-8")
    for key, value in clean_updates.items():
        os.environ[key] = value
