from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class AnswerBankEntry(TimestampMixin, Base):
    """Reusable answers to screening questions. An entry applies to a question when any of
    its `patterns` (lowercase substrings) occurs in the normalized question text."""

    __tablename__ = "answer_bank"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(100))
    label: Mapped[str] = mapped_column(String(255))
    patterns: Mapped[list] = mapped_column(JSON)
    answer: Mapped[str] = mapped_column(Text)
