from contextlib import nullcontext

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.adapters.base import (
    ApplyContext,
    ApplyResult,
    ApplyStatus,
    JobPosting,
    NeedsHuman,
    SearchCriteria,
    SiteAdapter,
)
from app.adapters.humanize import Humanizer
from app.core.crypto import encrypt
from app.models import (
    AnswerBankEntry,
    Application,
    ApplicationLog,
    Base,
    Resume,
    ResumeProfile,
    Schedule,
    ScheduleRun,
    SearchProfile,
    SiteAccount,
    User,
)
from app.services.runner import RunDeps, execute_run, process_approved
from tests.helpers import FakeLLM


class FakeAdapter(SiteAdapter):
    site = "naukri"

    def __init__(self, postings, outcomes=None, search_error=None):
        super().__init__(page=None, humanizer=Humanizer(scale=0))
        self.postings, self.outcomes, self.search_error = postings, outcomes or {}, search_error
        self.applied: list[str] = []
        self.searched = 0

    def search(self, criteria: SearchCriteria):
        self.searched += 1
        if self.search_error:
            raise self.search_error
        return list(self.postings)

    def get_job(self, url):
        return next(p for p in self.postings if p.url == url)

    def apply(self, job: JobPosting, ctx: ApplyContext) -> ApplyResult:
        self.applied.append(job.external_id)
        out = self.outcomes.get(job.external_id, ApplyResult(ApplyStatus.APPLIED, "ok"))
        if isinstance(out, Exception):
            raise out
        return out

    def screenshot(self, directory, name):
        return None


def posting(i, title="Python Developer", desc=None):
    return JobPosting(
        site="naukri",
        external_id=str(i),
        url=f"https://x/{i}",
        title=title,
        company=f"Co{i}",
        description=desc or ("d" * 300),
    )


def scorer(scores: dict[str, int]):
    """FakeLLM that scores by job title keyword."""

    def fn(system, user):
        for k, v in scores.items():
            if k in user:
                return {"score": v, "reasoning": f"{k}:{v}"}
        return {"score": 10, "reasoning": "default"}

    return FakeLLM(fn)


