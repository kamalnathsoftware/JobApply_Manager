from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class Contact(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    linkedin: str | None = None
    github: str | None = None
    website: str | None = None


class Experience(BaseModel):
    company: str | None = None
    title: str | None = None
    location: str | None = None
    start: str | None = None
    end: str | None = None  # "Present" allowed
    description: str | None = None
    highlights: list[str] = Field(default_factory=list)


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


class ResumeUpdate(BaseModel):
    label: str | None = Field(default=None, max_length=255)
