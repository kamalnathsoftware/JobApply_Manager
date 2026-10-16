import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _as_list(v: Any) -> Any:
    """Smaller models sometimes return a string or null where a list is expected."""
    if v is None:
        return []
    if isinstance(v, str):
        return [x.strip() for x in re.split(r"[,;\n]", v) if x.strip()]
    return v


def _as_str(v: Any) -> Any:
    return None if v is None or isinstance(v, str) else str(v)


class Contact(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    linkedin: str | None = None
    github: str | None = None
    website: str | None = None

    @field_validator("*", mode="before")
    @classmethod
    def _coerce(cls, v: Any) -> Any:
        return _as_str(v) if not isinstance(v, str) else v


class Experience(BaseModel):
    company: str | None = None
    title: str | None = None
    location: str | None = None
    start: str | None = None
    end: str | None = None  # "Present" allowed
    description: str | None = None
    highlights: list[str] = Field(default_factory=list)

    @field_validator("highlights", mode="before")
    @classmethod
    def _hl(cls, v: Any) -> Any:
        return _as_list(v)

    @field_validator("start", "end", mode="before")
    @classmethod
    def _dates(cls, v: Any) -> Any:
        return _as_str(v) if not isinstance(v, str) else v


class Education(BaseModel):
    institution: str | None = None
    degree: str | None = None
    field: str | None = None
    start: str | None = None
    end: str | None = None
    grade: str | None = None


class Project(BaseModel):
    name: str | None = None
    description: str | None = None
    technologies: list[str] = Field(default_factory=list)
    url: str | None = None

    @field_validator("technologies", mode="before")
    @classmethod
    def _tech(cls, v: Any) -> Any:
        return _as_list(v)


class ParsedResume(BaseModel):
    """Structured resume data. Every field is optional: parsing must be lenient."""

    contact: Contact = Field(default_factory=Contact)
    headline: str | None = None
    summary: str | None = None
    current_title: str | None = None
    current_company: str | None = None
    total_experience_years: float | None = None
    skills: list[str] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)

    @field_validator(
        "skills",
        "certifications",
        "languages",
        "experience",
        "education",
        "projects",
        mode="before",
    )
    @classmethod
    def _lists(cls, v: Any) -> Any:
        return _as_list(v)

    @field_validator("total_experience_years", mode="before")
    @classmethod
    def _years(cls, v: Any) -> Any:
        if isinstance(v, str):
            m = re.search(r"\d+(?:\.\d+)?", v)
            return float(m.group()) if m else None
        return v


class ResumeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    label: str
    original_filename: str
    mime_type: str
    is_default: bool
    status: str
    parse_error: str | None
    created_at: datetime
    profile: ParsedResume | None = None
    profile_edited: bool = False
    auto_plan: dict | None = None  # set only on upload: what was created automatically


class ResumeUpdate(BaseModel):
    label: str | None = Field(default=None, max_length=255)
