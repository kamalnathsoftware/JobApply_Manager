import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.db import get_db
from app.models import Resume, SiteAccount, User
from app.schemas.account import AccountCreate, AccountOut, AccountUpdate
from app.services import accounts as svc

router = APIRouter(prefix="/accounts", tags=["accounts"])


def _out(a: SiteAccount) -> AccountOut:
    return AccountOut(
        id=a.id,
        site=a.site,
        label=a.label,
        login_email=a.login_email,
        resume_id=a.resume_id,
        status=a.status,
        status_note=a.status_note,
        daily_cap=a.daily_cap,
        has_session=bool(a.storage_state_enc),
        has_password=bool(a.credentials_enc),
        last_login_at=a.last_login_at,
    )


def _get(db: Session, user: User, account_id: int) -> SiteAccount:
    a = db.get(SiteAccount, account_id)
    if a is None or a.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found")
    return a


def _check_resume(db: Session, user: User, resume_id: int | None) -> None:
    if resume_id is not None:
        r = db.get(Resume, resume_id)
        if r is None or r.user_id != user.id:
            raise HTTPException(422, "Unknown resume")


@router.post("", response_model=AccountOut, status_code=status.HTTP_201_CREATED)
def create(body: AccountCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    _check_resume(db, user, body.resume_id)
    a = SiteAccount(
        user_id=user.id,
        site=body.site,
        label=body.label,
        login_email=body.login_email,
        resume_id=body.resume_id,
        daily_cap=body.daily_cap,
    )
    svc.set_password(a, body.password)
    db.add(a)
    db.commit()
    return _out(a)


@router.get("", response_model=list[AccountOut])
def list_accounts(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(
        select(SiteAccount).where(SiteAccount.user_id == user.id).order_by(SiteAccount.id)
    )
    return [_out(a) for a in rows]


@router.patch("/{account_id}", response_model=AccountOut)
def update(
    account_id: int,
    body: AccountUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    a = _get(db, user, account_id)
    fields = body.model_dump(exclude_unset=True)
    if body.resume_id is not None:
        _check_resume(db, user, body.resume_id)
        a.resume_id = body.resume_id
    if body.clear_resume:
        a.resume_id = None
    for k in ("label", "login_email", "daily_cap"):
        if k in fields and fields[k] is not None:
            setattr(a, k, fields[k])
    if "password" in fields:
        svc.set_password(a, body.password)
    if body.status:
        a.status = body.status
    db.commit()
    return _out(a)


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(account_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    db.delete(_get(db, user, account_id))
    db.commit()


def _has_display() -> bool:
    return sys.platform != "linux" or bool(
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    )


def spawn_login_process(account_id: int) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "app.workers.assisted_login", str(account_id)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


@router.post("/{account_id}/login/start", response_model=AccountOut, status_code=202)
def start_login(account_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    a = _get(db, user, account_id)
    now = datetime.now(UTC).replace(tzinfo=None)
    in_progress = (
        a.status == "login_in_progress"
        and a.login_started_at is not None
        and now - a.login_started_at < timedelta(seconds=svc.LOGIN_TIMEOUT_S + 30)
    )
    if in_progress:
        raise HTTPException(status.HTTP_409_CONFLICT, "A login window is already open")
    if not _has_display():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "No display available. Assisted login needs a visible browser: run the backend "
            "on your own desktop machine (not inside Docker).",
        )
    a.status, a.login_started_at, a.status_note = "login_in_progress", now, None
    db.commit()
    try:
        spawn_login_process(a.id)
    except OSError as e:
        a.status, a.status_note = "needs_login", f"Could not start browser: {e}"[:500]
        db.commit()
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Could not start browser") from e
    return _out(a)


@router.post("/{account_id}/session/clear", response_model=AccountOut)
def clear_session(
    account_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    a = _get(db, user, account_id)
    svc.clear_session(db, a)
    return _out(a)
