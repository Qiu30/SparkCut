from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import get_db, init_db
from .routers import jobs, settings, templates, workspaces
from .settings import read_local_env_values
from .templates import seed_templates
from .worker import recover_incomplete_jobs


app = FastAPI(title="SparkCut API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(workspaces.router)
app.include_router(templates.router)
app.include_router(jobs.router)
app.include_router(settings.router)


@app.on_event("startup")
def on_startup() -> None:
    for key, value in read_local_env_values().items():
        os.environ.setdefault(key, value)
    init_db()
    db = next(get_db())
    try:
        seed_templates(db)
        recover_incomplete_jobs(db)
    finally:
        db.close()


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}
