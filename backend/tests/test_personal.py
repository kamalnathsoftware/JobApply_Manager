from datetime import date

from app.models import PersonalDetails
from app.services import personal
from app.services.answers import QuestionResolver
from app.services.runner import bank_dicts, build_resolver
from tests.test_autoplan import mk_account  # noqa: F401
from tests.test_resumes import auth, storage  # noqa: F401

FULL = {
    "date_of_birth": "1995-03-07",
    "gender": "Male",
    "marital_status": "Single",
    "nationality": "Indian",
    "father_name": "R Kumar",
    "passport_number": "P1234567",
    "address": "12 MG Road",
    "postal_code": "600001",
    "current_ctc": "6 LPA",
    "expected_ctc": "9 LPA",
    "notice_period": "30 days",
    "willing_to_relocate": "Yes",
    "requires_sponsorship": "No",
}


def test_roundtrip_and_encrypted_at_rest(client, auth, db_session):  # noqa: F811
    assert client.get("/api/personal-details", headers=auth).json()["gender"] == ""
    assert client.put("/api/personal-details", headers=auth, json=FULL).status_code == 200
    got = client.get("/api/personal-details", headers=auth).json()
    assert got["date_of_birth"] == "1995-03-07" and got["expected_ctc"] == "9 LPA"
    raw = db_session.query(PersonalDetails).one().data_enc
    assert "1995" not in raw and "P1234567" not in raw


def test_validation(client, auth):  # noqa: F811
    bad = client.put("/api/personal-details", headers=auth, json={"date_of_birth": "2999-01-01"})
    assert bad.status_code == 422
    assert (
        client.put(
            "/api/personal-details", headers=auth, json={"date_of_birth": "not a date"}
        ).status_code
        == 422
    )
    assert (
        client.put(
            "/api/personal-details", headers=auth, json={"willing_to_relocate": "maybe"}
        ).status_code
        == 422
    )


def test_age_calculation():
    assert personal.age_on(date(1995, 3, 7), date(2026, 3, 6)) == 30
    assert personal.age_on(date(1995, 3, 7), date(2026, 3, 7)) == 31


def resolver_for(d):
    from app.schemas.personal import PersonalDetailsIn

    return QuestionResolver(
        profile={"contact": {"email": "me@example.com", "location": "Chennai"}},
        bank=personal.entries(PersonalDetailsIn.model_validate(d)),
    )


def test_resolver_answers_personal_questions():
    r = resolver_for(FULL)
    assert r.resolve("Date of Birth") == "07/03/1995"
    assert r.resolve("DOB (dd/mm/yyyy)") == "07/03/1995"
    assert r.resolve("Gender", ["Male", "Female", "Other"]) == "Male"
    assert r.resolve("Father's name") == "R Kumar"
    assert r.resolve("Pin code") == "600001"
    assert r.resolve("Permanent address") == "12 MG Road"
    assert r.resolve("Expected CTC (in LPA)") == "9 LPA"
    assert r.resolve("Are you willing to relocate?", ["Yes", "No"]) == "Yes"
    assert r.resolve("Do you require visa sponsorship?", ["Yes", "No"]) == "No"
    assert r.resolve("Your age") == "31" or r.resolve("Your age").isdigit()
    # "address" must not hijack the email question
    assert r.resolve("Email address") == "me@example.com"
    assert r.resolve("Passport number") == "P1234567"


def test_empty_fields_are_never_used_and_unknowns_stay_unknown():
    r = resolver_for({"gender": "Female"})
    assert r.resolve("Date of birth") is None
    assert r.resolve("Expected salary") is None
    assert r.resolve("Gender") == "Female"


def test_sensitive_entries_are_kept_out_of_llm_payloads(client, auth, db_session):  # noqa: F811
    client.put("/api/personal-details", headers=auth, json=FULL)
    from app.models import User

    uid = db_session.query(User).one().id
    res = build_resolver(db_session, uid, {})
    assert res.resolve("Date of birth") == "07/03/1995"  # resolver still answers locally
    sent = str(bank_dicts(res))
    assert "07/03/1995" not in sent and "P1234567" not in sent and "R Kumar" not in sent
    assert "9 LPA" in sent and "Single" in sent


def test_answer_bank_entry_overrides_personal_details(client, auth, db_session):  # noqa: F811
    client.put("/api/personal-details", headers=auth, json=FULL)
    client.post(
        "/api/answer-bank",
        headers=auth,
        json={"key": "n", "label": "n", "patterns": ["notice period"], "answer": "Immediate"},
    )
    from app.models import User

    uid = db_session.query(User).one().id
    assert build_resolver(db_session, uid, {}).resolve("Notice period") == "Immediate"


def test_date_input_is_filled_in_iso_format(page):
    from app.adapters.forms import Field, fill_value
    from app.adapters.humanize import Humanizer
    from tests.conftest import serve

    serve(page, {"x.test": "<html><body><label>DOB <input type=date id=d></label></body></html>"})
    page.goto("https://x.test/")
    page.evaluate("document.getElementById('d').setAttribute('data-jam','0')")
    h = Humanizer(scale=0)
    assert fill_value(
        page,
        Field(id="0", type="date", label="DOB", required=False, options=[], value=""),
        "07/03/1995",
        h,
    )
    assert page.input_value("#d") == "1995-03-07"
