from __future__ import annotations

import queue
import threading
from typing import Dict

from sqlalchemy.orm import Session

from .database import SessionLocal
from .models import Job
from .pipeline import PipelineCancelled, run_job_pipeline
from .services import add_log, utcnow
from .settings import get_pipeline_settings


_job_queue: "queue.Queue[str]" = queue.Queue()
_lock = threading.Lock()
_worker_count = 0
_active_jobs: set[str] = set()
_queued_jobs: set[str] = set()


def _is_cancelled(db: Session, job: Job) -> bool:
    db.refresh(job)
    return job.status == "cancelled"


def run_mock_job(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if not job or job.status == "cancelled":
            return
        job.status = "running"
        job.stage = "queued"
        job.progress = max(job.progress, 2)
        if not job.started_at:
            job.started_at = utcnow()
        db.commit()
        add_log(db, job, "[系统] 任务已启动\n")

        run_job_pipeline(db, job, lambda: _is_cancelled(db, job))

        if _is_cancelled(db, job):
            add_log(db, job, "[系统] 任务已取消\n")
            return
        job.status = "done"
        job.stage = "done"
        job.progress = 100
        job.completed_at = utcnow()
        db.commit()
        add_log(db, job, "[系统] 任务完成\n")
    except PipelineCancelled:
        job = db.get(Job, job_id)
        if job:
            add_log(db, job, "[系统] 任务已取消\n")
    except Exception as exc:  # pragma: no cover - defensive runtime guard
        job = db.get(Job, job_id)
        if job:
            job.status = "error"
            job.error_message = str(exc)
            job.completed_at = utcnow()
            db.commit()
            add_log(db, job, f"[错误] {exc}\n")
    finally:
        db.close()


def start_mock_job(job_id: str) -> None:
    _ensure_worker_pool()
    with _lock:
        if job_id in _active_jobs or job_id in _queued_jobs:
            return
        _queued_jobs.add(job_id)
    _job_queue.put(job_id)


def runner_status() -> Dict[str, int]:
    with _lock:
        return {
            "queue_depth": _job_queue.qsize(),
            "active_jobs": len(_active_jobs),
            "worker_count": _worker_count,
        }


def recover_incomplete_jobs(db: Session) -> int:
    settings = get_pipeline_settings()
    if not settings.recover_jobs:
        return 0
    jobs = db.query(Job).filter(Job.status.in_(["queued", "running"])).all()
    for job in jobs:
        if job.status == "running":
            job.status = "queued"
            job.stage = "queued"
            job.progress = 0
            job.started_at = None
            job.error_message = None
            add_log(db, job, "[系统] 检测到服务重启，任务已重新排队\n")
        start_mock_job(job.id)
    db.commit()
    return len(jobs)


def _ensure_worker_pool() -> None:
    global _worker_count
    settings = get_pipeline_settings()
    with _lock:
        while _worker_count < settings.max_concurrent_jobs:
            thread = threading.Thread(target=_worker_loop, daemon=True)
            thread.start()
            _worker_count += 1


def _worker_loop() -> None:
    while True:
        job_id = _job_queue.get()
        with _lock:
            _queued_jobs.discard(job_id)
            _active_jobs.add(job_id)
        try:
            run_mock_job(job_id)
        finally:
            with _lock:
                _active_jobs.discard(job_id)
            _job_queue.task_done()
