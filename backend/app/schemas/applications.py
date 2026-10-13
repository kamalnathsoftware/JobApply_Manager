from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class JobBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    site: str
    url: str
    title: str
    company: str | None
    location: str | None
    salary: str | None
    experience: str | None
    posted: str | None


class ApplicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    score: int | None
    score_reasoning: str | None
    approved: bool
    applied_at: datetime | None
    status_note: str | None
    needs_human_kind: str | None
    pending_question: str | None
    attempts: int
    account_id: int
    account_label: str | None = None
    schedule_run_id: int | None
    created_at: datetime
    job: JobBrief


class ApplicationDetail(ApplicationOut):
    description: str | None = None


class ApplicationList(BaseModel):
    total: int
    items: list[ApplicationOut]


class IdsIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=200)


class AnswerIn(BaseModel):
    answer: str = Field(min_length=1, max_length=2000)
    save_to_bank: bool = True
