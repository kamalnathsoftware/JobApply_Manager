"""Executes schedule runs: search -> dedupe -> score -> (dry_run | queue | apply)."""

import logging
import threading
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.base import (
    ApplyContext,
    ApplyStatus,
    JobPosting,
    NeedsHuman,
    SearchCriteria,
    SiteAdapter,
)
from app.adapters.humanize import Humanizer
from app.models import (
    AnswerBankEntry,
    Application,
    ApplicationLog,
    Job,
    Resume,
    Schedule,
    ScheduleRun,
    SearchProfile,
    SiteAccount,
)
from app.services import personal
from app.services.answers import BankEntry, QuestionResolver
from app.services.llm import LLMClient, LLMError
from app.services.matching import score_job
from app.services.scheduling import effective_cap, remaining_quota

log = logging.getLogger(__name__)

# Blocks that make continuing on the same account pointless/unsafe.
STOP_KINDS = {"captcha", "login", "account_creation"}
NO_SESSION_SITES = {"company"}

_account_locks: dict[int, threading.Lock] = defaultdict(threading.Lock)


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@dataclass
class RunDeps:
    session_factory: Callable[[], Session]
    open_adapter: Callable[[int], AbstractContextManager[SiteAdapter]]
    llm: LLMClient | None
    humanizer_factory: Callable[[], Humanizer]
    screenshot_root: Path
    apply_gap: tuple[float, float] = (20.0, 60.0)
    llm_factory: Callable[[int], LLMClient] | None = None  # per-user LLM (Settings → AI providers)

    def llm_for(self, user_id: int) -> LLMClient:
        if self.llm_factory is not None:
            return self.llm_factory(user_id)
        if self.llm is None:
            raise LLMError("No LLM provider is configured")
        return self.llm

    def try_llm_for(self, user_id: int) -> LLMClient | None:
        try:
            return self.llm_for(user_id)
        except LLMError:
            return None


@dataclass
class Counts:
    found: int = 0
    queued: int = 0
    applied: int = 0
    skipped: int = 0
    failed: int = 0
    needs_human: int = 0
    error: str | None = None
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        d = {
            k: getattr(self, k)
            for k in ("found", "queued", "applied", "skipped", "failed", "needs_human")
        }
        if self.error:
            d["error"] = self.error
        return d


# ------------------------------------------------------------------------------ logging
def write_log(
    db: Session,
    msg: str,
    *,
    run_id: int | None = None,
    app_id: int | None = None,
    level: str = "info",
    shot: str | None = None,
    err: str | None = None,
) -> None:
    db.add(
        ApplicationLog(
            schedule_run_id=run_id,
            application_id=app_id,
            level=level,
            message=msg[:4000],
            screenshot_path=shot,
            error_text=(err or None) and err[:4000],
        )
    )
    db.commit()


# --------------------------------------------------------------------------- helpers
def build_resolver(db: Session, user_id: int, profile: dict) -> QuestionResolver:
    entries = db.scalars(select(AnswerBankEntry).where(AnswerBankEntry.user_id == user_id))
    bank = [BankEntry(list(e.patterns), e.answer) for e in entries]
    # explicit answer-bank entries win; personal details fill in what the bank does not cover
    return QuestionResolver(
        profile=profile, bank=bank + personal.entries(personal.load(db, user_id))
    )


def bank_dicts(resolver: QuestionResolver) -> list[dict]:
    return [{"patterns": b.patterns, "answer": b.answer} for b in resolver.bank if not b.sensitive]


def job_to_posting(job: Job) -> JobPosting:
    return JobPosting(
        site=job.site,
        external_id=job.external_id,
        url=job.url,
        title=job.title,
        company=job.company,
        location=job.location,
        description=job.description,
        salary=job.salary,
        experience=job.experience,
        posted=job.posted,
        apply_type=job.apply_type,
    )


def upsert_job(db: Session, user_id: int, p: JobPosting) -> Job:
    job = db.scalar(
        select(Job).where(
            Job.user_id == user_id, Job.site == p.site, Job.external_id == p.external_id
        )
    )
    if job is None:
        job = Job(user_id=user_id, site=p.site, external_id=p.external_id)
        db.add(job)
    job.url = p.url[:1000]
    job.title = p.title[:500]
    for attr in ("company", "location", "salary", "experience", "posted"):
        v = getattr(p, attr)
        if v:
            setattr(job, attr, v[:255])
    if p.description and len(p.description) > len(job.description or ""):
        job.description = p.description
    if p.apply_type != "unknown":
        job.apply_type = p.apply_type
    db.commit()
    return job


