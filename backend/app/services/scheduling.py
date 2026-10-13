"""Pure schedule logic: triggers, validation and daily quota math."""

import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Application, Schedule, SiteAccount

DEFAULT_DAILY_CAP = 25
_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class ScheduleError(ValueError):
    pass


def get_tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise ScheduleError(f"Unknown timezone '{name}'") from e


def build_trigger(
    kind: str, time_of_day: str | None, cron_expr: str | None, timezone: str
) -> CronTrigger:
    tz = get_tz(timezone)
    if kind in ("daily", "weekdays"):
        m = _HHMM.match(time_of_day or "")
        if not m:
            raise ScheduleError("time_of_day must be HH:MM (24h)")
        return CronTrigger(
            hour=int(m.group(1)),
            minute=int(m.group(2)),
            day_of_week="mon-fri" if kind == "weekdays" else "*",
            timezone=tz,
        )
    if kind == "cron":
        if not cron_expr:
            raise ScheduleError("cron_expr is required")
        try:
            return CronTrigger.from_crontab(cron_expr, timezone=tz)
        except ValueError as e:
            raise ScheduleError(f"Invalid cron expression: {e}") from e
    raise ScheduleError(f"Unknown schedule kind '{kind}'")


def next_fire(schedule: Schedule, now: datetime | None = None) -> datetime | None:
    """Next fire time as naive UTC (for display / storage)."""
    trig = build_trigger(schedule.kind, schedule.time_of_day, schedule.cron_expr, schedule.timezone)
    now = now or datetime.now(UTC)
    nxt = trig.get_next_fire_time(None, now)
    return nxt.astimezone(UTC).replace(tzinfo=None) if nxt else None


def day_bounds_utc(tz_name: str, now: datetime | None = None) -> tuple[datetime, datetime]:
    """[start, end) of the current local day in the given timezone, as naive UTC."""
    tz = get_tz(tz_name)
    local = (now or datetime.now(UTC)).astimezone(tz)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    from datetime import timedelta

    end = start + timedelta(days=1)
    return (
        start.astimezone(UTC).replace(tzinfo=None),
        end.astimezone(UTC).replace(tzinfo=None),
    )


def applied_today(db: Session, account_id: int, tz_name: str, now: datetime | None = None) -> int:
    start, end = day_bounds_utc(tz_name, now)
    return (
        db.scalar(
            select(func.count(Application.id)).where(
                Application.account_id == account_id,
                Application.status == "applied",
                Application.applied_at >= start,
                Application.applied_at < end,
            )
        )
        or 0
    )


def effective_cap(account: SiteAccount, schedule: Schedule | None) -> int:
    cap = account.daily_cap or DEFAULT_DAILY_CAP
    if schedule is not None and schedule.daily_cap:
        cap = min(cap, schedule.daily_cap)
    return cap


def remaining_quota(
    db: Session,
    account: SiteAccount,
    schedule: Schedule | None,
    tz_name: str = "UTC",
    now: datetime | None = None,
) -> int:
    return max(0, effective_cap(account, schedule) - applied_today(db, account.id, tz_name, now))
