import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.sites import SITE_KEYS


class SearchProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    keywords: list[str] = Field(min_length=1)
    location: str | None = Field(default=None, max_length=255)
    experience_min: int | None = Field(default=None, ge=0, le=60)
    experience_max: int | None = Field(default=None, ge=0, le=60)
    salary_min: int | None = Field(default=None, ge=0)
    job_type: str | None = Field(default=None, max_length=50)
    posted_within_days: int | None = Field(default=None, ge=1, le=90)
    excluded_companies: list[str] = Field(default_factory=list)
    sites: list[str] = Field(default_factory=list)
    company_urls: list[str] = Field(default_factory=list)
    account_id: int | None = None
    max_results: int = Field(default=25, ge=1, le=200)

    @field_validator("keywords", "excluded_companies", "company_urls")
    @classmethod
    def _strip(cls, v: list[str]) -> list[str]:
        return [x.strip() for x in v if x and x.strip()]

    @field_validator("keywords")
    @classmethod
    def _need_keyword(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("at least one keyword is required")
        return v

    @field_validator("sites")
    @classmethod
    def _sites(cls, v: list[str]) -> list[str]:
        bad = [s for s in v if s not in SITE_KEYS]
        if bad:
            raise ValueError(f"unknown sites: {bad}")
        return v

    @field_validator("company_urls")
    @classmethod
    def _urls(cls, v: list[str]) -> list[str]:
        if any(not re.match(r"^https?://", u) for u in v):
            raise ValueError("company URLs must start with http:// or https://")
        return v


class SearchProfileOut(SearchProfileIn):
    model_config = ConfigDict(from_attributes=True)

    id: int


class ScheduleIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    search_profile_id: int
    account_ids: list[int] = Field(min_length=1)
    mode: Literal["dry_run", "review", "auto"] = "dry_run"
    kind: Literal["daily", "weekdays", "cron"] = "daily"
    time_of_day: str | None = None
    cron_expr: str | None = Field(default=None, max_length=100)
    timezone: str = "UTC"
    daily_cap: int | None = Field(default=None, ge=1, le=200)
    match_threshold: int = Field(default=60, ge=0, le=100)
    max_concurrency: int = Field(default=3, ge=1, le=8)
    enabled: bool = True


class ScheduleOut(ScheduleIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    next_run_at: datetime | None = None


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    schedule_id: int
    trigger: str
    status: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    summary: dict | None
    error: str | None


class LogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    application_id: int | None
    schedule_run_id: int | None
    level: str
    message: str
    has_screenshot: bool = False
    error_text: str | None
    created_at: datetime
