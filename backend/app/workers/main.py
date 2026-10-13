"""Worker process: persists cron jobs in MySQL (APScheduler), turns due schedules and
'Run now' requests into runs, and executes them with bounded parallelism.

Run on your own machine:  python -m app.workers.main"""

import logging
import signal
import threading
from concurrent.futures import ThreadPoolExecutor

from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import Schedule, ScheduleRun
from app.services.runner import utcnow
from app.services.scheduling import ScheduleError, build_trigger, next_fire
from app.workers import jobs

log = logging.getLogger("worker")
MAX_PARALLEL_RUNS = 2
JOB_PREFIX = "schedule-"


def sync_schedules(scheduler, session_factory=SessionLocal) -> None:
    """Make APScheduler's job set mirror the enabled rows in `schedules`."""
    with session_factory() as db:
        wanted = {}
        for sch in db.scalars(select(Schedule).where(Schedule.enabled.is_(True))):
            try:
                wanted[f"{JOB_PREFIX}{sch.id}"] = (
                    sch,
                    build_trigger(sch.kind, sch.time_of_day, sch.cron_expr, sch.timezone),
                )
            except ScheduleError as e:
                log.warning("schedule %s has an invalid trigger: %s", sch.id, e)
        existing = {j.id: j for j in scheduler.get_jobs() if j.id.startswith(JOB_PREFIX)}
        for job_id in set(existing) - set(wanted):
            scheduler.remove_job(job_id)
        for job_id, (sch, trigger) in wanted.items():
            old = existing.get(job_id)
            if old is None or str(old.trigger) != str(trigger):
                scheduler.add_job(
                    jobs.enqueue_run,
                    trigger=trigger,
                    args=[sch.id],
                    id=job_id,
                    replace_existing=True,
                    coalesce=True,
                    misfire_grace_time=3600,
                    max_instances=1,
                )
            try:
                nxt = next_fire(sch)
            except ScheduleError:
                nxt = None
            if sch.next_run_at != nxt:
                sch.next_run_at = nxt
        db.commit()


def recover_interrupted_runs(session_factory=SessionLocal) -> None:
    """Runs left 'running' by a crashed worker would otherwise stay stuck forever."""
    with session_factory() as db:
        db.execute(
            update(ScheduleRun)
            .where(ScheduleRun.status == "running")
            .values(status="failed", error="worker restarted while running", finished_at=utcnow())
        )
        db.commit()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    recover_interrupted_runs()
    pool = ThreadPoolExecutor(max_workers=MAX_PARALLEL_RUNS, thread_name_prefix="run")
    in_flight = threading.BoundedSemaphore(MAX_PARALLEL_RUNS)

    def poll_runs() -> None:
        while in_flight.acquire(blocking=False):
            rid = jobs.claim_pending_run()
            if rid is None:
                in_flight.release()
                return

            def go(r=rid):
                try:
                    jobs.run_claimed(r)
                finally:
                    in_flight.release()

            pool.submit(go)

    scheduler = BlockingScheduler(
        jobstores={
            # cron schedules survive restarts; the housekeeping tickers are in-memory closures
            "default": SQLAlchemyJobStore(
                url=get_settings().database_url, tablename="apscheduler_jobs"
            ),
            "memory": MemoryJobStore(),
        },
        job_defaults={"coalesce": True, "misfire_grace_time": 3600},
    )
    scheduler.add_job(
        lambda: sync_schedules(scheduler),
        "interval",
        seconds=30,
        id="sync",
        replace_existing=True,
        jobstore="memory",
        next_run_time=utcnow(),
    )
    scheduler.add_job(
        poll_runs, "interval", seconds=5, id="poll_runs", replace_existing=True, jobstore="memory"
    )
    scheduler.add_job(
        jobs.approved_queue_tick,
        "interval",
        seconds=60,
        id="approved_queue",
        replace_existing=True,
        max_instances=1,
        jobstore="memory",
    )
    signal.signal(signal.SIGTERM, lambda *_: scheduler.shutdown(wait=False))
    log.info("worker started")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    main()
