from __future__ import annotations

import importlib
import json
import sys
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient


def configure_real_pipeline_env(tmp_path, monkeypatch) -> None:
    fake_asr = tmp_path / "fake_asr.py"
    fake_asr.write_text(
        """
from __future__ import annotations
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("input")
parser.add_argument("--output-file", required=True)
parser.add_argument("--material-id", required=True)
parser.add_argument("--fingerprint", required=True)
parser.add_argument("--model", default="base")
parser.add_argument("--seconds", type=float, default=0)
parser.add_argument("--language", default="zh")
args = parser.parse_args()

target = Path(args.output_file)
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps({
    "material_id": args.material_id,
    "fingerprint": args.fingerprint,
    "source": args.input,
    "model": args.model,
    "seconds": args.seconds,
    "language": args.language,
    "text": f"transcript for {args.material_id}",
    "segments": [{"start": 0, "end": 2, "text": f"line {args.material_id}"}],
}, ensure_ascii=False), encoding="utf-8")
""",
        encoding="utf-8",
    )
    fake_ffmpeg = tmp_path / "ffmpeg.exe"
    fake_ffmpeg.write_text("fake ffmpeg", encoding="utf-8")
    fake_ffprobe = tmp_path / "ffprobe.exe"
    fake_ffprobe.write_text("fake ffprobe", encoding="utf-8")
    monkeypatch.setenv("VIDEO_CUT_LLM_ENDPOINT", "https://llm.example.test/chat/completions")
    monkeypatch.setenv("VIDEO_CUT_LLM_API_KEY", "test-key")
    monkeypatch.setenv("VIDEO_CUT_FFMPEG_PATH", str(fake_ffmpeg))
    monkeypatch.setenv("VIDEO_CUT_FFPROBE_PATH", str(fake_ffprobe))
    monkeypatch.setenv(
        "VIDEO_CUT_WHISPER_COMMAND",
        f'{sys.executable} "{fake_asr}" "{{input}}" --output-file "{{output_file}}" --material-id {{material_id}} --fingerprint {{fingerprint}} --model {{model}} --seconds {{seconds}} --language {{language}}',
    )