@pytest.fixture()
def env(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/t.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        u = User(email="a@b.co", password_hash="x")
        db.add(u)
        db.flush()
        r = Resume(
            user_id=u.id,
            label="cv",
            original_filename="cv.pdf",
            stored_path="/tmp/cv.pdf",
            mime_type="application/pdf",
            is_default=True,
            status="parsed",
            raw_text="t",
        )
        r.profile = ResumeProfile(data={"skills": ["Python"], "total_experience_years": 4.0})
        db.add(r)
        sp = SearchProfile(user_id=u.id, name="sp", keywords=["python"], sites=["naukri"])
        db.add(sp)
        db.flush()
        accts = [
            SiteAccount(
                user_id=u.id,
                site="naukri",
                label=f"acct{i}",
                status="active",
                storage_state_enc=encrypt("{}"),
                daily_cap=25,
            )
            for i in range(2)
        ]
        db.add_all(accts)
        db.commit()
        ids = {"user": u.id, "sp": sp.id, "accts": [a.id for a in accts]}

    class Env:
        pass

    e = Env()
    e.factory, e.ids, e.tmp = factory, ids, tmp_path
    e.adapters = {}

    def make_schedule(mode="auto", accounts=1, threshold=60, cap=None, concurrency=3):
        with factory() as db:
            s = Schedule(
                user_id=ids["user"],
                name="s",
                search_profile_id=ids["sp"],
                account_ids=ids["accts"][:accounts],
                mode=mode,
                kind="daily",
                time_of_day="09:00",
                match_threshold=threshold,
                daily_cap=cap,
                max_concurrency=concurrency,
            )
            db.add(s)
            db.flush()
            run = ScheduleRun(schedule_id=s.id, user_id=ids["user"])
            db.add(run)
            db.commit()
            return run.id

    def deps(llm):
        return RunDeps(
            session_factory=factory,
            open_adapter=lambda aid: nullcontext(e.adapters[aid]),
            llm=llm,
            humanizer_factory=lambda: Humanizer(scale=0),
            screenshot_root=tmp_path / "shots",
            apply_gap=(0, 0),
        )

    e.make_schedule, e.deps = make_schedule, deps
    return e


def statuses(env):
    from app.models import Job

    with env.factory() as db:
        rows = db.execute(
            select(Job.external_id, Application.status).join(
                Application, Application.job_id == Job.id
            )
        ).all()
        return dict(rows)


def run_row(env, rid):
    with env.factory() as db:
        return db.get(ScheduleRun, rid)


def test_dry_run_scores_but_never_applies(env):
    ad = FakeAdapter([posting(1, "Python Developer"), posting(2, "Java Architect")])
    env.adapters[env.ids["accts"][0]] = ad
    rid = env.make_schedule("dry_run", threshold=60)
    execute_run(env.deps(scorer({"Python Developer": 85, "Java Architect": 30})), rid)
    assert ad.applied == []
    assert statuses(env) == {"1": "found", "2": "skipped"}
    run = run_row(env, rid)
    assert run.status == "completed" and run.summary["found"] == 1 and run.summary["skipped"] == 1
    with env.factory() as db:
        a = db.scalar(select(Application).where(Application.score == 85))
        assert a.score_reasoning == "Python Developer:85"
        assert (
            "below threshold"
            in db.scalar(select(Application).where(Application.score == 30)).status_note
        )


def test_review_mode_queues_matches(env):
    ad = FakeAdapter([posting(1), posting(2, "Cobol Dev")])
    env.adapters[env.ids["accts"][0]] = ad
    execute_run(
        env.deps(scorer({"Cobol Dev": 20, "Python Developer": 80})), env.make_schedule("review")
    )
    assert ad.applied == [] and statuses(env) == {"1": "queued", "2": "skipped"}


def test_auto_applies_and_respects_daily_cap(env):
    ad = FakeAdapter([posting(i) for i in range(1, 5)])
    env.adapters[env.ids["accts"][0]] = ad
    rid = env.make_schedule("auto", cap=2)
    execute_run(env.deps(scorer({"Python": 90})), rid)
    assert ad.applied == ["1", "2"]
    st = statuses(env)
    assert list(st.values()).count("applied") == 2 and list(st.values()).count("queued") == 2
    with env.factory() as db:
        capped = db.scalar(select(Application).where(Application.status == "queued"))
        assert "daily cap" in capped.status_note
    # a second run the same day must not apply anything more
    ad.applied.clear()
    rid2 = env.make_schedule("auto", cap=2)
    execute_run(env.deps(scorer({"Python": 90})), rid2)
    assert ad.applied == []


def test_unknown_question_marks_needs_human_and_continues(env):
    q = NeedsHuman("unknown_question", "Why do you want this job?")
    ad = FakeAdapter([posting(1), posting(2)], outcomes={"1": q})
    env.adapters[env.ids["accts"][0]] = ad
    execute_run(env.deps(scorer({"Python": 90})), env.make_schedule("auto"))
    assert ad.applied == ["1", "2"]
    assert statuses(env) == {"1": "needs_human", "2": "applied"}
    with env.factory() as db:
        a = db.scalar(select(Application).where(Application.status == "needs_human"))
        assert (
            a.pending_question == "Why do you want this job?"
            and a.needs_human_kind == "unknown_question"
        )
        acct = db.get(SiteAccount, env.ids["accts"][0])
        assert acct.status == "active"  # an unanswered question does not block the account


def test_captcha_stops_the_account(env):
    ad = FakeAdapter(
        [posting(1), posting(2), posting(3)], outcomes={"1": NeedsHuman("captcha", "challenge")}
    )
    env.adapters[env.ids["accts"][0]] = ad
    rid = env.make_schedule("auto")
    execute_run(env.deps(scorer({"Python": 90})), rid)
    assert ad.applied == ["1"]  # never touched jobs 2 and 3
    with env.factory() as db:
        assert db.get(SiteAccount, env.ids["accts"][0]).status == "needs_human"
    assert statuses(env)["1"] == "needs_human"


def test_search_level_captcha_marks_account(env):
    ad = FakeAdapter([], search_error=NeedsHuman("captcha", "bot check"))
    env.adapters[env.ids["accts"][0]] = ad
    execute_run(env.deps(scorer({})), env.make_schedule("auto"))
    with env.factory() as db:
        assert db.get(SiteAccount, env.ids["accts"][0]).status == "needs_human"
        assert "bot check" in db.get(SiteAccount, env.ids["accts"][0]).status_note


def test_adapter_exception_becomes_failed_and_run_continues(env):
    ad = FakeAdapter([posting(1), posting(2)], outcomes={"1": RuntimeError("selector gone")})
    env.adapters[env.ids["accts"][0]] = ad
    execute_run(env.deps(scorer({"Python": 90})), env.make_schedule("auto"))
    assert statuses(env) == {"1": "failed", "2": "applied"}
    with env.factory() as db:
        assert (
            "selector gone"
            in db.scalar(select(Application).where(Application.status == "failed")).status_note
        )
        assert db.scalar(select(ApplicationLog).where(ApplicationLog.level == "error")) is not None


def test_rerun_does_not_rescore_or_reapply(env):
    ad = FakeAdapter([posting(1)])
    env.adapters[env.ids["accts"][0]] = ad
    llm = scorer({"Python": 90})
    execute_run(env.deps(llm), env.make_schedule("auto"))
    n_calls = len(llm.calls)
    execute_run(env.deps(llm), env.make_schedule("auto"))
    assert ad.applied == ["1"] and len(llm.calls) == n_calls


def test_job_applied_via_other_account_is_skipped(env):
    a0, a1 = env.ids["accts"]
    ad0, ad1 = FakeAdapter([posting(1)]), FakeAdapter([posting(1)])
    env.adapters[a0], env.adapters[a1] = ad0, ad1
    execute_run(env.deps(scorer({"Python": 90})), env.make_schedule("auto", accounts=1))
    # now only account 1 is scheduled
    with env.factory() as db:
        s = db.scalar(select(Schedule))
        s.account_ids = [a1]
        db.add(ScheduleRun(schedule_id=s.id, user_id=env.ids["user"]))
        db.commit()
        rid = db.scalar(select(ScheduleRun.id).order_by(ScheduleRun.id.desc()))
    execute_run(env.deps(scorer({"Python": 90})), rid)
    assert ad1.applied == []


def test_parallel_accounts_and_summary(env):
    a0, a1 = env.ids["accts"]
    env.adapters[a0] = FakeAdapter([posting(1), posting(2)])
    env.adapters[a1] = FakeAdapter([posting(3)])
    rid = env.make_schedule("auto", accounts=2, concurrency=2)
    execute_run(env.deps(scorer({"Python": 90})), rid)
    run = run_row(env, rid)
    assert run.status == "completed" and run.summary["applied"] == 3
    assert run.summary["accounts"][str(a0)]["applied"] == 2


def test_missing_session_or_resume_fails_run(env):
    with env.factory() as db:
        db.get(SiteAccount, env.ids["accts"][0]).storage_state_enc = None
        db.commit()
    env.adapters[env.ids["accts"][0]] = FakeAdapter([posting(1)])
    rid = env.make_schedule("auto")
    execute_run(env.deps(scorer({})), rid)
    run = run_row(env, rid)
    assert run.status == "failed" and "no saved session" in run.error
    with env.factory() as db:
        assert db.get(SiteAccount, env.ids["accts"][0]).status == "needs_login"


def test_site_not_in_search_profile_is_skipped(env):
    with env.factory() as db:
        db.get(SearchProfile, env.ids["sp"]).sites = ["linkedin"]
        db.commit()
    ad = FakeAdapter([posting(1)])
    env.adapters[env.ids["accts"][0]] = ad
    execute_run(env.deps(scorer({})), env.make_schedule("auto"))
    assert ad.searched == 0


def test_process_approved_applies_only_approved_within_quota(env):
    a0 = env.ids["accts"][0]
    ad = FakeAdapter([posting(1), posting(2), posting(3)])
    env.adapters[a0] = ad
    execute_run(env.deps(scorer({"Python": 90})), env.make_schedule("review", cap=2))
    assert statuses(env) == {"1": "queued", "2": "queued", "3": "queued"}
    assert process_approved(env.deps(scorer({}))) == 0  # nothing approved yet
    with env.factory() as db:
        for a in db.scalars(select(Application)):
            a.approved = True
        db.commit()
    assert process_approved(env.deps(scorer({}))) == 2  # schedule cap = 2
    assert sorted(ad.applied) == ["1", "2"]
    assert process_approved(env.deps(scorer({}))) == 0  # quota exhausted
    assert list(statuses(env).values()).count("queued") == 1


def test_answered_needs_human_can_be_requeued_and_applied(env):
    a0 = env.ids["accts"][0]
    ad = FakeAdapter([posting(1)], outcomes={"1": NeedsHuman("unknown_question", "Notice period?")})
    env.adapters[a0] = ad
    execute_run(env.deps(scorer({"Python": 90})), env.make_schedule("auto"))
    with env.factory() as db:
        db.add(
            AnswerBankEntry(
                user_id=env.ids["user"],
                key="notice",
                label="n",
                patterns=["notice period"],
                answer="30 days",
            )
        )
        a = db.scalar(select(Application))
        a.status, a.approved = "queued", True
        db.commit()
    ad.outcomes = {}
    assert process_approved(env.deps(scorer({}))) == 1
    assert statuses(env) == {"1": "applied"}
