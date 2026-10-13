from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Site = Literal["naukri", "linkedin", "indeed", "company"]


class AccountCreate(BaseModel):
    site: Site
    label: str = Field(min_length=1, max_length=255)
    login_email: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, max_length=500)
    resume_id: int | None = None
    daily_cap: int = Field(default=25, ge=1, le=200)


class AccountUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=255)
    login_email: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, max_length=500)
    resume_id: int | None = None
    daily_cap: int | None = Field(default=None, ge=1, le=200)
    status: Literal["disabled", "needs_login"] | None = None
    clear_resume: bool = False


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    site: str
    label: str
    login_email: str | None
    resume_id: int | None
    status: str
    status_note: str | None
    daily_cap: int
    has_session: bool
    has_password: bool
    last_login_at: datetime | None
