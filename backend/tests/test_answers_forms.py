from app.adapters.forms import extract_fields, fill_form
from app.adapters.humanize import Humanizer
from app.services.answers import BankEntry, QuestionResolver, match_option, normalize
from tests.conftest import serve

FAST = Humanizer(sleep=lambda s: None, scale=0)
PROFILE = {
    "contact": {
        "name": "Asha Rao",
        "email": "asha@example.com",
        "phone": "+91 98765-43210",
        "location": "Pune",
        "linkedin": "https://linkedin.com/in/asha",
    },
    "current_title": "Engineer",
    "current_company": "Acme",
    "total_experience_years": 4.0,
}


def test_normalize_and_match_option():
    assert normalize("Are you willing to relocate? *") == "are you willing to relocate"
    assert match_option("yes", ["Yes, I am", "No"]) == "Yes, I am"
    assert match_option("no", ["Yes", "No"]) == "No"
    assert match_option("Remote", ["Onsite", "remote", "Hybrid"]) == "remote"
    assert match_option("maybe", ["Yes", "No"]) is None


def test_resolver_resume_answers():
    r = QuestionResolver(profile=PROFILE)
    assert r.resolve("Email address *") == "asha@example.com"
    assert r.resolve("Mobile number") == "+919876543210"
    assert r.resolve("First name") == "Asha" and r.resolve("Last name") == "Rao"
    assert r.resolve("Total years of experience") == "4"
    assert r.resolve("How many years of experience do you have?") == "4"
    assert r.resolve("Years of experience with Kubernetes?") is None  # skill-specific: don't guess
    assert r.resolve("Current company") == "Acme"
    assert r.resolve("Why do you want to join us?") is None


def test_resolver_bank_has_priority_and_handles_options():
    r = QuestionResolver(
        profile=PROFILE,
        bank=[BankEntry(["notice period"], "30 days"), BankEntry(["relocate"], "yes")],
    )
    assert r.resolve("What is your notice period?") == "30 days"
    assert r.resolve("Open to relocate?", ["Yes", "No"]) == "Yes"
    assert r.resolve("Notice period", ["Immediate", "15 days", "60 days"]) is None


FORM = """<html><body><form id="f">
<label for="n">Full name *</label><input id="n" type="text" required>
<label>Email<input type="email" value="prefilled@x.com"></label>
<label for="p">Phone</label><input id="p" type="tel">
<label for="s">Notice period</label><select id="s"><option value="">Select</option><option>Immediate</option><option>30 days</option></select>
<fieldset><legend>Willing to relocate?</legend>
 <label><input type="radio" name="rel" value="y"> Yes</label><label><input type="radio" name="rel" value="n"> No</label></fieldset>
<label for="why">Why us? *</label><textarea id="why" required></textarea>
<label for="cv">Upload resume</label><input id="cv" type="file">
<input type="hidden" name="csrf" value="x"><input type="password" aria-label="Password">
</form></body></html>"""


def test_extract_and_fill_form(page, tmp_path):
    cv = tmp_path / "cv.pdf"
    cv.write_bytes(b"%PDF-1.4 test")
    serve(page, {"example.test": FORM})
    page.goto("https://example.test/")
    fields = extract_fields(page)
    labels = [f.label for f in fields]
    assert labels == [
        "Full name",
        "Email",
        "Phone",
        "Notice period",
        "Willing to relocate?",
        "Why us?",
        "Upload resume",
        "Password",
    ]
    assert [f.required for f in fields][:1] == [True]
    r = QuestionResolver(
        profile=PROFILE,
        bank=[BankEntry(["notice period"], "30 days"), BankEntry(["relocate"], "yes")],
    )
    rep = fill_form(page, r, str(cv), FAST, fields=fields)
    assert page.input_value("#n") == "Asha Rao"
    assert page.input_value("input[type=email]") == "prefilled@x.com"  # prefilled kept
    assert page.input_value("#p") == "+919876543210"
    assert page.eval_on_selector("#s", "e => e.selectedOptions[0].text") == "30 days"
    assert page.is_checked("input[value=y]") and not page.is_checked("input[value=n]")
    assert page.eval_on_selector("#cv", "e => e.files.length") == 1
    assert [f.label for f in rep.unknown] == ["Why us?"]  # required & unknowable -> human
    assert "Password" in rep.skipped and page.input_value("[aria-label=Password]") == ""


def test_answer_bank_api(client):
    client.post("/api/auth/register", json={"email": "u@example.com", "password": "password123"})
    t = client.post(
        "/api/auth/login", json={"email": "u@example.com", "password": "password123"}
    ).json()
    h = {"Authorization": f"Bearer {t['access_token']}"}
    assert any(
        s["key"] == "notice_period"
        for s in client.get("/api/answer-bank/suggestions", headers=h).json()
    )
    body = {
        "key": "notice_period",
        "label": "Notice",
        "patterns": [" Notice Period ", ""],
        "answer": "30 days",
    }
    r = client.post("/api/answer-bank", headers=h, json=body)
    assert r.status_code == 201 and r.json()["patterns"] == ["notice period"]
    eid = r.json()["id"]
    assert (
        client.put(f"/api/answer-bank/{eid}", headers=h, json=body | {"answer": "15 days"}).json()[
            "answer"
        ]
        == "15 days"
    )
    assert (
        client.post("/api/answer-bank", headers=h, json=body | {"patterns": [" "]}).status_code
        == 422
    )
    assert client.delete(f"/api/answer-bank/{eid}", headers=h).status_code == 204
    assert client.get("/api/answer-bank", headers=h).json() == []


def test_experience_question_variants():
    r = QuestionResolver(profile=PROFILE)
    assert r.resolve("How many years of work experience do you have?") == "4"
    assert r.resolve("Years of experience in total") == "4"
    for q in (
        "How many years of work experience do you have with Python?",
        "Years of experience in Java development",
        "years of experience using Docker",
    ):
        assert r.resolve(q) is None, q
