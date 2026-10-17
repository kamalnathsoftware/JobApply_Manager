from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator

YesNo = Literal["Yes", "No", ""]


class PersonalDetailsIn(BaseModel):
    """Every field is optional. Empty fields are simply never used to answer a form."""

    date_of_birth: date | None = None
    gender: str = Field(default="", max_length=40)
    marital_status: str = Field(default="", max_length=40)
    nationality: str = Field(default="", max_length=80)
    father_name: str = Field(default="", max_length=120)
    passport_number: str = Field(default="", max_length=40)
    disability_status: str = Field(default="", max_length=120)

    address: str = Field(default="", max_length=300)
    city: str = Field(default="", max_length=80)
    state: str = Field(default="", max_length=80)
    postal_code: str = Field(default="", max_length=20)
    country: str = Field(default="", max_length=80)
    alternate_phone: str = Field(default="", max_length=30)

    current_ctc: str = Field(default="", max_length=60)
    expected_ctc: str = Field(default="", max_length=60)
    notice_period: str = Field(default="", max_length=60)
    last_working_day: date | None = None  # date you leave / left your current employer
    preferred_location: str = Field(default="", max_length=160)
    willing_to_relocate: YesNo = ""
    work_authorization: str = Field(default="", max_length=120)
    requires_sponsorship: YesNo = ""

    @field_validator("*", mode="before")
    @classmethod
    def _strip(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("last_working_day")
    @classmethod
    def _lwd(cls, v: date | None) -> date | None:
        if v is not None and not (date(2000, 1, 1) <= v <= date(2100, 12, 31)):
            raise ValueError("last working day is out of range")
        return v

    @field_validator("date_of_birth")
    @classmethod
    def _dob(cls, v: date | None) -> date | None:
        if v is not None and not (date(1900, 1, 1) <= v <= date.today()):
            raise ValueError("date of birth is out of range")
        return v
