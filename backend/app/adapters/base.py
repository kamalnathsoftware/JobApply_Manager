"""Plugin interface every job-site adapter implements. Adapters only drive an already-open
Playwright `page` that carries the user's saved session; they never log in by themselves and
never try to defeat CAPTCHAs or bot checks (they raise NeedsHuman instead)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from app.adapters.humanize import Humanizer
from app.services.answers import QuestionResolver


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

    def __init__(self, page, humanizer: Humanizer | None = None):
        self.page = page
        self.h = humanizer or Humanizer()

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
        if reason:
            raise NeedsHuman("captcha", reason)

    def goto(self, url: str) -> None:
        self.page.goto(url, wait_until="domcontentloaded")
        self.h.pause(0.8, 2.0)
        self.check_blocked()

    def excluded(self, company: str | None, criteria: SearchCriteria) -> bool:
        c = (company or "").strip().lower()
        return bool(c) and any(
            x.strip().lower() == c for x in criteria.excluded_companies if x.strip()
        )
