from __future__ import annotations

from ...db_helpers import add_log
from ...models import OutputVideo


def _package_stage(ctx, outputs: list[OutputVideo]) -> None:
    db, job = ctx.db, ctx.job
    if outputs:
        for output in outputs:
            add_log(db, job, f"[Pipeline] 输出文件就绪：{output.name}（{output.filename}）\n")
    else:
        add_log(db, job, "[Pipeline] 没有可预览 MP4 输出，保留任务日志和解释报告\n")
