from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.crypto import encrypt
from app.core.db import get_db
from app.models import LLMProviderSetting, User
from app.services import llm_config
from app.services.llm import (
    PROVIDERS,
    LLMError,
    ProviderConfig,
    build_single,
    default_model,
    env_chain,
    env_key,
    llm_info,
)

router = APIRouter(prefix="/llm", tags=["llm"])


class ProviderIn(BaseModel):
    provider: str
    enabled: bool = True
    priority: int = Field(default=0, ge=0, le=100)
    model: str | None = Field(default=None, max_length=100)
    base_url: str | None = Field(default=None, max_length=255)
    api_key: str | None = Field(default=None, max_length=500)  # None = keep, "" = remove


def _view(db: Session, user: User) -> dict:
    rows = {r.provider: r for r in llm_config.user_rows(db, user.id)}
    env_names = [c.provider for c in env_chain()]
    out = []
    for i, p in enumerate(PROVIDERS):
        r = rows.get(p)
        out.append(
            {
                "provider": p,
                "enabled": r.enabled if r else (p in env_names if not rows else False),
                "priority": r.priority if r else (env_names.index(p) if p in env_names else 10 + i),
                "model": (r.model if r and r.model else "") or "",
                "default_model": default_model(p),
                "base_url": (r.base_url if r else "") or "",
                "has_key": bool(r and r.api_key_enc),
                "env_key": bool(env_key(p)),
                "needs_key": p != "ollama",
            }
        )
    out.sort(key=lambda x: (not x["enabled"], x["priority"]))
    return {"providers": out, "source": "ui" if rows else "env", "env": llm_info()}


@router.get("/providers")
def get_providers(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return _view(db, user)


@router.put("/providers")
def save_providers(
    body: list[ProviderIn], db: Session = Depends(get_db), user: User = Depends(current_user)
):
    existing = {r.provider: r for r in llm_config.user_rows(db, user.id)}
    for item in body:
        if item.provider not in PROVIDERS:
            raise HTTPException(422, f"unknown provider {item.provider}")
        row = existing.get(item.provider)
        if row is None:
            row = LLMProviderSetting(user_id=user.id, provider=item.provider)
            db.add(row)
        row.enabled, row.priority = item.enabled, item.priority
        row.model = (item.model or "").strip() or None
        row.base_url = (item.base_url or "").strip() or None
        if item.api_key is not None:
            row.api_key_enc = encrypt(item.api_key.strip()) if item.api_key.strip() else None
    db.commit()
    return _view(db, user)


@router.delete("/providers")
def reset_to_env(db: Session = Depends(get_db), user: User = Depends(current_user)):
    for r in llm_config.user_rows(db, user.id):
        db.delete(r)
    db.commit()
    return _view(db, user)


@router.post("/test")
def test_provider(
    provider: str | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    """Send a tiny request to one provider (or the whole chain) and report the result."""
    try:
        if provider:
            row = next(
                (r for r in llm_config.user_rows(db, user.id) if r.provider == provider), None
            )
            cfg = (
                ProviderConfig(
                    provider, llm_config.row_key(row), row.model or "", row.base_url or ""
                )
                if row
                else ProviderConfig(provider)
            )
            client = build_single(cfg)
        else:
            client = llm_config.llm_for_user(db, user.id)
        out = client.complete_json('Return {"ok": true}.', "ping", max_tokens=50)
        used = getattr(client, "used", None) or provider
        return {"ok": True, "provider": used, "model": client.model, "reply": str(out)[:100]}
    except LLMError as e:
        return {"ok": False, "provider": provider, "error": str(e)[:500]}
