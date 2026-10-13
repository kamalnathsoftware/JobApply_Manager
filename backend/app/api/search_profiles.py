from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.db import get_db
from app.models import SearchProfile, SiteAccount, User
from app.schemas.schedule import SearchProfileIn, SearchProfileOut

router = APIRouter(prefix="/search-profiles", tags=["search-profiles"])


def _get(db: Session, user: User, pid: int) -> SearchProfile:
    sp = db.get(SearchProfile, pid)
    if sp is None or sp.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Search profile not found")
    return sp


def _validate(db: Session, user: User, body: SearchProfileIn) -> None:
    if body.experience_min is not None and body.experience_max is not None:
        if body.experience_min > body.experience_max:
            raise HTTPException(422, "experience_min cannot exceed experience_max")
    if body.account_id is not None:
        a = db.get(SiteAccount, body.account_id)
        if a is None or a.user_id != user.id:
            raise HTTPException(422, "Unknown account")


@router.get("", response_model=list[SearchProfileOut])
def list_profiles(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return db.scalars(
        select(SearchProfile).where(SearchProfile.user_id == user.id).order_by(SearchProfile.id)
    )


@router.post("", response_model=SearchProfileOut, status_code=201)
def create(
    body: SearchProfileIn, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    _validate(db, user, body)
    sp = SearchProfile(user_id=user.id, **body.model_dump())
    db.add(sp)
    db.commit()
    return sp


@router.put("/{pid}", response_model=SearchProfileOut)
def update(
    pid: int,
    body: SearchProfileIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    sp = _get(db, user, pid)
    _validate(db, user, body)
    for k, v in body.model_dump().items():
        setattr(sp, k, v)
    db.commit()
    return sp


@router.delete("/{pid}", status_code=204)
def delete(pid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    db.delete(_get(db, user, pid))
    db.commit()
