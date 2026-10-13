from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.db import get_db
from app.models import AnswerBankEntry, User
from app.schemas.answer_bank import AnswerIn, AnswerOut
from app.services.answers import DEFAULT_BANK

router = APIRouter(prefix="/answer-bank", tags=["answer-bank"])


def _clean(body: AnswerIn) -> AnswerIn:
    body.patterns = [p.strip().lower() for p in body.patterns if p.strip()]
    if not body.patterns:
        raise HTTPException(422, "At least one non-empty pattern is required")
    return body


def _get(db: Session, user: User, entry_id: int) -> AnswerBankEntry:
    e = db.get(AnswerBankEntry, entry_id)
    if e is None or e.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entry not found")
    return e


@router.get("", response_model=list[AnswerOut])
def list_entries(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return db.scalars(select(AnswerBankEntry).where(AnswerBankEntry.user_id == user.id))


@router.get("/suggestions")
def suggestions(_: User = Depends(current_user)):
    return [{"key": k, "label": label, "patterns": p} for k, label, p in DEFAULT_BANK]


@router.post("", response_model=AnswerOut, status_code=status.HTTP_201_CREATED)
def create(body: AnswerIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    e = AnswerBankEntry(user_id=user.id, **_clean(body).model_dump())
    db.add(e)
    db.commit()
    return e


@router.put("/{entry_id}", response_model=AnswerOut)
def update(
    entry_id: int,
    body: AnswerIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    e = _get(db, user, entry_id)
    for k, v in _clean(body).model_dump().items():
        setattr(e, k, v)
    db.commit()
    return e


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(entry_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    db.delete(_get(db, user, entry_id))
    db.commit()
