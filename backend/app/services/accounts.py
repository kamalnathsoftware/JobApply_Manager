"""Account helpers. Cookies/passwords only ever touch the DB in encrypted form and are
never logged."""

import json
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.crypto import decrypt, encrypt
from app.core.sites import SITES
from app.models import SiteAccount

LOGIN_TIMEOUT_S = 600


def set_password(acct: SiteAccount, password: str | None) -> None:
    acct.credentials_enc = encrypt(json.dumps({"password": password})) if password else None


def get_password(acct: SiteAccount) -> str | None:
    if not acct.credentials_enc:
        return None
    return json.loads(decrypt(acct.credentials_enc)).get("password")


def get_storage_state(acct: SiteAccount) -> dict | None:
    if not acct.storage_state_enc:
        return None
    return json.loads(decrypt(acct.storage_state_enc))


def has_login_cookie(site: str, state: dict | None) -> bool:
    info = SITES[site]
    if not state or not state.get("cookies"):
        return False
    if info.session_cookie is None:  # company sites: any cookie counts as a saved session
        return True
    return any(
        c.get("name") == info.session_cookie
        and (info.cookie_domain or "") in (c.get("domain") or "")
        for c in state["cookies"]
    )


def save_storage_state(
    db: Session,
    acct: SiteAccount,
    state: dict,
    *,
    mark_login: bool,
    logged_in: bool = False,
) -> None:
    acct.storage_state_enc = encrypt(json.dumps(state))
    if mark_login:
        ok = logged_in or has_login_cookie(acct.site, state)
        acct.status = "active" if ok else "needs_login"
        acct.status_note = None if ok else "Login was not completed"
        if ok:
            acct.last_login_at = datetime.now(UTC).replace(tzinfo=None)
    db.commit()


def clear_session(db: Session, acct: SiteAccount) -> None:
    acct.storage_state_enc = None
    acct.status = "new"
    acct.status_note = None
    db.commit()
