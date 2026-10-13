from fastapi import APIRouter, Depends

from app.api.deps import current_user
from app.models import User
from app.services.llm import llm_info

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/info")
def info(_: User = Depends(current_user)) -> dict:
    return {"llm": llm_info()}
