"""Assisted login: opens a VISIBLE browser, pre-fills the email/password you saved for the
account (if any) and submits them, then waits while YOU handle anything extra (OTP, CAPTCHA,
"is this you?" prompts). When login is detected the session (Playwright storage_state) is saved
encrypted. This code never solves or bypasses CAPTCHAs/bot checks: if one appears it leaves the
page for you.

Run as:  python -m app.workers.assisted_login <account_id>
It must run on a machine with a display (your own PC)."""

import logging
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass

from app.core.sites import SITES
from app.services.accounts import (
    LOGIN_TIMEOUT_S,
    get_password,
    get_storage_state,
    has_login_cookie,
)

log = logging.getLogger("assisted_login")
POLL_S = 2.0


def looks_logged_in(site: str, url: str) -> bool:
    """URL-based login signal (cookie names change; page URLs after login are stabler)."""
    pattern = SITES[site].logged_in_url
    return bool(pattern and re.search(pattern, url or ""))


@dataclass
class CaptureResult:
    state: dict | None
    logged_in: bool = False


def capture_session(
    context,
    page,
    site: str,
    *,
    timeout_s: float = LOGIN_TIMEOUT_S,
    poll_s: float = POLL_S,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> CaptureResult:
    """Poll until login is detected (cookie or post-login URL), the user closes the window, or
    time runs out. `state` is the last storage_state snapshot (None if closed before any)."""
    deadline = clock() + timeout_s
    last: dict | None = None
    logged_in = False
    while clock() < deadline:
        try:
            if page.is_closed():
                break
            last = context.storage_state()
            url = page.url
        except Exception:  # browser/context was closed by the user
            break
        has_cookie = has_login_cookie(site, last) and bool(SITES[site].session_cookie)
        if has_cookie or looks_logged_in(site, url):
            logged_in = True
            sleep(3)  # let the post-login redirects finish writing cookies
            try:
                last = context.storage_state()
            except Exception:
                pass
            break
        sleep(poll_s)
    return CaptureResult(last, logged_in)


def _first_visible(page, selectors: tuple[str, ...], timeout_ms: int = 8000):
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="visible", timeout=timeout_ms if sel == selectors[0] else 1500)
            return loc
        except Exception:
            continue
    return None


def prefill_login(
    page, site: str, email: str | None, password: str | None, *, submit: bool = True
) -> str:
    """Type the saved email/password into the site's login form (like you would) and press
    Login. Returns a short outcome for the log; never raises and never logs the values."""
    from app.adapters.guards import detect_block
    from app.adapters.humanize import Humanizer

    info = SITES[site]
    if not email or not info.user_selectors:
        return (
            "skipped: no saved email" if not email else "skipped: no form selectors for this site"
        )
    h = Humanizer()
    try:
        if detect_block(page):
            return "skipped: bot check on the page - please handle it yourself"
        user = _first_visible(page, info.user_selectors)
        if user is None:
            return "login form not found - log in manually"
        h.type_into(user, email)
        if password:
            pw = _first_visible(page, info.pass_selectors, timeout_ms=3000)
            if pw is not None:
                h.type_into(pw, password)
        if not submit:
            return "filled"
        btn = _first_visible(page, info.submit_selectors, timeout_ms=3000)
        if btn is None:
            return "filled - press Login yourself"
        h.pause(0.5, 1.2)
        btn.click()
        return "filled and submitted - complete any OTP/CAPTCHA in the window"
    except Exception as e:  # never break the manual path
        return f"auto-fill failed ({type(e).__name__}) - log in manually"


def run(account_id: int) -> int:
    from playwright.sync_api import sync_playwright

    from app.core.config import get_settings
    from app.core.db import SessionLocal
    from app.models import SiteAccount
    from app.services.accounts import save_storage_state

    with SessionLocal() as db:
        acct = db.get(SiteAccount, account_id)
        if acct is None:
            log.error("account %s not found", account_id)
            return 2
        info = SITES[acct.site]
        try:
            existing = get_storage_state(acct)
            password = get_password(acct)
            s = get_settings()
            with sync_playwright() as pw:
                kwargs = {"headless": False}
                if s.playwright_executable:
                    kwargs["executable_path"] = s.playwright_executable
                browser = pw.chromium.launch(**kwargs)
                context = (
                    browser.new_context(storage_state=existing)
                    if existing
                    else browser.new_context()
                )
                page = context.new_page()
                page.goto(info.login_url)
                log.info("Browser opened for '%s' (%s).", acct.label, acct.site)
                outcome = prefill_login(page, acct.site, acct.login_email, password)
                log.info("auto-fill: %s", outcome)
                result = capture_session(context, page, acct.site)
                try:
                    browser.close()
                except Exception:
                    pass
        except Exception as e:
            log.exception("assisted login crashed")
            hint = " Run 'playwright install chromium' once." if "xecutable" in str(e) else ""
            acct.status, acct.status_note = "needs_login", f"Login window failed: {e}"[:400] + hint
            db.commit()
            return 3
        if result.state is None:
            acct.status, acct.status_note = "needs_login", "Browser closed before login"
            db.commit()
            return 1
        save_storage_state(db, acct, result.state, mark_login=True, logged_in=result.logged_in)
        log.info("session saved for account %s (status=%s)", acct.id, acct.status)
        return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(run(int(sys.argv[1])))
