import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.core.migrate import upgrade_to_head

log = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(_: FastAPI):
    if get_settings().auto_migrate:
        try:
            upgrade_to_head()
        except Exception:  # keep the API up; the log says what to fix
            log.exception("could not apply database migrations - run `alembic upgrade head`")
    yield


app = FastAPI(title="JobApply Manager", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix="/api")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
