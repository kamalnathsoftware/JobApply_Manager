from fastapi import APIRouter, Depends

from app.api.deps import current_user
from app.models import User
from app.services import worker_status
from app.services.llm import llm_info

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/info")
def info(_: User = Depends(current_user)) -> dict:
    return {"llm": llm_info()}


@router.get("/worker")
def worker(_: User = Depends(current_user)) -> dict:
    age = worker_status.heartbeat_age()
    return {"alive": worker_status.worker_alive(), "age_s": None if age is None else round(age)}


@router.post("/worker/start", status_code=202)
def start_worker(_: User = Depends(current_user)) -> dict:
    """Start the worker on this machine unless one is already running."""
    if worker_status.worker_alive():
        return {"alive": True, "started": False}
    worker_status.spawn_worker()
    return {"alive": False, "started": True}
