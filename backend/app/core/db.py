from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_connect_args = (
    {"check_same_thread": False} if get_settings().database_url.startswith("sqlite") else {}
)
engine = create_engine(
    get_settings().database_url, pool_pre_ping=True, pool_recycle=3600, connect_args=_connect_args
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    with SessionLocal() as db:
        yield db


def get_session_factory():
    """Dependency returning a callable that opens a Session (overridable in tests)."""
    return SessionLocal
