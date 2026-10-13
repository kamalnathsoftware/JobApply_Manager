from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class SiteAccount(TimestampMixin, Base):
    __tablename__ = "site_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    site: Mapped[str] = mapped_column(String(20), index=True)  # naukri|linkedin|indeed|company
    label: Mapped[str] = mapped_column(String(255))
    login_email: Mapped[str | None] = mapped_column(String(255), default=None)
    # Fernet-encrypted JSON ({"password": ...}); optional, never returned by the API.
    credentials_enc: Mapped[str | None] = mapped_column(Text, default=None)
    # Fernet-encrypted Playwright storage_state JSON.
    storage_state_enc: Mapped[str | None] = mapped_column(
        Text().with_variant(Text(16_000_000), "mysql"), default=None
    )
    resume_id: Mapped[int | None] = mapped_column(
        ForeignKey("resumes.id", ondelete="SET NULL"), default=None
    )
    # new | login_in_progress | active | needs_login | needs_human | disabled
    status: Mapped[str] = mapped_column(String(30), default="new")
    daily_cap: Mapped[int] = mapped_column(Integer, default=25)
    login_started_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    status_note: Mapped[str | None] = mapped_column(String(500), default=None)
