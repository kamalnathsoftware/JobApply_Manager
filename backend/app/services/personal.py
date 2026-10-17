"""Personal details -> answers. Entries are plain (patterns, answer) pairs, so they flow through
the same resolver as the answer bank. Sensitive ones are never sent to an external LLM."""

import json
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import decrypt, encrypt
from app.models import PersonalDetails
from app.schemas.personal import PersonalDetailsIn
from app.services.answers import BankEntry


def load(db: Session, user_id: int) -> PersonalDetailsIn:
    row = db.scalar(select(PersonalDetails).where(PersonalDetails.user_id == user_id))
    if row is None:
        return PersonalDetailsIn()
    try:
        return PersonalDetailsIn.model_validate(json.loads(decrypt(row.data_enc)))
    except Exception:  # unreadable (e.g. FERNET_KEY changed): behave as if empty
        return PersonalDetailsIn()


def save(db: Session, user_id: int, d: PersonalDetailsIn) -> PersonalDetailsIn:
    blob = encrypt(d.model_dump_json())
    row = db.scalar(select(PersonalDetails).where(PersonalDetails.user_id == user_id))
    if row is None:
        db.add(PersonalDetails(user_id=user_id, data_enc=blob))
    else:
        row.data_enc = blob
    db.commit()
    return d


def age_on(dob: date, today: date | None = None) -> int:
    t = today or date.today()
    return t.year - dob.year - ((t.month, t.day) < (dob.month, dob.day))


# (field, patterns, sensitive). Patterns are matched as substrings of the normalized question
# (lowercase, punctuation -> space), so keep them specific: "address" alone would also match
# "email address".
_FIELDS: list[tuple[str, list[str], bool]] = [
    ("gender", ["gender"], False),
    ("marital_status", ["marital status", "marital"], False),
    ("nationality", ["nationality", "citizenship"], False),
    ("father_name", ["father name", "father s name", "fathers name"], True),
    ("passport_number", ["passport number", "passport no"], True),
    ("disability_status", ["disability", "differently abled"], True),
    (
        "address",
        [
            "current address",
            "permanent address",
            "residential address",
            "mailing address",
            "postal address",
            "street address",
            "address line",
            "home address",
        ],
        False,
    ),
    ("city", ["hometown", "home town", "your city", "city of residence"], False),
    (
        "state",
        ["state province", "province", "your state", "which state", "state of residence"],
        False,
    ),
    (
        "postal_code",
        ["pin code", "pincode", "postal code", "postcode", "zip code", "zipcode"],
        False,
    ),
    (
        "country",
        ["country of residence", "current country", "which country", "your country"],
        False,
    ),
    (
        "alternate_phone",
        ["alternate phone", "alternate mobile", "alternate contact", "alternative phone"],
        False,
    ),
    (
        "current_ctc",
        ["current ctc", "current salary", "current compensation", "present salary"],
        False,
    ),
    (
        "expected_ctc",
        ["expected ctc", "expected salary", "salary expectation", "expected compensation"],
        False,
    ),
    (
        "notice_period",
        ["notice period", "how soon can you join", "earliest joining", "joining time"],
        False,
    ),
    ("preferred_location", ["preferred location", "preferred work location"], False),
    ("willing_to_relocate", ["relocate", "relocation"], False),
    (
        "work_authorization",
        [
            "authorized to work",
            "authorised to work",
            "legally authorized",
            "work permit",
            "right to work",
        ],
        False,
    ),
    ("requires_sponsorship", ["sponsorship", "require visa"], False),
]

DOB_PATTERNS = ["date of birth", "dob", "birth date", "birthday", "d o b"]
AGE_PATTERNS = ["your age", "age in years", "current age"]
LWD_PATTERNS = [
    "last working day",
    "last working date",
    "last day of work",
    "last day at work",
    "last day in office",
    "last day of employment",
    "relieving date",
    "date of relieving",
    "lwd",
]


def dob_text(d: date) -> str:
    return d.strftime("%d/%m/%Y")  # dd/mm/yyyy; date <input> fields are converted when filling


def entries(d: PersonalDetailsIn) -> list[BankEntry]:
    out: list[BankEntry] = []
    if d.date_of_birth:
        out.append(BankEntry(DOB_PATTERNS, dob_text(d.date_of_birth), sensitive=True))
        out.append(BankEntry(AGE_PATTERNS, str(age_on(d.date_of_birth))))
    if d.last_working_day:
        out.append(BankEntry(LWD_PATTERNS, dob_text(d.last_working_day)))
    for field, patterns, sensitive in _FIELDS:
        val = getattr(d, field)
        if val:
            out.append(BankEntry(list(patterns), str(val), sensitive=sensitive))
    return out