def resolve_resume_profile(db: Session, acct: SiteAccount) -> tuple[Resume | None, dict | None]:
    resume = db.get(Resume, acct.resume_id) if acct.resume_id else None
    if resume is None:
        resume = db.scalar(select(Resume).where(Resume.user_id == acct.user_id, Resume.is_default))
    if resume is None or resume.profile is None:
        return resume, None
    return resume, resume.profile.data


def criteria_from(sp: SearchProfile) -> SearchCriteria:
    return SearchCriteria(
        keywords=list(sp.keywords or []),
        location=sp.location,
        experience_min=sp.experience_min,
        experience_max=sp.experience_max,
        salary_min=sp.salary_min,
        job_type=sp.job_type,
        posted_within_days=sp.posted_within_days,
        excluded_companies=list(sp.excluded_companies or []),
        company_urls=list(sp.company_urls or []),
        max_results=sp.max_results or 25,
    )


# ------------------------------------------------------------------- apply one application
def apply_one(
    db: Session,
    deps: RunDeps,
    adapter: SiteAdapter,
    app: Application,
    job: Job,
    ctx: ApplyContext,
    run_id: int | None,
    counts: Counts,
) -> bool:
    """Attempt to apply. Returns True if the account should stop (captcha/login wall)."""
    app.attempts += 1
    app.needs_human_kind = app.pending_question = None
    shot_name = f"app{app.id}_try{app.attempts}"
    stop = False
    try:
        res = adapter.apply(job_to_posting(job), ctx)
        if res.status == ApplyStatus.APPLIED:
            app.status, app.applied_at, app.status_note = "applied", utcnow(), res.message or None
            counts.applied += 1
        elif res.status == ApplyStatus.ALREADY_APPLIED:
            app.status, app.status_note = "skipped", "already applied on the site"
            counts.skipped += 1
        elif res.status == ApplyStatus.SKIPPED:
            app.status, app.status_note = "skipped", res.message or "skipped by adapter"
            counts.skipped += 1
        else:
            app.status, app.status_note = "failed", res.message
            counts.failed += 1
        write_log(
            db,
            f"{app.status}: {job.title} @ {job.company}",
            run_id=run_id,
            app_id=app.id,
            shot=res.screenshot_path,
            level="info" if app.status != "failed" else "error",
            err=res.message if app.status == "failed" else None,
        )
    except NeedsHuman as e:
        app.status, app.needs_human_kind = "needs_human", e.kind
        app.status_note = str(e)[:1000]
        if e.kind in ("unknown_question", "unknown_field"):
            app.pending_question = e.detail
        shot = adapter.screenshot(deps.screenshot_root / "needs_human", shot_name)
        counts.needs_human += 1
        # one company site's captcha/login says nothing about the next company site
        stop = e.kind in STOP_KINDS and job.site != "company"
        write_log(
            db,
            f"needs human ({e.kind}): {job.title} @ {job.company}",
            run_id=run_id,
            app_id=app.id,
            level="warn",
            shot=shot,
            err=e.detail,
        )
    except Exception as e:  # noqa: BLE001 - one bad job must not kill the run
        app.status, app.status_note = "failed", f"{type(e).__name__}: {e}"[:1000]
        shot = adapter.screenshot(deps.screenshot_root / "errors", shot_name)
        counts.failed += 1
        write_log(
            db,
            f"failed: {job.title} @ {job.company}",
            run_id=run_id,
            app_id=app.id,
            level="error",
            shot=shot,
            err=app.status_note,
        )
    db.commit()
    return stop


# --------------------------------------------------------------------- per-account run
def run_account(deps: RunDeps, run_id: int, account_id: int) -> Counts:
    counts = Counts()
    with deps.session_factory() as db:
        run = db.get(ScheduleRun, run_id)
        schedule = db.get(Schedule, run.schedule_id)
        acct = db.get(SiteAccount, account_id)
        sp = db.get(SearchProfile, schedule.search_profile_id)
        tag = f"[{acct.site}:{acct.label}]"

        def say(msg, level="info", **kw):
            write_log(db, f"{tag} {msg}", run_id=run_id, level=level, **kw)

        if acct.status == "disabled":
            say("account disabled - skipped")
            return counts
        if sp.sites and acct.site not in sp.sites:
            say(f"search profile '{sp.name}' does not include {acct.site} - skipped")
            return counts
        if acct.site not in NO_SESSION_SITES and not acct.storage_state_enc:
            acct.status, acct.status_note = "needs_login", "No saved session"
            db.commit()
            say("no saved session - use 'Log in' on the Accounts page first", "error")
            counts.error = "no saved session"
            return counts
        _, profile = resolve_resume_profile(db, acct)
        if profile is None:
            say("no parsed resume available for this account", "error")
            counts.error = "no parsed resume"
            return counts

        with _account_locks[account_id]:
            try:
                _run_account_locked(deps, db, run, schedule, acct, sp, profile, counts, say)
            except NeedsHuman as e:
                _mark_account_blocked(db, acct, e)
                say(f"stopped: {e}", "warn")
            except Exception as e:  # noqa: BLE001
                log.exception("account run failed")
                counts.error = f"{type(e).__name__}: {e}"[:500]
                say(f"run failed: {counts.error}", "error")
    return counts


