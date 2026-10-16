from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.db import get_db
from app.models import User
from app.schemas.personal import PersonalDetailsIn
from app.services import personal

router = APIRouter(prefix="/personal-details", tags=["personal-details"])


@router.get("", response_model=PersonalDetailsIn)
def get_details(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return personal.load(db, user.id)


@router.put("", response_model=PersonalDetailsIn)
def put_details(
    body: PersonalDetailsIn, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    return personal.save(db, user.id, body)
