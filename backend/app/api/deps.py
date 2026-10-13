from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import InvalidToken, decode_token
from app.models import User
from app.services.llm import LLMClient, LLMError
from app.services.llm_config import llm_for_user

bearer = HTTPBearer(auto_error=False)


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    unauth = HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    if creds is None:
        raise unauth
    try:
        uid = decode_token(creds.credentials, "access")
    except InvalidToken:
        raise unauth from None
    user = db.get(User, uid)
    if user is None or not user.is_active:
        raise unauth
    return user


def optional_llm(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> LLMClient | None:
    """None when no provider is usable, so uploads still work and can be parsed later."""
    try:
        return llm_for_user(db, user.id)
    except LLMError:
        return None


def current_user_sse(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    token: str | None = None,
    db: Session = Depends(get_db),
) -> User:
    """Like current_user, but also accepts ?token= because EventSource/<img> cannot send
    an Authorization header."""
    raw = creds.credentials if creds else token
    unauth = HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    if not raw:
        raise unauth
    try:
        uid = decode_token(raw, "access")
    except InvalidToken:
        raise unauth from None
    user = db.get(User, uid)
    if user is None or not user.is_active:
        raise unauth
    return user