def _mark_account_blocked(db: Session, acct: SiteAccount, e: NeedsHuman) -> None:
    acct.status = "needs_login" if e.kind == "login" else "needs_human"
    acct.status_note = str(e)[:500]
    db.commit()


def _run_account_locked(deps, db, run, schedule, acct, sp, profile, counts, say) -> None:
    mode, threshold = schedule.mode, schedule.match_threshold
    h = deps.humanizer_factory()
    resume, _ = resolve_resume_profile(db, acct)
    resolver = build_resolver(db, acct.user_id, profile)
    quota = remaining_quota(db, acct, schedule, schedule.timezone)
    say(f"starting ({mode}); daily quota left: {quota}/{effective_cap(acct, schedule)}")
    ctx = ApplyContext(
        profile=profile,
        resume_path=resume.stored_path if resume else "",
        resolver=resolver,
        screenshot_dir=deps.screenshot_root / f"run_{run.id}" / f"acct_{acct.id}",
        llm=deps.try_llm_for(acct.user_id),
        bank=bank_dicts(resolver),
    )
    with deps.open_adapter(acct.id) as adapter:
        postings = adapter.search(criteria_from(sp))
        say(f"search returned {len(postings)} jobs")
        for p in postings:
            job = upsert_job(db, acct.user_id, p)
            app = db.scalar(
                select(Application).where(
                    Application.account_id == acct.id, Application.job_id == job.id
                )
            )
            if app is None:
                if db.scalar(
                    select(Application.id).where(
                        Application.user_id == acct.user_id,
                        Application.job_id == job.id,
                        Application.status == "applied",
                    )
                ):
                    continue  # already applied via another account
                app = Application(user_id=acct.user_id, job_id=job.id, account_id=acct.id)
                db.add(app)
            elif app.status not in ("found",):
                continue  # already handled in an earlier run
            app.schedule_run_id = run.id
            db.commit()
            if p.already_applied:
                app.status, app.status_note = "skipped", "already applied on the site"
                counts.skipped += 1
                db.commit()
                continue

            if app.score is None:
                if not job.description or len(job.description) < 200:
                    try:
                        full = adapter.get_job(job.url)
                        job = upsert_job(db, acct.user_id, full)
                        if full.already_applied:
                            app.status, app.status_note = "skipped", "already applied on the site"
                            counts.skipped += 1
                            db.commit()
                            continue
                    except NeedsHuman:
                        raise
                    except Exception as e:  # noqa: BLE001
                        say(f"could not load details for '{job.title}': {e}", "warn")
                try:
                    m = score_job(
                        deps.llm_for(acct.user_id),
                        profile,
                        {
                            "title": job.title,
                            "company": job.company,
                            "location": job.location,
                            "experience": job.experience,
                            "salary": job.salary,
                            "description": job.description,
                        },
                    )
                except LLMError as e:
                    say(f"scoring failed for '{job.title}': {e}", "error")
                    counts.error = counts.error or f"scoring: {e}"
                    continue
                app.score, app.score_reasoning = m.score, m.reasoning
                db.commit()
                say(f"scored {m.score}: {job.title} @ {job.company}")

            if app.score < threshold:
                app.status, app.status_note = (
                    "skipped",
                    f"score {app.score} below threshold {threshold}",
                )
                counts.skipped += 1
                db.commit()
                continue
            if mode == "dry_run":
                counts.found += 1
                continue
            if mode == "review":
                app.status = "queued"
                counts.queued += 1
                db.commit()
                continue
            # auto
            if quota <= 0:
                app.status, app.status_note = (
                    "queued",
                    "daily cap reached - will apply once approved",
                )
                counts.queued += 1
                db.commit()
                continue
            stop = apply_one(db, deps, adapter, app, job, ctx, run.id, counts)
            if app.status == "applied":
                quota -= 1
            if stop:
                raise NeedsHuman(app.needs_human_kind or "other", app.status_note or "")
            h.pause(*deps.apply_gap)
    say(f"done: {counts.as_dict()}")


