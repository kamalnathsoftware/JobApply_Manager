from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, optional_llm
from app.core.db import get_db
from app.models import Resume, User
from app.schemas.resume import ParsedResume, ResumeOut, ResumeUpdate
from app.services import resume_service
from app.services.llm import LLMClient
from app.services.resume_text import MAX_BYTES, UnsupportedResume

router = APIRouter(prefix="/resumes", tags=["resumes"])


def _out(r: Resume) -> ResumeOut:
    return ResumeOut(
        id=r.id,
        label=r.label,
        original_filename=r.original_filename,
        mime_type=r.mime_type,
        is_default=r.is_default,
        status=r.status,
        parse_error=r.parse_error,
        created_at=r.created_at,
        profile=ParsedResume.model_validate(r.profile.data) if r.profile else None,
        profile_edited=bool(r.profile and r.profile.user_edited),
    )


def _get(db: Session, user: User, resume_id: int) -> Resume:
    r = db.get(Resume, resume_id)
    if r is None or r.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resume not found")
    return r


@router.post("", response_model=ResumeOut, status_code=status.HTTP_201_CREATED)
def upload(
    file: UploadFile = File(...),
    label: str | None = Form(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    llm: LLMClient | None = Depends(optional_llm),
) -> ResumeOut:
    data = file.file.read(MAX_BYTES + 1)
    try:
        r = resume_service.create_resume(db, user.id, file.filename or "resume", data, label, llm)
    except (UnsupportedResume, ValueError) as e:
        raise HTTPException(422, str(e)) from e
    if r.status == "uploaded":
        r.status, r.parse_error = "parse_failed", "ANTHROPIC_API_KEY is not configured"
        db.commit()
    return _out(r)


@router.get("", response_model=list[ResumeOut])
def list_resumes(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(
        select(Resume).where(Resume.user_id == user.id).order_by(Resume.created_at.desc())
    )
    return [_out(r) for r in rows]


@router.get("/{resume_id}", response_model=ResumeOut)
def get_resume(resume_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return _out(_get(db, user, resume_id))


@router.patch("/{resume_id}", response_model=ResumeOut)
def rename(
    resume_id: int,
    body: ResumeUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    r = _get(db, user, resume_id)
    if body.label:
        r.label = body.label
    db.commit()
    return _out(r)


@router.put("/{resume_id}/profile", response_model=ResumeOut)
def edit_profile(
    resume_id: int,
    body: ParsedResume,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    r = _get(db, user, resume_id)
    resume_service.save_profile(db, r, body, edited=True)
    db.commit()
    return _out(r)


@router.post("/{resume_id}/reparse", response_model=ResumeOut)
def reparse(
    resume_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    llm: LLMClient | None = Depends(optional_llm),
):
    r = _get(db, user, resume_id)
    if llm is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "ANTHROPIC_API_KEY is not set")
    if r.profile:
        r.profile.user_edited = False  # explicit re-parse overwrites manual edits
    return _out(resume_service.parse_resume(db, r, llm))


@router.post("/{resume_id}/default", response_model=ResumeOut)
def make_default(resume_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    r = _get(db, user, resume_id)
    resume_service.set_default(db, r)
    return _out(r)


@router.get("/{resume_id}/file")
def download(resume_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    r = _get(db, user, resume_id)
    return FileResponse(r.stored_path, media_type=r.mime_type, filename=r.original_filename)


@router.delete("/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(resume_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    r = _get(db, user, resume_id)
    was_default, uid, path = r.is_default, r.user_id, r.stored_path
    db.delete(r)
    db.commit()
    Path(path).unlink(missing_ok=True)
    if was_default:
        nxt = db.scalar(select(Resume).where(Resume.user_id == uid).order_by(Resume.id))
        if nxt:
            nxt.is_default = True
            db.commit()
