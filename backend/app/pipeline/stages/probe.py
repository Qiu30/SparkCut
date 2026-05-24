from __future__ import annotations

from ..engine import PipelineContext
from ...db_helpers import add_log
from ...settings import ffprobe_path
from ...utils import json_loads


def _probe_stage(ctx) -> None:
    db, job = ctx.db, ctx.job
    snapshot = json_loads(job.input_snapshot_json)
    materials = snapshot.get("materials", [])
    add_log(db, job, f"[Pipeline] 输入素材 {len(materials) if isinstance(materials, list) else 0} 个\n")
    add_log(
        db,
        job,
        f"[Pipeline] ffprobe {'可用' if ffprobe_path() else '不可用'}，"
        "v0.4 会优先使用上传时保存的 metadata\n",
    )
