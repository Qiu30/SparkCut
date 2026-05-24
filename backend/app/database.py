from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = ROOT_DIR / "backend" / "data" / "app.db"
DEFAULT_STORAGE_DIR = ROOT_DIR / "storage"

DATABASE_URL = os.environ.get("VIDEO_CUT_DB_URL", f"sqlite:///{DEFAULT_DB_PATH}")
STORAGE_DIR = Path(os.environ.get("VIDEO_CUT_STORAGE_DIR", str(DEFAULT_STORAGE_DIR)))

if DATABASE_URL.startswith("sqlite:///"):
    db_file = Path(DATABASE_URL.replace("sqlite:///", "", 1))
    db_file.parent.mkdir(parents=True, exist_ok=True)

STORAGE_DIR.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
