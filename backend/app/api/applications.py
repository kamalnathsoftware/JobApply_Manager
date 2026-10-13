from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.api.schedules import _log_out
from app.core.db import get_db
from app.models import (
    AnswerBankEntry,
    Application,
    ApplicationLog,
    Job,
    Schedule,
    ScheduleRun,
    SiteAccount,
    User,
)
from app.schemas.applications import (
    AnswerIn,
    ApplicationDetail,
    ApplicationList,
    ApplicationOut,
    IdsIn,
    JobBrief,
)
from app.schemas.schedule import LogOut
from app.services.answers import normalize
from app.services.scheduling import applied_today, effective_cap

router = APIRouter(tags=["applications"])
VALID_STATUS = {"found", "queued", "applied", "failed", "needs_human", "skipped"}


def _out(app: Application, job: Job, label: str | None) -> ApplicationOut:
    data = {
        k: getattr(app, k) for k in ApplicationOut.model_fields if k not in ("job", "account_label")
    }
    return ApplicationOut(**data, job=JobBrief.model_validate(job), account_label=label)


def _get(db: Session, user: User, app_id: int) -> Application:
    a = db.get(Application, app_id)
    if a is None or a.user_id != user.id:
        raise HTTPException(404, "Application not found")
    return a


@router.get("/applications", response_model=ApplicationList)
def list_applications(
    status: str | None = Query(None, description="comma separated statuses"),
    site: str | None = None,
    account_id: int | None = None,
    q: str | None = None,
    min_score: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    cond = [Application.user_id == user.id]
    if status:
        wanted = [s for s in status.split(",") if s]
        if not set(wanted) <= VALID_STATUS:
            raise HTTPException(422, "Unknown status filter")
        cond.append(Application.status.in_(wanted))
    if site:
        cond.append(Job.site == site)
    if account_id:
        cond.append(Application.account_id == account_id)
    if min_score is not None:
        cond.append(Application.score >= min_score)
    if date_from:
        cond.append(Application.created_at >= date_from)
    if date_to:
        cond.append(Application.created_at <= date_to)
    if q:
        like = f"%{q.strip()}%"
        cond.append(or_(Job.title.like(like), Job.company.like(like)))
    base = (
        select(Application, Job, SiteAccount.label)
        .join(Job, Job.id == Application.job_id)
        .join(SiteAccount, SiteAccount.id == Application.account_id)
    )
    total = db.scalar(
        select(func.count())
        .select_from(Application)
        .join(Job, Job.id == Application.job_id)
        .where(*cond)
    )
    rows = db.execute(
        base.where(*cond).order_by(Application.id.desc()).limit(limit).offset(offset)
    ).all()
    return ApplicationList(total=total or 0, items=[_out(a, j, lbl) for a, j, lbl in rows])


@router.get("/applications/{app_id}", response_model=ApplicationDetail)
def detail(app_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    a = _get(db, user, app_id)
    job, acct = db.get(Job, a.job_id), db.get(SiteAccount, a.account_id)
    out = _out(a, job, acct.label if acct else None)
    return ApplicationDetail(**out.model_dump(), description=job.description)


@router.get("/applications/{app_id}/logs", response_model=list[LogOut])
def logs(app_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    _get(db, user, app_id)
    rows = db.scalars(
        select(ApplicationLog)
        .where(ApplicationLog.application_id == app_id)
        .order_by(ApplicationLog.id)
    )
    return [_log_out(r) for r in rows]


@router.post("/applications/approve")
def approve(body: IdsIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """One-click approval; the worker applies approved items (respecting daily caps)."""
    done = []
    for a in db.scalars(
        select(Application).where(
            Application.user_id == user.id,
            Application.id.in_(body.ids),
            Application.status == "queued",
        )
    ):
        a.approved = True
        done.append(a.id)
    db.commit()
    return {"approved": done}


@router.post("/applications/reject")
def reject(body: IdsIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    done = []
    for a in db.scalars(
        select(Application).where(
            Application.user_id == user.id,
            Application.id.in_(body.ids),
            Application.status.in_(["queued", "needs_human", "found", "failed"]),
        )
    ):
        a.status, a.approved, a.status_note = "skipped", False, "rejected by user"
        done.append(a.id)
    db.commit()
    return {"rejected": done}


@router.post("/applications/{app_id}/answer", response_model=ApplicationOut)
def answer(
    app_id: int, body: AnswerIn, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    """Provide the answer to an unknown screening question; the application is re-queued
    (pre-approved) and the answer optionally saved to the bank for next time."""
    a = _get(db, user, app_id)
    if a.status != "needs_human" or not a.pending_question:
        raise HTTPException(409, "This application is not waiting for an answer")
    if body.save_to_bank:
        pattern = normalize(a.pending_question)[:200]
        db.add(
            AnswerBankEntry(
                user_id=user.id,
                key="custom",
                label=a.pending_question[:255],
                patterns=[pattern],
                answer=body.answer,
            )
        )
    a.status, a.approved, a.pending_question, a.needs_human_kind = "queued", True, None, None
    a.status_note = "answer provided - will retry"
    db.commit()
    job, acct = db.get(Job, a.job_id), db.get(SiteAccount, a.account_id)
    return _out(a, job, acct.label if acct else None)


@router.post("/applications/{app_id}/retry", response_model=ApplicationOut)
def retry(app_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    a = _get(db, user, app_id)
    if a.status not in ("failed", "needs_human"):
        raise HTTPException(409, "Only failed or needs-human applications can be retried")
    a.status, a.approved, a.status_note = "queued", True, "retry requested"
    a.pending_question = a.needs_human_kind = None
    db.commit()
    job, acct = db.get(Job, a.job_id), db.get(SiteAccount, a.account_id)
    return _out(a, job, acct.label if acct else None)


@router.get("/dashboard/stats")
def stats(
    days: int = Query(14, ge=1, le=90),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    now = datetime.now(UTC).replace(tzinfo=None)
    since = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    by_status = dict(
        db.execute(
            select(Application.status, func.count())
            .where(Application.user_id == user.id)
            .group_by(Application.status)
        ).all()
    )
    applied_rows = db.execute(
        select(Job.site, func.date(Application.applied_at), func.count())
        .join(Job, Job.id == Application.job_id)
        .where(
            Application.user_id == user.id,
            Application.status == "applied",
            Application.applied_at >= since,
        )
        .group_by(Job.site, func.date(Application.applied_at))
    ).all()
    per_day: dict[str, dict[str, int]] = {}
    for site, day, n in applied_rows:
        per_day.setdefault(str(day), {})[site] = n
    series = []
    for i in range(days):
        d = (since + timedelta(days=i)).date().isoformat()
        series.append({"date": d, **per_day.get(d, {})})
    by_site = dict(
        db.execute(
            select(Job.site, func.count())
            .join(Application, Application.job_id == Job.id)
            .where(Application.user_id == user.id, Application.status == "applied")
            .group_by(Job.site)
        ).all()
    )
    accounts = []
    for a in db.scalars(
        select(SiteAccount).where(SiteAccount.user_id == user.id).order_by(SiteAccount.id)
    ):
        accounts.append(
            {
                "id": a.id,
                "site": a.site,
                "label": a.label,
                "status": a.status,
                "applied_today": applied_today(db, a.id, "UTC"),
                "cap": effective_cap(a, None),
            }
        )
    runs = db.scalars(
        select(ScheduleRun)
        .where(ScheduleRun.user_id == user.id)
        .order_by(ScheduleRun.id.desc())
        .limit(5)
    )
    sched_names = {
        s.id: s.name for s in db.scalars(select(Schedule).where(Schedule.user_id == user.id))
    }
    return {
        "by_status": by_status,
        "applied_by_site": by_site,
        "applied_per_day": series,
        "accounts": accounts,
        "recent_runs": [
            {
                "id": r.id,
                "schedule": sched_names.get(r.schedule_id),
                "status": r.status,
                "started_at": r.started_at,
                "summary": r.summary,
            }
            for r in runs
        ],
        "attention": {
            "awaiting_approval": by_status.get("queued", 0),
            "needs_human": by_status.get("needs_human", 0),
            "accounts_need_login": sum(
                a["status"] in ("needs_login", "needs_human") for a in accounts
            ),
        },
    }