def make_client(tmp_path, monkeypatch, *, pipeline_ready: bool = False, clear_pipeline_env: bool = True) -> TestClient:
    monkeypatch.setenv("VIDEO_CUT_DB_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("VIDEO_CUT_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("VIDEO_CUT_JOB_STEP_SECONDS", "0.01")
    monkeypatch.setenv("VIDEO_CUT_MAX_CONCURRENT_JOBS", "2")
    if clear_pipeline_env:
        for key in [
            "VIDEO_CUT_LLM_API_KEY",
            "VIDEO_CUT_LLM_ENDPOINT",
            "VIDEO_CUT_LLM_MODEL",
            "VIDEO_CUT_LLM_TIMEOUT_SECONDS",
            "VIDEO_CUT_WHISPER_COMMAND",
            "VIDEO_CUT_FFMPEG_PATH",
            "VIDEO_CUT_FFPROBE_PATH",
        ]:
            monkeypatch.delenv(key, raising=False)
    if pipeline_ready:
        configure_real_pipeline_env(tmp_path, monkeypatch)
    for name in list(sys.modules):
        if name.startswith("app."):
            del sys.modules[name]
    module = importlib.import_module("app.main")
    monkeypatch.setattr(module, "read_local_env_values", lambda: {})
    module.on_startup()
    return TestClient(module.app)


def install_successful_pipeline_stubs(monkeypatch, *, stub_llm: bool = True) -> None:
    from app.pipeline import ffmpeg, llm
    from app.db_helpers import first_mp4_material
    from app.models import OutputVideo
    from app.storage import outputs_dir
    from app.utils import new_id

    def fake_call_llm_with_messages(messages, settings, model=None, is_cancelled=None):
        payload = {
            "summary": {
                "title": "Test cut",
                "storyline": "Test storyline",
                "clip_count": 1,
                "estimated_duration": 2,
                "target_platform": "test",
                "aspect_ratio": "9:16",
            },
            "timeline": [
                {
                    "source": "1.mp4",
                    "start": 0,
                    "end": 2,
                    "duration": 2,
                    "score": 9,
                    "reason": "test clip",
                }
            ],
            "review_report": {
                "status": "passed",
                "risk_level": "low",
                "items": [{"rule": "test", "time": "all", "result": "ok", "action": "allow"}],
            },
            "comparison": [
                {
                    "name": "Test cut",
                    "duration_seconds": 2,
                    "clip_count": 1,
                    "strength": "fast",
                    "tradeoff": "none",
                }
            ],
        }
        return json.dumps(payload, ensure_ascii=False)

    def fake_render_ffmpeg_output(
        db,
        job,
        ffmpeg,
        clips,
        plan_name="Real cut",
        plan_suffix="",
        target_duration=30.0,
    ):
        source = first_mp4_material(db, job.workspace_id)
        assert source is not None
        target = outputs_dir(job.workspace_id, job.id) / f"videocut_{job.id}{plan_suffix}_real_cut.mp4"
        target.write_bytes(Path(source.filepath).read_bytes())
        output = OutputVideo(
            id=new_id(),
            job_id=job.id,
            name=plan_name,
            filename=target.name,
            filepath=str(target),
            size_bytes=target.stat().st_size,
            duration=round(sum(max(0.0, clip.get("duration", 0)) for clip in clips), 1) if clips else source.duration,
            review_status="passed",
        )
        db.add(output)
        db.commit()
        db.refresh(output)
        return output

    if stub_llm:
        monkeypatch.setattr(llm, "_call_llm_with_messages", fake_call_llm_with_messages)
    monkeypatch.setattr(ffmpeg, "_render_ffmpeg_output", fake_render_ffmpeg_output)


def wait_for_status(client: TestClient, job_id: str, status: str, timeout: float = 3.0) -> dict:
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        response = client.get(f"/api/jobs/{job_id}")
        response.raise_for_status()
        last = response.json()
        if last["status"] == status:
            return last
        time.sleep(0.05)
    raise AssertionError(f"job did not reach {status}: {last}")


def test_demo_loop_persists_workspace_uploads_job_logs_and_output(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch, pipeline_ready=True)
    install_successful_pipeline_stubs(monkeypatch)

    workspace = client.post("/api/workspaces", json={"name": "漫剧测试"}).json()
    listed = client.get("/api/workspaces").json()
    assert listed[0]["name"] == "漫剧测试"

    upload = client.post(
        f"/api/workspaces/{workspace['id']}/videos",
        data={"duration": "12.5", "width": "360", "height": "640", "probe_status": "browser"},
        files={"file": ("1.mp4", b"fake mp4 bytes", "video/mp4")},
    )
    assert upload.status_code == 200
    material = upload.json()
    assert material["filename"] == "1.mp4"
    assert material["duration"] == 12.5

    detail = client.get(f"/api/workspaces/{workspace['id']}").json()
    assert len(detail["materials"]) == 1

    templates = client.get("/api/templates").json()
    assert any(template["type"] == "clip" for template in templates)

    job_response = client.post(
        f"/api/workspaces/{workspace['id']}/jobs",
        json={
            "config": {
                "contentType": "高光",
                "durationRange": "30 秒",
                "outputCount": 1,
                "pace": "强反转",
                "targetPlatform": "通用",
                "aspectRatio": "9:16",
                "keepSuspense": True,
                "clipRule": "前5秒强反转",
                "reviewRule": "",
                "clipModel": "GLM-5.1",
                "reviewModel": "GLM-5.1",
                "whisperModel": "base",
                "dramaName": "",
                "fontColor": "#ffff00",
                "cornerEnabled": True,
                "endingEnabled": True,
            }
        },
    )
    assert job_response.status_code == 200
    job = job_response.json()
    assert job["input_snapshot"]["materials"][0]["id"] == material["id"]

    completed = wait_for_status(client, job["id"], "done")
    assert completed["progress"] == 100
    assert len(completed["outputs"]) == 1
    assert completed["explainability"]["summary"]["clip_count"] == 1
    assert completed["explainability"]["timeline"][0]["source"] == "1.mp4"
    assert completed["explainability"]["review_report"]["status"] == "passed"

    logs = client.get(f"/api/jobs/{job['id']}/logs?offset=0").json()
    assert logs["next_offset"] > 0
    assert any("任务完成" in line for line in logs["lines"])

    output = completed["outputs"][0]
    output_response = client.get(f"/api/jobs/{job['id']}/outputs/{output['id']}")
    assert output_response.status_code == 200
    assert output_response.content == b"fake mp4 bytes"

    feedback = client.post(
        f"/api/jobs/{job['id']}/outputs/{output['id']}/feedback",
        json={"status": "usable", "reason": "节奏符合预期"},
    )
    assert feedback.status_code == 200
    feedback_job = feedback.json()
    assert feedback_job["outputs"][0]["feedback_status"] == "usable"
    assert feedback_job["outputs"][0]["feedback_reason"] == "节奏符合预期"


def test_cancel_and_retry_create_separate_job(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch, pipeline_ready=True)
    install_successful_pipeline_stubs(monkeypatch)

    workspace = client.post("/api/workspaces", json={"name": "取消测试"}).json()
    client.post(
        f"/api/workspaces/{workspace['id']}/videos",
        files={"file": ("1.mp4", b"fake mp4 bytes", "video/mp4")},
    )
    job = client.post(f"/api/workspaces/{workspace['id']}/jobs", json={"config": {"clipRule": "test"}}).json()
    cancelled = client.post(f"/api/jobs/{job['id']}/cancel").json()
    assert cancelled["status"] == "cancelled"

    retried = client.post(f"/api/jobs/{job['id']}/retry").json()
    assert retried["id"] != job["id"]
    assert retried["source_job_id"] == job["id"]


def test_template_productivity_actions_and_storage_summary(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)

    created = client.post(
        "/api/templates",
        json={"name": "QA 模板", "type": "clip", "config": {"clipRule": "qa"}},
    ).json()
    used = client.post(f"/api/templates/{created['id']}/use").json()
    assert used["last_used_at"]

    defaulted = client.post(f"/api/templates/{created['id']}/default").json()
    assert defaulted["is_default"] is True

    duplicated = client.post(f"/api/templates/{created['id']}/duplicate").json()
    assert duplicated["id"] != created["id"]
    assert duplicated["name"].endswith("副本")

    summary = client.get("/api/storage/summary").json()
    assert summary["material_count"] == 0
    assert summary["output_count"] == 0
    assert summary["storage_bytes"] == 0

    pipeline = client.get("/api/pipeline/status").json()
    assert pipeline["mode"] == "real"
    assert pipeline["max_concurrent_jobs"] == 2
    assert "ffmpeg_available" in pipeline
    assert pipeline["task_ready"] is False
    assert "VIDEO_CUT_LLM_ENDPOINT" in pipeline["missing_env_vars"]
    assert "VIDEO_CUT_LLM_API_KEY" in pipeline["missing_env_vars"]
    assert "VIDEO_CUT_WHISPER_COMMAND" in pipeline["missing_env_vars"]
    assert pipeline["blocking_requirements"]

    models = client.get("/api/llm/models").json()
    assert models["models"] == []
    assert models["default_model"] == "GLM-5.1"
    assert models["source"] == "fallback"

    runtime = client.get("/api/settings/runtime").json()
    assert runtime["llm_timeout_seconds"] == 300
    updated = client.put("/api/settings/runtime", json={"llm_timeout_seconds": 120}).json()
    assert updated["llm_timeout_seconds"] == 120


def test_real_timeline_clip_plan_uses_multiple_materials(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)

    workspace = client.post("/api/workspaces", json={"name": "timeline"}).json()
    first = client.post(
        f"/api/workspaces/{workspace['id']}/videos",
        data={"duration": "60", "probe_status": "browser"},
        files={"file": ("first.mp4", b"first", "video/mp4")},
    ).json()
    second = client.post(
        f"/api/workspaces/{workspace['id']}/videos",
        data={"duration": "80", "probe_status": "browser"},
        files={"file": ("second.mp4", b"second", "video/mp4")},
    ).json()

    from app.database import SessionLocal
    from app.models import Job
    from app.pipeline.ffmpeg import _timeline_clips

    db = SessionLocal()
    try:
        job = Job(id="timelinejob", workspace_id=workspace["id"], input_snapshot_json="{}")
        db.add(job)
        db.commit()
        clips = _timeline_clips(
            db,
            job,
            {
                "timeline": [
                    {"material_id": first["id"], "start": 5, "end": 9},
                    {"material_id": second["id"], "start": 10, "duration": 6},
                ]
            },
            30,
        )
        assert [clip["material"].id for clip in clips] == [first["id"], second["id"]]
        assert [clip["duration"] for clip in clips] == [4.0, 6.0]
    finally:
        db.close()


def test_asr_runs_for_all_materials_and_reuses_workspace_cache(tmp_path, monkeypatch):
    counter = tmp_path / "asr_calls.txt"
    fake_asr = tmp_path / "fake_asr.py"
    fake_asr.write_text(
        """
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("input")
parser.add_argument("--output-file", required=True)
parser.add_argument("--material-id", required=True)
parser.add_argument("--fingerprint", required=True)
parser.add_argument("--model", default="base")
parser.add_argument("--seconds", type=float, default=12)
parser.add_argument("--language", default="zh")
args = parser.parse_args()

counter = Path(os.environ["FAKE_ASR_COUNTER"])
with counter.open("a", encoding="utf-8") as handle:
    handle.write(args.material_id + "\\n")

target = Path(args.output_file)
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps({
    "material_id": args.material_id,
    "fingerprint": args.fingerprint,
    "source": args.input,
    "model": args.model,
    "seconds": args.seconds,
    "language": args.language,
    "text": f"transcript for {args.material_id}",
    "segments": [{"start": 0, "end": 2, "text": f"line {args.material_id}"}],
}, ensure_ascii=False), encoding="utf-8")
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("FAKE_ASR_COUNTER", str(counter))
    monkeypatch.setenv(
        "VIDEO_CUT_WHISPER_COMMAND",
        f'{sys.executable} "{fake_asr}" "{{input}}" --output-file "{{output_file}}" --material-id {{material_id}} --fingerprint {{fingerprint}} --model {{model}} --seconds {{seconds}} --language {{language}}',
    )
    monkeypatch.setenv("VIDEO_CUT_ASR_CLIP_SECONDS", "7")
    fake_ffmpeg = tmp_path / "ffmpeg.exe"
    fake_ffmpeg.write_text("fake ffmpeg", encoding="utf-8")
    fake_ffprobe = tmp_path / "ffprobe.exe"
    fake_ffprobe.write_text("fake ffprobe", encoding="utf-8")
    monkeypatch.setenv("VIDEO_CUT_FFMPEG_PATH", str(fake_ffmpeg))
    monkeypatch.setenv("VIDEO_CUT_FFPROBE_PATH", str(fake_ffprobe))
    monkeypatch.setenv("VIDEO_CUT_LLM_ENDPOINT", "https://llm.example.test/chat/completions")
    monkeypatch.setenv("VIDEO_CUT_LLM_API_KEY", "test-key")
    client = make_client(tmp_path, monkeypatch, clear_pipeline_env=False)
    install_successful_pipeline_stubs(monkeypatch)

    workspace = client.post("/api/workspaces", json={"name": "asr cache"}).json()
    first = client.post(
        f"/api/workspaces/{workspace['id']}/videos",
        data={"duration": "20", "probe_status": "browser"},
        files={"file": ("first.mp4", b"same-first", "video/mp4")},
    ).json()
    second = client.post(
        f"/api/workspaces/{workspace['id']}/videos",
        data={"duration": "20", "probe_status": "browser"},
        files={"file": ("second.mp4", b"same-second", "video/mp4")},
    ).json()

    job = client.post(f"/api/workspaces/{workspace['id']}/jobs", json={"config": {"whisperModel": "base"}}).json()
    completed = wait_for_status(client, job["id"], "done")
    calls = counter.read_text(encoding="utf-8").splitlines()
    assert calls == [first["id"], second["id"]]
    bundle = completed["input_snapshot"]["asr_bundle"]["materials"]
    assert [item["material_id"] for item in bundle] == [first["id"], second["id"]]
    assert all(item["status"] == "done" for item in bundle)
    from app.prompts import build_llm_messages

    prompt_text = build_llm_messages(completed["input_snapshot"], "GLM-5.1")[1]["content"]
    assert f"transcript for {first['id']}" in prompt_text
    assert f"transcript for {second['id']}" in prompt_text

    detail = client.get(f"/api/workspaces/{workspace['id']}").json()
    assert [item["asr_status"] for item in detail["materials"]] == ["done", "done"]

    second_job = client.post(f"/api/workspaces/{workspace['id']}/jobs", json={"config": {"whisperModel": "base"}}).json()
    wait_for_status(client, second_job["id"], "done")
    assert counter.read_text(encoding="utf-8").splitlines() == calls

    third = client.post(
        f"/api/workspaces/{workspace['id']}/videos",
        data={"duration": "20", "probe_status": "browser"},
        files={"file": ("third.mp4", b"same-third", "video/mp4")},
    ).json()
    third_job = client.post(f"/api/workspaces/{workspace['id']}/jobs", json={"config": {"whisperModel": "base"}}).json()
    wait_for_status(client, third_job["id"], "done")
    assert counter.read_text(encoding="utf-8").splitlines() == [*calls, third["id"]]

    order = [third["id"], first["id"], second["id"]]
    response = client.patch(f"/api/workspaces/{workspace['id']}/videos/order", json={"material_ids": order})
    assert response.status_code == 200
    reordered_job = client.post(f"/api/workspaces/{workspace['id']}/jobs", json={"config": {"whisperModel": "base"}}).json()
    reordered = wait_for_status(client, reordered_job["id"], "done")
    assert counter.read_text(encoding="utf-8").splitlines() == [*calls, third["id"]]
    assert [item["material_id"] for item in reordered["input_snapshot"]["asr_bundle"]["materials"]] == order


def test_llm_request_uses_selected_clip_model(monkeypatch):
    monkeypatch.setenv("VIDEO_CUT_LLM_ENDPOINT", "https://llm.example.test/chat/completions")
    monkeypatch.setenv("VIDEO_CUT_LLM_API_KEY", "test-key")
    monkeypatch.setenv("VIDEO_CUT_LLM_MODEL", "env-default")

    captured: dict[str, str] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": "{}"}}]}).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = request.data.decode("utf-8")
        return FakeResponse()

    from app.pipeline.llm import _call_llm
    from app.settings import get_pipeline_settings

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    _call_llm({"config": {"clipModel": "user-selected-model", "reviewModel": "review-selected-model"}}, get_pipeline_settings())

    payload = json.loads(captured["body"])
    assert captured["url"] == "https://llm.example.test/chat/completions"
    assert payload["model"] == "user-selected-model"


def test_llm_url_normalization_modes():
    from app.llm_models import normalize_llm_urls

    standard = normalize_llm_urls("api.example.test")
    assert standard.chat_completions_url == "https://api.example.test/v1/chat/completions"
    assert standard.model_urls[0] == "https://api.example.test/v1/models"
    assert standard.mode == "auto_v1"

    no_v1 = normalize_llm_urls("https://api.example.test/custom/")
    assert no_v1.chat_completions_url == "https://api.example.test/custom/chat/completions"
    assert no_v1.model_urls[0] == "https://api.example.test/custom/models"
    assert no_v1.mode == "slash_no_v1"

    explicit_v1 = normalize_llm_urls("https://api.example.test/custom/v1/")
    assert explicit_v1.chat_completions_url == "https://api.example.test/custom/v1/chat/completions"
    assert explicit_v1.model_urls[0] == "https://api.example.test/custom/v1/models"

    full_chat = normalize_llm_urls("https://api.example.test/custom/v1/chat/completions/")
    assert full_chat.chat_completions_url == "https://api.example.test/custom/v1/chat/completions"
    assert full_chat.model_urls[0] == "https://api.example.test/custom/v1/models"

    exact = normalize_llm_urls("https://api.example.test/private/generate?api-version=1#")
    assert exact.chat_completions_url == "https://api.example.test/private/generate?api-version=1"
    assert exact.model_urls == ["https://api.example.test/private/generate?api-version=1"]
    assert exact.mode == "exact"


def test_llm_request_uses_normalized_chat_url(monkeypatch):
    monkeypatch.setenv("VIDEO_CUT_LLM_ENDPOINT", "https://llm.example.test/provider")
    monkeypatch.setenv("VIDEO_CUT_LLM_API_KEY", "test-key")

    captured: dict[str, str] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": "{}"}}]}).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        return FakeResponse()

    from app.pipeline.llm import _call_llm_with_messages
    from app.settings import get_pipeline_settings

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    _call_llm_with_messages([{"role": "user", "content": "test"}], get_pipeline_settings(), model="model")

    assert captured["url"] == "https://llm.example.test/provider/v1/chat/completions"


def test_llm_request_exact_hash_url(monkeypatch):
    monkeypatch.setenv("VIDEO_CUT_LLM_ENDPOINT", "https://llm.example.test/private/generate#")
    monkeypatch.setenv("VIDEO_CUT_LLM_API_KEY", "test-key")

    captured: dict[str, str] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": "{}"}}]}).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        return FakeResponse()

    from app.pipeline.llm import _call_llm_with_messages
    from app.settings import get_pipeline_settings

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    _call_llm_with_messages([{"role": "user", "content": "test"}], get_pipeline_settings(), model="model")

    assert captured["url"] == "https://llm.example.test/private/generate"


def test_llm_request_can_use_selected_review_model(monkeypatch):
    monkeypatch.setenv("VIDEO_CUT_LLM_ENDPOINT", "https://llm.example.test/chat/completions")
    monkeypatch.setenv("VIDEO_CUT_LLM_API_KEY", "test-key")
    monkeypatch.setenv("VIDEO_CUT_LLM_MODEL", "env-default")

    captured: dict[str, str] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": "{}"}}]}).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["body"] = request.data.decode("utf-8")
        return FakeResponse()

    from app.pipeline.llm import _call_llm_with_messages
    from app.settings import get_pipeline_settings

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    _call_llm_with_messages([{"role": "user", "content": "review"}], get_pipeline_settings(), model="review-selected-model")

    payload = json.loads(captured["body"])
    assert payload["model"] == "review-selected-model"


def test_cancel_running_llm_analysis_releases_worker(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch, pipeline_ready=True)
    install_successful_pipeline_stubs(monkeypatch, stub_llm=False)
    monkeypatch.setenv("VIDEO_CUT_MAX_CONCURRENT_JOBS", "1")

    from app.pipeline import llm

    entered = threading.Event()
    release = threading.Event()
    lock = threading.Lock()
    call_count = 0

    def fake_send_json_request(request, timeout):
        nonlocal call_count
        with lock:
            call_count += 1
        entered.set()
        release.wait(3)
        payload = {
            "summary": {"title": "Cancelable cut", "clip_count": 1, "estimated_duration": 2},
            "timeline": [{"source": "1.mp4", "start": 0, "end": 2, "duration": 2}],
            "review_report": {"status": "passed", "risk_level": "low", "items": []},
        }
        return {"choices": [{"message": {"content": json.dumps(payload)}}]}

    monkeypatch.setattr(llm, "_send_json_request", fake_send_json_request)

    workspace = client.post("/api/workspaces", json={"name": "cancel analysis"}).json()
    client.post(
        f"/api/workspaces/{workspace['id']}/videos",
        data={"duration": "30", "probe_status": "browser"},
        files={"file": ("1.mp4", b"fake mp4 bytes", "video/mp4")},
    )

    first = client.post(f"/api/workspaces/{workspace['id']}/jobs", json={"config": {"clipRule": "first"}}).json()
    assert entered.wait(2)
    cancelled = client.post(f"/api/jobs/{first['id']}/cancel").json()
    assert cancelled["status"] == "cancelled"

    second = client.post(f"/api/workspaces/{workspace['id']}/jobs", json={"config": {"clipRule": "second"}}).json()
    deadline = time.time() + 2
    while time.time() < deadline:
        with lock:
            calls = call_count
        if calls >= 2:
            break
        time.sleep(0.05)
    with lock:
        assert call_count >= 2

    release.set()
    completed = wait_for_status(client, second["id"], "done", timeout=4)
    assert completed["status"] == "done"


def test_refine_prompt_uses_original_explainability_from_refine_request():
    from app.prompts import build_refine_messages

    messages = build_refine_messages(
        "adjust",
        {
            "config": {
                "durationRange": "1-3 分钟",
                "clipModel": "custom-clip-model",
            },
            "materials": [],
            "refine_request": {
                "original_explainability": {
                    "summary": {"title": "Previous Plan", "estimated_duration": 120},
                    "timeline": [
                        {"source": "ep1.mp4", "start": 1, "end": 18, "duration": 17},
                        {"source": "ep2.mp4", "start": 2, "end": 22, "duration": 20},
                        {"source": "ep3.mp4", "start": 3, "end": 25, "duration": 22},
                        {"source": "ep4.mp4", "start": 4, "end": 24, "duration": 20},
                    ],
                }
            },
        },
        "keep the previous pacing",
    )

    user_prompt = messages[-1]["content"]
    assert "Previous Plan" in user_prompt
    assert "1-3 分钟" in user_prompt
    assert "custom-clip-model" in user_prompt
