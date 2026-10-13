from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Resume(TimestampMixin, Base):
    __tablename__ = "resumes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(255))
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(500))
    mime_type: Mapped[str] = mapped_column(String(100))
    raw_text: Mapped[str | None] = mapped_column(Text().with_variant(Text(16_000_000), "mysql"))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    # uploaded | parsed | parse_failed
    status: Mapped[str] = mapped_column(String(20), default="uploaded")
    parse_error: Mapped[str | None] = mapped_column(Text, default=None)

    profile: Mapped["ResumeProfile | None"] = relationship(
        back_populates="resume", cascade="all, delete-orphan", uselist=False
    )
    skills: Mapped[list["Skill"]] = relationship(
        back_populates="resume", cascade="all, delete-orphan"
    )


class ResumeProfile(Base):
    __tablename__ = "resume_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    resume_id: Mapped[int] = mapped_column(
        ForeignKey("resumes.id", ondelete="CASCADE"), unique=True
    )
    data: Mapped[dict] = mapped_column(JSON)
    total_experience_years: Mapped[float | None] = mapped_column(Float, default=None)
    user_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    model: Mapped[str | None] = mapped_column(String(100), default=None)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    resume: Mapped[Resume] = relationship(back_populates="profile")


class Skill(Base):
    __tablename__ = "skills"
    __table_args__ = (
        UniqueConstraint("resume_id", "name_normalized", name="uq_skill_resume_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    resume_id: Mapped[int] = mapped_column(ForeignKey("resumes.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    name_normalized: Mapped[str] = mapped_column(String(100), index=True)

    resume: Mapped[Resume] = relationship(back_populates="skills")