# ------------------------------------------------------------------------- whole run
def execute_run(deps: RunDeps, run_id: int) -> None:
    with deps.session_factory() as db:
        run = db.get(ScheduleRun, run_id)
        if run is None:
            return
        schedule = db.get(Schedule, run.schedule_id)
        run.status, run.started_at = "running", utcnow()
        db.commit()
        accounts = [
            a
            for a in db.scalars(
                select(SiteAccount).where(
                    SiteAccount.user_id == run.user_id,
                    SiteAccount.id.in_(schedule.account_ids or []),
                )
            )
        ]
        write_log(
            db,
            f"run #{run.id} started: {schedule.name} ({schedule.mode}) on "
            f"{len(accounts)} account(s)",
            run_id=run.id,
        )
        ids = [a.id for a in accounts]
        workers = max(1, min(schedule.max_concurrency or 1, len(ids) or 1))

    results: dict[int, Counts] = {}
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="acct") as pool:
        futures = {i: pool.submit(run_account, deps, run_id, i) for i in ids}
        for i, f in futures.items():
            try:
                results[i] = f.result()
            except Exception as e:  # noqa: BLE001
                results[i] = Counts(error=f"{type(e).__name__}: {e}"[:500])

    with deps.session_factory() as db:
        run = db.get(ScheduleRun, run_id)
        total = Counts()
        for c in results.values():
            for k in ("found", "queued", "applied", "skipped", "failed", "needs_human"):
                setattr(total, k, getattr(total, k) + getattr(c, k))
        errors = [c.error for c in results.values() if c.error]
        run.summary = total.as_dict() | {
            "accounts": {str(i): c.as_dict() for i, c in results.items()}
        }
        run.status = "failed" if ids and len(errors) == len(ids) else "completed"
        run.error = "; ".join(errors)[:1000] if errors else None
        run.finished_at = utcnow()
        db.commit()
        write_log(db, f"run #{run.id} {run.status}: {total.as_dict()}", run_id=run.id)


# --------------------------------------------------------- approved (review queue) items
def process_approved(deps: RunDeps) -> int:
    """Apply queued applications the user approved. Returns number attempted."""
    attempted = 0
    with deps.session_factory() as db:
        acct_ids = sorted(
            set(
                db.scalars(
                    select(Application.account_id).where(
                        Application.status == "queued", Application.approved.is_(True)
                    )
                )
            )
        )
    for acct_id in acct_ids:
        with _account_locks[acct_id], deps.session_factory() as db:
            acct = db.get(SiteAccount, acct_id)
            if acct is None or acct.status == "disabled":
                continue
            apps = list(
                db.scalars(
                    select(Application)
                    .where(
                        Application.account_id == acct_id,
                        Application.status == "queued",
                        Application.approved.is_(True),
                    )
                    .order_by(Application.id)
                )
            )
            resume, profile = resolve_resume_profile(db, acct)
            if not apps or profile is None:
                continue
            run = db.get(ScheduleRun, apps[0].schedule_run_id) if apps[0].schedule_run_id else None
            schedule = db.get(Schedule, run.schedule_id) if run else None
            tz = schedule.timezone if schedule else "UTC"
            quota = remaining_quota(db, acct, schedule, tz)
            if quota <= 0:
                continue
            counts, h = Counts(), deps.humanizer_factory()
            ctx = ApplyContext(
                profile=profile,
                resume_path=resume.stored_path if resume else "",
                resolver=build_resolver(db, acct.user_id, profile),
                screenshot_dir=deps.screenshot_root / "approved" / f"acct_{acct.id}",
                llm=deps.try_llm_for(acct.user_id),
                bank=bank_dicts(build_resolver(db, acct.user_id, profile)),
            )
            try:
                with deps.open_adapter(acct_id) as adapter:
                    for app in apps[:quota]:
                        job = db.get(Job, app.job_id)
                        attempted += 1
                        stop = apply_one(
                            db, deps, adapter, app, job, ctx, app.schedule_run_id, counts
                        )
                        if stop:
                            _mark_account_blocked(
                                db,
                                acct,
                                NeedsHuman(app.needs_human_kind or "other", app.status_note or ""),
                            )
                            break
                        h.pause(*deps.apply_gap)
            except Exception as e:  # noqa: BLE001
                log.exception("approved processing failed for account %s", acct_id)
                write_log(db, f"approved-queue run failed: {e}", level="error", err=str(e))
    return attempted
