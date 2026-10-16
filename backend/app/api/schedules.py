import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, current_user_sse
from app.core.db import get_db, get_session_factory
from app.models import ApplicationLog, Schedule, ScheduleRun, SearchProfile, SiteAccount, User
from app.schemas.schedule import LogOut, RunOut, ScheduleIn, ScheduleOut
from app.services.scheduling import ScheduleError, next_fire

router = APIRouter(tags=["schedules"])


def _get_schedule(db: Session, user: User, sid: int) -> Schedule:
    s = db.get(Schedule, sid)
    if s is None or s.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Schedule not found")
    return s


def _validate(db: Session, user: User, body: ScheduleIn) -> None:
    sp = db.get(SearchProfile, body.search_profile_id)
    if sp is None or sp.user_id != user.id:
        raise HTTPException(422, "Unknown search profile")
    owned = set(db.scalars(select(SiteAccount.id).where(SiteAccount.user_id == user.id)))
    if not set(body.account_ids) <= owned:
        raise HTTPException(422, "Unknown account in account_ids")
    probe = Schedule(**body.model_dump())
    try:
        next_fire(probe)
    except ScheduleError as e:
        raise HTTPException(422, str(e)) from e


def _log_out(r: ApplicationLog) -> LogOut:
    return LogOut(
        id=r.id,
        application_id=r.application_id,
        schedule_run_id=r.schedule_run_id,
        level=r.level,
        message=r.message,
        has_screenshot=bool(r.screenshot_path),
        error_text=r.error_text,
        created_at=r.created_at,
    )


@router.get("/schedules", response_model=list[ScheduleOut])
def list_schedules(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return db.scalars(select(Schedule).where(Schedule.user_id == user.id).order_by(Schedule.id))


@router.post("/schedules", response_model=ScheduleOut, status_code=201)
def create(body: ScheduleIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    _validate(db, user, body)
    s = Schedule(user_id=user.id, **body.model_dump())
    s.next_run_at = next_fire(s) if s.enabled else None
    db.add(s)
    db.commit()
    return s


@router.put("/schedules/{sid}", response_model=ScheduleOut)
def update(
    sid: int, body: ScheduleIn, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    s = _get_schedule(db, user, sid)
    _validate(db, user, body)
    for k, v in body.model_dump().items():
        setattr(s, k, v)
    s.next_run_at = next_fire(s) if s.enabled else None
    db.commit()
    return s


@router.delete("/schedules/{sid}", status_code=204)
def delete(sid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    db.delete(_get_schedule(db, user, sid))
    db.commit()


@router.post("/schedules/{sid}/run", response_model=RunOut, status_code=202)
def run_now(sid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Queue a run; the worker process picks it up within a few seconds."""
    s = _get_schedule(db, user, sid)
    active = db.scalar(
        select(ScheduleRun.id).where(
            ScheduleRun.schedule_id == s.id, ScheduleRun.status.in_(["pending", "running"])
        )
    )
    if active:
        raise HTTPException(status.HTTP_409_CONFLICT, "This schedule already has a run in progress")
    run = ScheduleRun(schedule_id=s.id, user_id=user.id, trigger="manual")
    db.add(run)
    db.commit()
    return run


@router.get("/runs", response_model=list[RunOut])
def list_runs(
    schedule_id: int | None = None,
    limit: int = Query(30, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    q = select(ScheduleRun).where(ScheduleRun.user_id == user.id)
    if schedule_id:
        q = q.where(ScheduleRun.schedule_id == schedule_id)
    return db.scalars(q.order_by(ScheduleRun.id.desc()).limit(limit))


def _get_run(db: Session, user: User, rid: int) -> ScheduleRun:
    r = db.get(ScheduleRun, rid)
    if r is None or r.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    return r


@router.post("/runs/{rid}/cancel", response_model=RunOut)
def cancel_run(rid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Cancel a run the worker has not started yet (e.g. the worker was not running)."""
    r = _get_run(db, user, rid)
    if r.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only pending runs can be cancelled")
    r.status, r.error, r.finished_at = (
        "failed",
        "cancelled by user",
        datetime.now(UTC).replace(tzinfo=None),
    )
    db.commit()
    return r


@router.get("/runs/{rid}", response_model=RunOut)
def get_run(rid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return _get_run(db, user, rid)


@router.get("/runs/{rid}/logs", response_model=list[LogOut])
def run_logs(
    rid: int, after: int = 0, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    _get_run(db, user, rid)
    rows = db.scalars(
        select(ApplicationLog)
        .where(ApplicationLog.schedule_run_id == rid, ApplicationLog.id > after)
        .order_by(ApplicationLog.id)
        .limit(500)
    )
    return [_log_out(r) for r in rows]


@router.get("/runs/{rid}/events")
async def run_events(
    rid: int,
    request: Request,
    user: User = Depends(current_user_sse),
    session_factory=Depends(get_session_factory),
):
    """Server-Sent Events: streams new log lines until the run finishes."""
    with session_factory() as db:
        _get_run(db, user, rid)

    def fetch(last: int) -> tuple[list[dict], str]:
        with session_factory() as db:
            rows = db.scalars(
                select(ApplicationLog)
                .where(ApplicationLog.schedule_run_id == rid, ApplicationLog.id > last)
                .order_by(ApplicationLog.id)
                .limit(200)
            )
            out = [_log_out(r).model_dump(mode="json") for r in rows]
            return out, db.get(ScheduleRun, rid).status

    async def gen() -> AsyncIterator[str]:
        last = 0
        idle_after_done = 0
        while not await request.is_disconnected():
            rows, run_status = await asyncio.to_thread(fetch, last)
            for r in rows:
                last = r["id"]
                yield f"id: {last}\nevent: log\ndata: {json.dumps(r)}\n\n"
            if run_status in ("completed", "failed") and not rows:
                idle_after_done += 1
                if idle_after_done >= 2:
                    yield f"event: end\ndata: {json.dumps({'status': run_status})}\n\n"
                    return
            else:
                idle_after_done = 0
            yield ": keep-alive\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/logs/{log_id}/screenshot")
def screenshot(log_id: int, db: Session = Depends(get_db), user: User = Depends(current_user_sse)):
    row = db.get(ApplicationLog, log_id)
    owner = None
    if row is not None:
        if row.schedule_run_id:
            run = db.get(ScheduleRun, row.schedule_run_id)
            owner = run.user_id if run else None
        elif row.application_id:
            from app.models import Application

            app = db.get(Application, row.application_id)
            owner = app.user_id if app else None
    if row is None or not row.screenshot_path or owner != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Screenshot not found")
    from pathlib import Path

    if not Path(row.screenshot_path).is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Screenshot file is gone")
    return FileResponse(row.screenshot_path, media_type="image/png")
