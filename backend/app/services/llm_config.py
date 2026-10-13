"""Resolves which LLM(s) a user gets: the providers saved in the UI (encrypted keys in the DB),
or -- when the user has saved none -- the .env settings."""

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import CryptoError, decrypt
from app.models import LLMProviderSetting
from app.services.llm import LLMClient, LLMError, ProviderConfig, build_llm, env_chain


def user_rows(db: Session, user_id: int) -> list[LLMProviderSetting]:
    return list(
        db.scalars(
            select(LLMProviderSetting)
            .where(LLMProviderSetting.user_id == user_id)
            .order_by(LLMProviderSetting.priority, LLMProviderSetting.id)
        )
    )


def row_key(row: LLMProviderSetting) -> str:
    if not row.api_key_enc:
        return ""
    try:
        return decrypt(row.api_key_enc)
    except CryptoError:
        return ""


def user_configs(db: Session, user_id: int) -> list[ProviderConfig]:
    rows = user_rows(db, user_id)
    if not rows:
        return env_chain()
    return [
        ProviderConfig(r.provider, row_key(r), r.model or "", r.base_url or "")
        for r in rows
        if r.enabled
    ]


def llm_for_user(db: Session, user_id: int) -> LLMClient:
    configs = user_configs(db, user_id)
    if not configs:
        raise LLMError("No LLM provider is enabled - enable one in Settings → AI providers")
    return build_llm(configs)


def llm_factory(session_factory: Callable[[], Session]) -> Callable[[int], LLMClient]:
    """For the worker: resolve the LLM per call so Settings changes apply without a restart."""

    def make(user_id: int) -> LLMClient:
        with session_factory() as db:
            return llm_for_user(db, user_id)

    return make
