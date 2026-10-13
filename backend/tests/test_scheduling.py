from datetime import UTC, datetime

import pytest

from app.models import Application, Job, Schedule, SiteAccount, User
from app.services import scheduling as sch


def utc(*a):
    return datetime(*a, tzinfo=UTC)


def test_daily_trigger_respects_timezone():
    t = sch.build_trigger("daily", "09:30", None, "Asia/Kolkata")
    nxt = t.get_next_fire_time(None, utc(2026, 1, 5, 0, 0))
    assert nxt.astimezone(UTC) == utc(2026, 1, 5, 4, 0)  # 09:30 IST == 04:00 UTC


def test_weekdays_skips_weekend():
    t = sch.build_trigger("weekdays", "10:00", None, "UTC")
    # 2026-01-10 is a Saturday -> next fire is Monday the 12th
    assert t.get_next_fire_time(None, utc(2026, 1, 10, 12, 0)) == utc(2026, 1, 12, 10, 0)
    assert t.get_next_fire_time(None, utc(2026, 1, 8, 9, 0)) == utc(2026, 1, 8, 10, 0)


def test_cron_trigger_and_errors():
    t = sch.build_trigger("cron", None, "*/30 8-18 * * mon-fri", "UTC")
    assert t.get_next_fire_time(None, utc(2026, 1, 5, 8, 10)) == utc(2026, 1, 5, 8, 30)
    for args in [
        ("daily", "25:00", None, "UTC"),
        ("daily", None, None, "UTC"),
        ("cron", None, "not a cron", "UTC"),
        ("cron", None, None, "UTC"),
        ("daily", "09:00", None, "Mars/Base"),
        ("hourly", None, None, "UTC"),
    ]:
        with pytest.raises(sch.ScheduleError):
            sch.build_trigger(*args)


def test_day_bounds_use_local_midnight():
    start, end = sch.day_bounds_utc("Asia/Kolkata", utc(2026, 1, 5, 20, 0))  # 01:30 Jan 6 IST
    assert (start, end) == (datetime(2026, 1, 5, 18, 30), datetime(2026, 1, 6, 18, 30))


@pytest.fixture()
def world(db_session):
    u = User(email="a@b.co", password_hash="x")
    db_session.add(u)
    db_session.flush()
    acct = SiteAccount(user_id=u.id, site="naukri", label="n", daily_cap=5)
    db_session.add(acct)
    job = Job(user_id=u.id, site="naukri", external_id="1", url="u", title="t")
    db_session.add(job)
    db_session.flush()
    return u, acct, job


def test_quota_counts_only_todays_applied(db_session, world):
    u, acct, job = world
    now = utc(2026, 1, 5, 12, 0)

    def add(status, when, n):
        j = Job(user_id=u.id, site="naukri", external_id=f"j{n}", url="u", title="t")
        db_session.add(j)
        db_session.flush()
        db_session.add(
            Application(
                user_id=u.id, job_id=j.id, account_id=acct.id, status=status, applied_at=when
            )
        )

    add("applied", datetime(2026, 1, 5, 3, 0), 1)
    add("applied", datetime(2026, 1, 5, 9, 0), 2)
    add("applied", datetime(2026, 1, 4, 23, 0), 3)  # yesterday
    add("failed", datetime(2026, 1, 5, 9, 0), 4)  # not applied
    add("queued", None, 5)
    db_session.commit()
    assert sch.applied_today(db_session, acct.id, "UTC", now) == 2
    assert sch.remaining_quota(db_session, acct, None, "UTC", now) == 3


def test_schedule_cap_override_is_min_and_never_negative(db_session, world):
    _, acct, _ = world
    s = Schedule(daily_cap=2)
    assert sch.effective_cap(acct, s) == 2
    assert sch.effective_cap(acct, Schedule(daily_cap=50)) == 5
    assert sch.effective_cap(acct, None) == 5
    acct.daily_cap = None
    assert sch.effective_cap(acct, None) == sch.DEFAULT_DAILY_CAP
