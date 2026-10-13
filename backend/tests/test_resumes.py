import pytest

from app.api.deps import optional_llm
from app.core.config import get_settings
from app.main import app
from app.services.llm import LLMError, extract_json
from app.services.resume_text import UnsupportedResume, extract_text, validate_upload
from tests.helpers import FakeLLM, make_docx, make_pdf

PARSED = {
    "contact": {"name": "Asha Rao", "email": "asha@example.com", "phone": "+91 99999 11111"},
    "current_title": "Backend Engineer",
    "total_experience_years": 4.5,
    "skills": ["Python", "FastAPI", "python", " MySQL "],
    "experience": [{"company": "Acme", "title": "Engineer", "start": "2020", "end": "Present"}],
    "education": [{"institution": "NIT", "degree": "B.Tech"}],
    "unexpected_key": "ignored",
}


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path))


@pytest.fixture()
def auth(client):
    client.post("/api/auth/register", json={"email": "u@example.com", "password": "password123"})
    t = client.post(
        "/api/auth/login", json={"email": "u@example.com", "password": "password123"}
    ).json()
    return {"Authorization": f"Bearer {t['access_token']}"}


@pytest.fixture()
def llm():
    fake = FakeLLM(PARSED)
    app.dependency_overrides[optional_llm] = lambda: fake
    yield fake
    app.dependency_overrides.pop(optional_llm, None)


def upload(client, auth, data=None, name="cv.pdf", label=None):
    data = data or make_pdf(["Asha Rao", "Python developer (FastAPI)"])
    return client.post(
        "/api/resumes",
        headers=auth,
        files={"file": (name, data, "application/octet-stream")},
        data={"label": label} if label else {},
    )


def test_text_extraction_pdf_and_docx():
    assert "Asha Rao" in extract_text(make_pdf(["Asha Rao", "Python"]), ".pdf")
    assert "Hello (world)" in extract_text(make_pdf(["Hello (world)"]), ".pdf")
    assert "Led a team" in extract_text(make_docx(["Asha", "Led a team"]), ".docx")


def test_validate_upload_rejects_bad_files():
    with pytest.raises(UnsupportedResume):
        validate_upload("a.exe", b"MZ...")
    with pytest.raises(UnsupportedResume):
        validate_upload("a.pdf", b"not a pdf")
    with pytest.raises(UnsupportedResume):
        validate_upload("a.pdf", b"")
    assert validate_upload("a.docx", make_docx(["x"])) == ".docx"


def test_extract_json_variants():
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Sure! Here it is: {"a": [1, 2]} hope it helps') == {"a": [1, 2]}
    with pytest.raises(LLMError):
        extract_json("no json here")


def test_upload_parses_and_normalizes_skills(client, auth, llm):
    r = upload(client, auth, label="Main CV")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "parsed" and body["is_default"] is True and body["label"] == "Main CV"
    assert body["profile"]["contact"]["email"] == "asha@example.com"
    assert "Asha Rao" in llm.calls[0][1]  # resume text reached the model
    assert body["profile"]["skills"] == ["Python", "FastAPI", "python", " MySQL "]


def test_skills_table_deduplicated(client, auth, llm, db_session):
    from app.models import Skill

    upload(client, auth)
    names = sorted(s.name_normalized for s in db_session.query(Skill))
    assert names == ["fastapi", "mysql", "python"]


def test_docx_upload(client, auth, llm):
    r = upload(client, auth, data=make_docx(["Asha Rao", "Python"]), name="cv.docx")
    assert r.status_code == 201 and r.json()["status"] == "parsed"


def test_upload_without_api_key_is_stored_and_marked_failed(client, auth):
    app.dependency_overrides[optional_llm] = lambda: None
    try:
        r = upload(client, auth)
    finally:
        app.dependency_overrides.pop(optional_llm, None)
    assert r.status_code == 201
    assert r.json()["status"] == "parse_failed" and "LLM_PROVIDER" in r.json()["parse_error"]


def test_llm_failure_recorded_not_raised(client, auth):
    app.dependency_overrides[optional_llm] = lambda: FakeLLM(LLMError("boom"))
    try:
        r = upload(client, auth)
    finally:
        app.dependency_overrides.pop(optional_llm, None)
    assert r.status_code == 201 and r.json()["status"] == "parse_failed"


def test_rejects_wrong_type(client, auth, llm):
    assert upload(client, auth, data=b"hello", name="cv.txt").status_code == 422
    assert upload(client, auth, data=b"hello", name="cv.pdf").status_code == 422


def test_edit_profile_and_reparse_semantics(client, auth, llm):
    rid = upload(client, auth).json()["id"]
    edited = dict(PARSED, current_title="Staff Engineer", skills=["Go"])
    r = client.put(f"/api/resumes/{rid}/profile", headers=auth, json=edited)
    assert r.json()["profile"]["current_title"] == "Staff Engineer" and r.json()["profile_edited"]
    # explicit reparse overwrites edits
    r = client.post(f"/api/resumes/{rid}/reparse", headers=auth)
    assert r.json()["profile"]["current_title"] == "Backend Engineer"
    assert not r.json()["profile_edited"]


def test_default_switching_and_delete(client, auth, llm):
    a = upload(client, auth, name="a.pdf").json()
    b = upload(client, auth, name="b.pdf").json()
    assert a["is_default"] and not b["is_default"]
    client.post(f"/api/resumes/{b['id']}/default", headers=auth)
    listed = {r["id"]: r["is_default"] for r in client.get("/api/resumes", headers=auth).json()}
    assert listed == {a["id"]: False, b["id"]: True}
    assert client.delete(f"/api/resumes/{b['id']}", headers=auth).status_code == 204
    listed = client.get("/api/resumes", headers=auth).json()
    assert len(listed) == 1 and listed[0]["is_default"]  # default falls back to remaining


def test_resumes_are_private_per_user(client, auth, llm):
    rid = upload(client, auth).json()["id"]
    client.post("/api/auth/register", json={"email": "o@example.com", "password": "password123"})
    t = client.post(
        "/api/auth/login", json={"email": "o@example.com", "password": "password123"}
    ).json()
    other = {"Authorization": f"Bearer {t['access_token']}"}
    assert client.get(f"/api/resumes/{rid}", headers=other).status_code == 404
    assert client.get(f"/api/resumes/{rid}/file", headers=other).status_code == 404
    assert client.delete(f"/api/resumes/{rid}", headers=other).status_code == 404
    assert client.get("/api/resumes", headers=other).json() == []
    assert client.get(f"/api/resumes/{rid}/file", headers=auth).status_code == 200
