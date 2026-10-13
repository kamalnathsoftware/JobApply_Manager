from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

LONGTEXT = Text().with_variant(Text(16_000_000), "mysql")


class SearchProfile(TimestampMixin, Base):
    __tablename__ = "search_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    keywords: Mapped[list] = mapped_column(JSON)
    location: Mapped[str | None] = mapped_column(String(255), default=None)
    experience_min: Mapped[int | None] = mapped_column(Integer, default=None)
    experience_max: Mapped[int | None] = mapped_column(Integer, default=None)
    salary_min: Mapped[int | None] = mapped_column(Integer, default=None)
    job_type: Mapped[str | None] = mapped_column(String(50), default=None)
    posted_within_days: Mapped[int | None] = mapped_column(Integer, default=None)
    excluded_companies: Mapped[list] = mapped_column(JSON, default=list)
    sites: Mapped[list] = mapped_column(JSON, default=list)
    company_urls: Mapped[list] = mapped_column(JSON, default=list)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("site_accounts.id", ondelete="SET NULL"), default=None
    )
    max_results: Mapped[int] = mapped_column(Integer, default=25)


class Schedule(TimestampMixin, Base):
    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    search_profile_id: Mapped[int] = mapped_column(
        ForeignKey("search_profiles.id", ondelete="CASCADE")
    )
    account_ids: Mapped[list] = mapped_column(JSON)
    mode: Mapped[str] = mapped_column(String(20), default="dry_run")  # dry_run|review|auto
    kind: Mapped[str] = mapped_column(String(20), default="daily")  # daily|weekdays|cron
    time_of_day: Mapped[str | None] = mapped_column(String(5), default=None)  # HH:MM
    cron_expr: Mapped[str | None] = mapped_column(String(100), default=None)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    daily_cap: Mapped[int | None] = mapped_column(Integer, default=None)  # per account override
    match_threshold: Mapped[int] = mapped_column(Integer, default=60)
    max_concurrency: Mapped[int] = mapped_column(Integer, default=3)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)


class ScheduleRun(Base):
    __tablename__ = "schedule_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[int] = mapped_column(
        ForeignKey("schedules.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    trigger: Mapped[str] = mapped_column(String(20), default="manual")  # manual|schedule
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    # pending|running|completed|failed
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    summary: Mapped[dict | None] = mapped_column(JSON, default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("user_id", "site", "external_id", name="uq_job_ext"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    site: Mapped[str] = mapped_column(String(20), index=True)
    external_id: Mapped[str] = mapped_column(String(190))
    url: Mapped[str] = mapped_column(String(1000))
    title: Mapped[str] = mapped_column(String(500))
    company: Mapped[str | None] = mapped_column(String(255), default=None)
    location: Mapped[str | None] = mapped_column(String(255), default=None)
    description: Mapped[str | None] = mapped_column(LONGTEXT, default=None)
    salary: Mapped[str | None] = mapped_column(String(255), default=None)
    experience: Mapped[str | None] = mapped_column(String(255), default=None)
    posted: Mapped[str | None] = mapped_column(String(100), default=None)
    apply_type: Mapped[str] = mapped_column(String(20), default="unknown")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Application(TimestampMixin, Base):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("account_id", "job_id", name="uq_app_account_job"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("site_accounts.id", ondelete="CASCADE"), index=True
    )
    schedule_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("schedule_runs.id", ondelete="SET NULL"), default=None
    )
    # found | queued | applied | failed | needs_human | skipped
    status: Mapped[str] = mapped_column(String(20), default="found", index=True)
    score: Mapped[int | None] = mapped_column(Integer, default=None)
    score_reasoning: Mapped[str | None] = mapped_column(Text, default=None)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime, default=None, index=True)
    status_note: Mapped[str | None] = mapped_column(Text, default=None)
    needs_human_kind: Mapped[str | None] = mapped_column(String(30), default=None)
    pending_question: Mapped[str | None] = mapped_column(Text, default=None)
    attempts: Mapped[int] = mapped_column(Integer, default=0)


class ApplicationLog(Base):
    __tablename__ = "application_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True, default=None
    )
    schedule_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("schedule_runs.id", ondelete="CASCADE"), index=True, default=None
    )
    level: Mapped[str] = mapped_column(String(10), default="info")
    message: Mapped[str] = mapped_column(Text)
    screenshot_path: Mapped[str | None] = mapped_column(String(500), default=None)
    error_text: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
