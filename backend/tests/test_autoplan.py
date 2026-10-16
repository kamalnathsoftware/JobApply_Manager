# ruff: noqa: F811
from app.models import Schedule, SearchProfile
from app.schemas.resume import ParsedResume
from app.services.autoplan import derive_experience, derive_keywords
from tests.test_resumes import auth, llm, storage, upload  # noqa: F401 (fixtures)


def mk_account(client, hdr, site="naukri", **kw):
    body = {"site": site, "label": f"{site} acct", "login_email": "me@example.com"} | kw
    return client.post("/api/accounts", headers=hdr, json=body).json()


def test_derive_keywords_and_experience():
    p = ParsedResume(current_title="Senior QA Engineer - Payments (Contract)", skills=["a"])
    assert derive_keywords(p) == ["Senior QA Engineer"]
    assert derive_keywords(ParsedResume(skills=["Python", "Django", "x"])) == ["Python Django"]
    assert derive_keywords(ParsedResume()) == []
    assert derive_experience(4.5) == (3, 8)
    assert derive_experience(None) == (None, None)
    assert derive_experience(1) == (0, 4)


def test_upload_creates_profile_and_schedule(client, auth, llm, db_session):
    mk_account(client, auth)
    r = upload(client, auth).json()
    plan = r["auto_plan"]
    assert plan["created_profile"] and plan["created_schedule"]
    sp = db_session.get(SearchProfile, plan["search_profile_id"])
    assert sp.keywords == ["Backend Engineer"] and sp.sites == ["naukri", "linkedin", "indeed"]
    sch = db_session.get(Schedule, plan["schedule_id"])
    assert sch.mode == "review" and sch.enabled and sch.next_run_at is not None
    assert sch.account_ids == [client.get("/api/accounts", headers=auth).json()[0]["id"]]


def test_upload_without_accounts_makes_profile_only_then_auto_plan_adds_schedule(
    client,
    auth,
    llm,
    db_session,
):
    r = upload(client, auth).json()
    assert r["auto_plan"]["created_profile"] and not r["auto_plan"]["created_schedule"]
    assert "Add a site account" in r["auto_plan"]["message"]
    mk_account(client, auth, site="linkedin")
    again = client.post(f"/api/resumes/{r['id']}/auto-plan", headers=auth).json()
    assert not again["created_profile"] and again["created_schedule"]
    assert db_session.query(SearchProfile).count() == 1


def test_auto_plan_is_idempotent_and_merges_new_accounts(client, auth, llm, db_session):
    a1 = mk_account(client, auth)
    r = upload(client, auth).json()
    a2 = mk_account(client, auth, site="indeed")
    again = client.post(f"/api/resumes/{r['id']}/auto-plan", headers=auth).json()
    assert not again["created_schedule"] and "Added new accounts" in again["message"]
    sch = db_session.query(Schedule).one()
    assert sorted(sch.account_ids) == sorted([a1["id"], a2["id"]])
    assert db_session.query(SearchProfile).count() == 1
    assert (
        "Already planned"
        in client.post(f"/api/resumes/{r['id']}/auto-plan", headers=auth).json()["message"]
    )


def test_opt_out_and_unparsed_resume(client, auth, llm):
    mk_account(client, auth)
    data = {"auto_plan": "false"}
    r = client.post(
        "/api/resumes",
        headers=auth,
        data=data,
        files={
            "file": (
                "cv.pdf",
                __import__("tests.helpers", fromlist=["x"]).make_pdf(["x"]),
                "application/pdf",
            )
        },
    ).json()
    assert r["auto_plan"] is None
    assert client.get("/api/search-profiles", headers=auth).json() == []
    assert (
        client.post(f"/api/resumes/{r['id']}/auto-plan?mode=bogus", headers=auth).status_code == 422
    )
