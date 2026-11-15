"""Job pipelines (filled in by the next milestone)."""
from __future__ import annotations

from .media import UserError
from .worker import JobContext, manager


def run_vod(ctx: JobContext) -> None:
    for st in ("downloading", "chat", "transcribing", "scoring", "rendering"):
        ctx.stage(st, f"{st}…")
    raise UserError("Pipeline not implemented yet.")


def run_live(ctx: JobContext) -> None:
    raise UserError("Live mode not implemented yet.")


def housekeeping() -> None:
    pass


manager.configure(run_vod, run_live)
