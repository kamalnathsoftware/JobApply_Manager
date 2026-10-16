from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class PersonalDetails(TimestampMixin, Base):
    """One row per user: personal data job forms ask for (date of birth, address, CTC...).
    The whole JSON document is Fernet-encrypted at rest."""

    __tablename__ = "personal_details"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    data_enc: Mapped[str] = mapped_column(Text)
