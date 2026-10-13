"""Functions executed by the worker. Kept importable at module level so APScheduler can
persist references to them in MySQL."""

import logging
import random
from pathlib import Path

from sqlalchemy import select, update

from app.adapters.humanize import Humanizer
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import Schedule, ScheduleRun
from app.services.llm import get_llm
from app.services.runner import RunDeps, execute_run, process_approved, utcnow
from app.services.scheduling import next_fire
from app.workers.browser import open_adapter

log = logging.getLogger("worker")


def make_deps() -> RunDeps:
    s = get_settings()
    return RunDeps(
        session_factory=SessionLocal,
        open_adapter=open_adapter,
        llm=get_llm(),
        humanizer_factory=lambda: Humanizer(rng=random.Random()),
        screenshot_root=Path(s.storage_dir) / "screenshots",
        apply_gap=(s.apply_gap_min_s, s.apply_gap_max_s),
    )


def enqueue_run(schedule_id: int) -> None:
    """Called by APScheduler at the scheduled time: just records a pending run."""
    with SessionLocal() as db:
        sch = db.get(Schedule, schedule_id)
        if sch is None or not sch.enabled:
            return
        db.add(ScheduleRun(schedule_id=sch.id, user_id=sch.user_id, trigger="schedule"))
        try:
            sch.next_run_at = next_fire(sch)
        except Exception:
            pass
        db.commit()
        log.info("enqueued run for schedule %s", schedule_id)


def claim_pending_run(session_factory=SessionLocal) -> int | None:
    """Atomically move one pending run to 'running' and return its id."""
    with session_factory() as db:
        for rid in db.scalars(
            select(ScheduleRun.id)
            .where(ScheduleRun.status == "pending")
            .order_by(ScheduleRun.id)
            .limit(5)
        ):
            res = db.execute(
                update(ScheduleRun)
                .where(ScheduleRun.id == rid, ScheduleRun.status == "pending")
                .values(status="running", started_at=utcnow())
            )
            db.commit()
            if res.rowcount == 1:
                return rid
    return None


def run_claimed(run_id: int) -> None:
    try:
        execute_run(make_deps(), run_id)
    except Exception as e:
        log.exception("run %s crashed", run_id)
        with SessionLocal() as db:
            run = db.get(ScheduleRun, run_id)
            if run:
                run.status, run.error, run.finished_at = "failed", str(e)[:1000], utcnow()
                db.commit()


def approved_queue_tick() -> None:
    try:
        n = process_approved(make_deps())
        if n:
            log.info("processed %s approved applications", n)
    except Exception:
        log.exception("approved queue processing failed")
