"""Assisted login: opens a VISIBLE browser, the human logs in (OTP/CAPTCHA included) and the
resulting storage_state is saved encrypted. This code only pre-fills the saved email/password; it never solves or
bypasses CAPTCHAs/bot checks.

Run as:  python -m app.workers.assisted_login <account_id>
It must run on a machine with a display (your own PC)."""

import logging
import sys
import time
from collections.abc import Callable

from app.core.sites import SITES
from app.services.accounts import (
    LOGIN_TIMEOUT_S,
    get_password,
    get_storage_state,
    has_login_cookie,
)

log = logging.getLogger("assisted_login")
POLL_S = 2.0


def capture_session(
    context,
    page,
    site: str,
    *,
    timeout_s: float = LOGIN_TIMEOUT_S,
    poll_s: float = POLL_S,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict | None:
    """Poll the context until the user is logged in, closes the window, or time runs out.
    Returns the last storage_state snapshot (or None if the browser was closed before any)."""
    deadline = clock() + timeout_s
    last: dict | None = None
    while clock() < deadline:
        try:
            if page.is_closed():
                break
            last = context.storage_state()
        except Exception:  # browser/context was closed by the user
            break
        if has_login_cookie(site, last) and SITES[site].session_cookie:
            sleep(3)  # let the post-login redirects finish writing cookies
            try:
                last = context.storage_state()
            except Exception:
                pass
            break
        sleep(poll_s)
    return last


_STEALTH_ARGS = ["--disable-blink-features=AutomationControlled", "--start-maximized"]


def _launch_visible(pw):
    """Prefer the user's installed Chrome/Edge: Naukri's bot protection often stalls the login
    in Playwright's bundled Chromium. Falls back to bundled Chromium."""
    for channel in ("chrome", "msedge"):
        try:
            return pw.chromium.launch(
                headless=False,
                channel=channel,
                args=_STEALTH_ARGS,
                ignore_default_args=["--enable-automation"],
            )
        except Exception as e:
            log.info("channel %s unavailable: %s", channel, e)
    return pw.chromium.launch(
        headless=False, args=_STEALTH_ARGS, ignore_default_args=["--enable-automation"]
    )


# site -> (email field, password field, submit button); only Naukri is pre-filled for now
_FORMS = {
    "naukri": (
        "input[placeholder*='Email ID'], input#usernameField",
        "input[type='password'], input#passwordField",
        "button[type='submit']:has-text('Login'), button:has-text('Login'):not(:has-text('Use OTP'))",
    ),
}


def prefill_login(page, site: str, email: str | None, password: str | None) -> None:
    """Type the saved email/password into the login form and submit. OTP/CAPTCHA are left to the
    human in the visible window."""
    form = _FORMS.get(site)
    if not form or not email:
        return
    email_sel, pw_sel, btn_sel = form
    try:
        page.wait_for_selector(email_sel, state="visible", timeout=30_000)
        page.click(email_sel)
        page.keyboard.type(email, delay=60)
        if password:
            page.click(pw_sel)
            page.keyboard.type(password, delay=60)
            page.wait_for_timeout(500)
            page.locator(btn_sel).last.click()
    except Exception as e:  # user can still type manually
        log.warning("could not pre-fill login form: %s", e)


def run(account_id: int) -> int:
    from playwright.sync_api import sync_playwright

    from app.core.db import SessionLocal
    from app.models import SiteAccount
    from app.services.accounts import save_storage_state

    with SessionLocal() as db:
        acct = db.get(SiteAccount, account_id)
        if acct is None:
            log.error("account %s not found", account_id)
            return 2
        info = SITES[acct.site]
        existing = get_storage_state(acct)
        with sync_playwright() as pw:
            browser = _launch_visible(pw)
            ctx_kwargs = {"no_viewport": True, "locale": "en-IN"}
            if existing:
                ctx_kwargs["storage_state"] = existing
            context = browser.new_context(**ctx_kwargs)
            page = context.new_page()
            try:
                # don't block on the load event: Naukri keeps loading trackers for a long time
                page.goto(info.login_url, wait_until="commit", timeout=60_000)
            except Exception as e:  # page stays open; the user can still navigate/login manually
                log.warning("initial navigation problem: %s", e)
            prefill_login(page, acct.site, acct.login_email, get_password(acct))
            log.info(
                "Browser opened for %s - log in, then it closes automatically "
                "(company sites: close the window when done).",
                acct.label,
            )
            state = capture_session(context, page, acct.site)
            try:
                browser.close()
            except Exception:
                pass
        if state is None:
            acct.status, acct.status_note = "needs_login", "Browser closed before login"
            db.commit()
            return 1
        save_storage_state(db, acct, state, mark_login=True)
        log.info("session saved for account %s (status=%s)", acct.id, acct.status)
        return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(run(int(sys.argv[1])))
