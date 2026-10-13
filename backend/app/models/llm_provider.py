from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class LLMProviderSetting(TimestampMixin, Base):
    """Per-user provider choice. Providers are tried in ascending `priority` order."""

    __tablename__ = "llm_providers"
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_llm_user_provider"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(20))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    model: Mapped[str | None] = mapped_column(String(100), default=None)
    base_url: Mapped[str | None] = mapped_column(String(255), default=None)
    api_key_enc: Mapped[str | None] = mapped_column(Text, default=None)  # Fernet
