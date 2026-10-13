from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import InvalidToken, decode_token
from app.models import User
from app.services.llm import LLMClient, LLMError, get_llm

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


def optional_llm() -> LLMClient | None:
    """None when no API key is configured, so uploads still work and can be parsed later."""
    try:
        return get_llm()
    except LLMError:
        return None
