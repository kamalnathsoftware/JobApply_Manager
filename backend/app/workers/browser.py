"""Playwright session management: one isolated browser context per account, seeded from the
encrypted storage_state and written back (encrypted) afterwards. Cookies never touch disk in
plain text."""

from collections.abc import Iterator
from contextlib import contextmanager

from app.adapters import get_adapter_class
from app.adapters.base import SiteAdapter
from app.adapters.humanize import Humanizer
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import SiteAccount
from app.services.accounts import get_storage_state, save_storage_state


@contextmanager
def open_adapter(account_id: int) -> Iterator[SiteAdapter]:
    from playwright.sync_api import sync_playwright

    s = get_settings()
    with SessionLocal() as db:
        acct = db.get(SiteAccount, account_id)
        site, state = acct.site, get_storage_state(acct)
    with sync_playwright() as pw:
        kwargs = {"headless": s.playwright_headless}
        if s.playwright_executable:
            kwargs["executable_path"] = s.playwright_executable
        browser = pw.chromium.launch(**kwargs)
        try:
            context = browser.new_context(
                storage_state=state, viewport={"width": 1366, "height": 850}, locale="en-IN"
            )
            context.set_default_timeout(20_000)
            page = context.new_page()
            try:
                adapter = get_adapter_class(site)(page, Humanizer())
                if not s.playwright_headless:  # a person can only help if they can see the window
                    adapter.human_wait_s = s.human_wait_seconds
                yield adapter
            finally:
                try:  # persist refreshed cookies
                    new_state = context.storage_state()
                    with SessionLocal() as db:
                        save_storage_state(
                            db, db.get(SiteAccount, account_id), new_state, mark_login=False
                        )
                except Exception:
                    pass
        finally:
            browser.close()
