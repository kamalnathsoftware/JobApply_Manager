"""Turn a parsed resume into a ready-to-run search profile + schedule.

Deterministic on purpose (no LLM call): the title, experience and location come straight from
the parsed resume. The schedule defaults to `review` mode, so every match lands in the Review
Queue and nothing is submitted until the user approves it. Re-running is idempotent: it updates
the schedule's accounts but never overwrites a profile/schedule the user has edited."""

import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Resume, Schedule, SearchProfile, SiteAccount
from app.schemas.resume import ParsedResume
from app.services.scheduling import ScheduleError, next_fire

AUTO_PREFIX = "Auto: "
SEARCH_SITES = ("naukri", "linkedin", "indeed")  # company sites need explicit URLs
DEFAULT_TIME = "09:00"


@dataclass
class PlanResult:
    search_profile_id: int | None = None
    schedule_id: int | None = None
    created_profile: bool = False
    created_schedule: bool = False
    messages: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "search_profile_id": self.search_profile_id,
            "schedule_id": self.schedule_id,
            "created_profile": self.created_profile,
            "created_schedule": self.created_schedule,
            "message": " ".join(self.messages),
        }


def _clean_title(t: str) -> str:
    t = re.sub(r"\(.*?\)", "", t)  # "(Contract)" etc.
    t = re.split(r"\s[-|@–,]\s", t)[0]  # "QA Engineer - Payments" -> "QA Engineer"
    return " ".join(t.split())[:100]


def derive_keywords(p: ParsedResume) -> list[str]:
    cands = [p.current_title]
    cands += [e.title for e in p.experience[:2]]
    cands.append(p.headline)
    out: list[str] = []
    for c in cands:
        c = _clean_title(c or "")
        if c and c.lower() not in {x.lower() for x in out}:
            out.append(c)
        if out:
            break  # one role per search: the adapters AND the keywords into a single query
    if not out and p.skills:
        out = [" ".join(p.skills[:2])]
    return out


def derive_experience(years: float | None) -> tuple[int | None, int | None]:
    if years is None:
        return None, None
    y = int(years + 0.5)  # round half up (round() is banker's rounding)
    # Naukri's experience filter takes the candidate's own years and lists the jobs that accept it
    return max(0, y), y + 3


def _location(p: ParsedResume) -> str | None:
    loc = (p.contact.location or "").strip()
    return loc.split(",")[0].strip()[:255] or None if loc else None


def ensure_plan(
    db: Session,
    resume: Resume,
    *,
    timezone: str = "UTC",
    mode: str = "review",
    time_of_day: str = DEFAULT_TIME,
) -> PlanResult:
    res = PlanResult()
    if resume.profile is None:
        res.messages.append("Resume is not parsed yet, so nothing was planned.")
        return res
    parsed = ParsedResume.model_validate(resume.profile.data)
    keywords = derive_keywords(parsed)
    if not keywords:
        res.messages.append(
            "No job title or skills found in the resume - add a search profile manually."
        )
        return res

    name = f"{AUTO_PREFIX}{resume.label} (resume {resume.id})"[:255]
    sp = db.scalar(
        select(SearchProfile).where(
            SearchProfile.user_id == resume.user_id, SearchProfile.name == name
        )
    )
    if sp is None:
        lo, hi = derive_experience(parsed.total_experience_years)
        sp = SearchProfile(
            user_id=resume.user_id,
            name=name,
            keywords=keywords,
            location=_location(parsed),
            experience_min=lo,
            experience_max=hi,
            posted_within_days=7,
            sites=list(SEARCH_SITES),
            max_results=25,
        )
        db.add(sp)
        db.flush()
        res.created_profile = True
        res.messages.append(f"Created search profile for '{keywords[0]}'.")
    res.search_profile_id = sp.id

    accounts = list(
        db.scalars(
            select(SiteAccount).where(
                SiteAccount.user_id == resume.user_id, SiteAccount.site.in_(SEARCH_SITES)
            )
        )
    )
    # accounts bound to this resume, or with no resume of their own (they use the default one)
    ids = [a.id for a in accounts if a.resume_id in (None, resume.id)]
    sched = db.scalar(
        select(Schedule).where(
            Schedule.user_id == resume.user_id,
            Schedule.search_profile_id == sp.id,
            Schedule.name == name,
        )
    )
    if sched is None:
        if not ids:
            res.messages.append(
                "Add a site account (Accounts page) and click Auto-plan again to create the schedule."
            )
            db.commit()
            return res
        sched = Schedule(
            user_id=resume.user_id,
            name=name,
            search_profile_id=sp.id,
            account_ids=ids,
            mode=mode,
            kind="daily",
            time_of_day=time_of_day,
            timezone=timezone,
            match_threshold=60,
            enabled=True,
        )
        try:
            sched.next_run_at = next_fire(sched)
        except ScheduleError:
            sched.timezone = "UTC"
            sched.next_run_at = next_fire(sched)
        db.add(sched)
        db.flush()
        res.created_schedule = True
        res.messages.append(
            f"Scheduled daily at {time_of_day} in {mode} mode - matches wait in the Review Queue."
            if mode == "review"
            else f"Scheduled daily at {time_of_day} ({mode})."
        )
    else:
        merged = sorted(set(sched.account_ids or []) | set(ids))
        if merged != sorted(sched.account_ids or []):
            sched.account_ids = merged
            res.messages.append("Added new accounts to the existing schedule.")
    res.schedule_id = sched.id
    if not res.messages:
        res.messages.append("Already planned - nothing to change.")
    db.commit()
    return res
