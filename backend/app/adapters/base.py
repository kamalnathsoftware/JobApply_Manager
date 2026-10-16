"""Plugin interface every job-site adapter implements. Adapters only drive an already-open
Playwright `page` that carries the user's saved session; they never log in by themselves and
never try to defeat CAPTCHAs or bot checks (they raise NeedsHuman instead)."""

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from app.adapters.humanize import Humanizer
from app.services.answers import QuestionResolver

log = logging.getLogger(__name__)


class ApplyStatus(StrEnum):
    APPLIED = "applied"
    ALREADY_APPLIED = "already_applied"
    SKIPPED = "skipped"
    FAILED = "failed"


class NeedsHuman(Exception):
    """Raised when automation must stop: captcha, login wall, unknown question, etc."""

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = (
            kind  # captcha | login | unknown_question | unknown_field | account_creation | other
        )
        self.detail = detail


class AdapterError(Exception):
    pass


@dataclass
class SearchCriteria:
    keywords: list[str]
    location: str | None = None
    experience_min: int | None = None
    experience_max: int | None = None
    salary_min: int | None = None  # annual, in the site's currency
    job_type: str | None = None  # full_time | contract | internship ...
    posted_within_days: int | None = None
    excluded_companies: list[str] = field(default_factory=list)
    company_urls: list[str] = field(default_factory=list)  # company-site adapter only
    max_results: int = 25


@dataclass
class JobPosting:
    site: str
    external_id: str
    url: str
    title: str
    company: str | None = None
    location: str | None = None
    description: str | None = None
    salary: str | None = None
    experience: str | None = None
    posted: str | None = None
    apply_type: str = "unknown"  # easy | external | unknown
    already_applied: bool = False


@dataclass
class ApplyContext:
    profile: dict  # ParsedResume.model_dump()
    resume_path: str
    resolver: QuestionResolver
    screenshot_dir: Path
    llm: object | None = None  # LLMClient; used by the company-site adapter
    bank: list = field(default_factory=list)  # [{'patterns': [...], 'answer': '...'}] for mapping


@dataclass
class ApplyResult:
    status: ApplyStatus
    message: str = ""
    screenshot_path: str | None = None


class SiteAdapter(ABC):
    site: str = ""

    # How long to wait for a person to clear a CAPTCHA / bot check in the visible browser window
    # before giving up with NeedsHuman. 0 = do not wait (headless runs, tests).
    human_wait_s: float = 0
    human_poll_s: float = 3.0

    def __init__(self, page, humanizer: Humanizer | None = None):
        self.page = page
        self.h = humanizer or Humanizer()
        self._sleep = time.sleep

    # -- required interface ---------------------------------------------------------
    @abstractmethod
    def search(self, criteria: SearchCriteria) -> list[JobPosting]: ...

    @abstractmethod
    def get_job(self, url: str) -> JobPosting: ...

    @abstractmethod
    def apply(self, job: JobPosting, ctx: ApplyContext) -> ApplyResult: ...

    # -- shared helpers ---------------------------------------------------------------
    def screenshot(self, directory: Path, name: str) -> str | None:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"{name}.png"
            self.page.screenshot(path=str(path), full_page=True)
            return str(path)
        except Exception:
            return None

    def check_blocked(self) -> None:
        from app.adapters.guards import detect_block

        reason = detect_block(self.page)
        if reason and self.human_wait_s > 0:
            # Never solved automatically: the page stays open for YOU to complete it, then the
            # run carries on by itself.
            log.warning(
                "%s: %s - waiting up to %ds for you to complete it in the browser window",
                self.site,
                reason,
                self.human_wait_s,
            )
            waited = 0.0
            while reason and waited < self.human_wait_s:
                self._sleep(self.human_poll_s)
                waited += self.human_poll_s
                reason = detect_block(self.page)
            if not reason:
                log.info("%s: check cleared, continuing", self.site)
                self.h.pause(1.0, 2.0)
        if reason:
            raise NeedsHuman("captcha", reason)

    def goto(self, url: str) -> None:
        self.page.goto(url, wait_until="domcontentloaded")
        self.h.pause(0.8, 2.0)
        self.check_blocked()

    def apply_external(self, trigger, job: JobPosting, ctx: ApplyContext) -> ApplyResult:
        """Follow an 'Apply on company site' button to the employer's own page and complete the
        application there with the company-site form filler (same rules: never guesses, stops
        with NeedsHuman on logins / account creation / unknown questions / CAPTCHAs).

        `trigger` is the already-located button/link on the job board page."""
        from app.adapters.company_site import CompanySiteAdapter

        board_page = self.page
        context = board_page.context
        before = list(context.pages)
        board_url = board_page.url
        href = None
        try:
            href = trigger.get_attribute("href")
        except Exception:
            pass
        self.h.click(trigger)

        target = None
        for _ in range(16):  # up to ~8s for a new tab or a same-tab navigation
            new = [p for p in context.pages if p not in before]
            if new:
                target = new[-1]
                break
            if board_page.url != board_url:
                target = board_page
                break
            board_page.wait_for_timeout(500)
        if target is None:
            if not href or not href.startswith("http"):
                raise AdapterError("the company-site link did not open anything")
            target = board_page
            board_page.goto(href, wait_until="domcontentloaded")
        try:
            target.wait_for_load_state("domcontentloaded")
        except Exception:
            pass
        self.h.pause(1.0, 2.0)

        company = CompanySiteAdapter(target, self.h)
        company._sleep = self._sleep
        company.human_wait_s, company.human_poll_s = self.human_wait_s, self.human_poll_s
        ext = JobPosting(
            site=self.site,
            external_id=job.external_id,
            url=target.url,
            title=job.title,
            company=job.company,
            apply_type="external",
        )
        try:
            company.check_blocked()
            res = company.apply_current_page(ext, ctx)
        except NeedsHuman as e:
            # The block is on the employer's site, not on this job-board account, so it must not
            # stop the rest of the account's run (hence the external_ prefix).
            company.screenshot(
                ctx.screenshot_dir, f"{self.site}_{job.external_id}_external_{e.kind}"
            )
            raise NeedsHuman(f"external_{e.kind}", f"company site: {e.detail or e.kind}") from e
        finally:
            self.page = board_page
            for p in list(context.pages):
                if p not in before and p is not board_page and not p.is_closed():
                    p.close()
        if res.status == ApplyStatus.APPLIED:
            return ApplyResult(
                ApplyStatus.APPLIED,
                "applied on company site (external redirect)",
                res.screenshot_path,
            )
        return res

    def excluded(self, company: str | None, criteria: SearchCriteria) -> bool:
        c = (company or "").strip().lower()
        return bool(c) and any(
            x.strip().lower() == c for x in criteria.excluded_companies if x.strip()
        )
