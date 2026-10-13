from datetime import UTC, datetime

import pytest

from app.models import AnswerBankEntry, Application, ApplicationLog, Job, SiteAccount, User


@pytest.fixture()
def auth(client):
    client.post("/api/auth/register", json={"email": "u@example.com", "password": "password123"})
    t = client.post(
        "/api/auth/login", json={"email": "u@example.com", "password": "password123"}
    ).json()
    return {"Authorization": f"Bearer {t['access_token']}"}


@pytest.fixture()
def data(db_session, auth):
    user = db_session.query(User).one()
    acct = SiteAccount(user_id=user.id, site="naukri", label="N1", status="active", daily_cap=10)
    li = SiteAccount(user_id=user.id, site="linkedin", label="L1", status="needs_login")
    db_session.add_all([acct, li])
    db_session.flush()
    apps = {}
    for i, (site, status, score, company) in enumerate(
        [
            ("naukri", "applied", 90, "Acme"),
            ("naukri", "queued", 80, "Globex"),
            ("naukri", "needs_human", 75, "Initech"),
            ("linkedin", "skipped", 20, "Umbrella"),
            ("linkedin", "failed", 70, "Hooli"),
        ],
        1,
    ):
        j = Job(
            user_id=user.id,
            site=site,
            external_id=str(i),
            url=f"https://x/{i}",
            title=f"Job {i}",
            company=company,
            description="desc",
        )
        db_session.add(j)
        db_session.flush()
        a = Application(
            user_id=user.id,
            job_id=j.id,
            account_id=acct.id if site == "naukri" else li.id,
            status=status,
            score=score,
            applied_at=datetime.now(UTC).replace(tzinfo=None) if status == "applied" else None,
            pending_question="Notice period?" if status == "needs_human" else None,
            needs_human_kind="unknown_question" if status == "needs_human" else None,
        )
        db_session.add(a)
        db_session.flush()
        apps[status] = a
    db_session.add(
        ApplicationLog(
            application_id=apps["applied"].id, message="applied ok", screenshot_path="/nope.png"
        )
    )
    db_session.commit()
    return apps


def test_list_filters(client, auth, data):
    h = auth
    r = client.get("/api/applications", headers=h).json()
    assert r["total"] == 5 and len(r["items"]) == 5 and r["items"][0]["job"]["title"]
    assert {i["account_label"] for i in r["items"]} == {"N1", "L1"}
    assert client.get("/api/applications?status=queued,needs_human", headers=h).json()["total"] == 2
    assert client.get("/api/applications?site=linkedin", headers=h).json()["total"] == 2
    assert client.get("/api/applications?min_score=80", headers=h).json()["total"] == 2
    assert client.get("/api/applications?q=glob", headers=h).json()["total"] == 1
    assert (
        client.get("/api/applications?limit=2&offset=4", headers=h).json()["items"].__len__() == 1
    )
    assert client.get("/api/applications?status=bogus", headers=h).status_code == 422


def test_detail_and_logs(client, auth, data):
    a = data["applied"]
    d = client.get(f"/api/applications/{a.id}", headers=auth).json()
    assert d["description"] == "desc" and d["job"]["company"] == "Acme"
    logs = client.get(f"/api/applications/{a.id}/logs", headers=auth).json()
    assert logs[0]["message"] == "applied ok" and logs[0]["has_screenshot"]


def test_approve_and_reject(client, auth, data, db_session):
    q = data["queued"]
    r = client.post(
        "/api/applications/approve", headers=auth, json={"ids": [q.id, data["applied"].id]}
    )
    assert r.json() == {"approved": [q.id]}  # only queued items can be approved
    db_session.refresh(q)
    assert q.approved and q.status == "queued"
    r = client.post(
        "/api/applications/reject", headers=auth, json={"ids": [q.id, data["applied"].id]}
    )
    assert r.json() == {"rejected": [q.id]}
    db_session.refresh(q)
    assert q.status == "skipped" and not q.approved
    assert (
        client.post("/api/applications/approve", headers=auth, json={"ids": []}).status_code == 422
    )


def test_answer_requeues_and_saves_to_bank(client, auth, data, db_session):
    a = data["needs_human"]
    r = client.post(f"/api/applications/{a.id}/answer", headers=auth, json={"answer": "30 days"})
    assert r.status_code == 200 and r.json()["status"] == "queued" and r.json()["approved"]
    entry = db_session.query(AnswerBankEntry).one()
    assert entry.answer == "30 days" and entry.patterns == ["notice period"]
    assert (
        client.post(
            f"/api/applications/{a.id}/answer", headers=auth, json={"answer": "x"}
        ).status_code
        == 409
    )
    # not saved when the user opts out
    b = data["failed"]
    assert (
        client.post(
            f"/api/applications/{b.id}/answer", headers=auth, json={"answer": "x"}
        ).status_code
        == 409
    )


def test_retry_failed(client, auth, data):
    f = data["failed"]
    r = client.post(f"/api/applications/{f.id}/retry", headers=auth)
    assert r.json()["status"] == "queued" and r.json()["approved"]
    assert (
        client.post(f"/api/applications/{data['applied'].id}/retry", headers=auth).status_code
        == 409
    )


def test_privacy_between_users(client, auth, data):
    client.post("/api/auth/register", json={"email": "o@example.com", "password": "password123"})
    t = client.post(
        "/api/auth/login", json={"email": "o@example.com", "password": "password123"}
    ).json()
    other = {"Authorization": f"Bearer {t['access_token']}"}
    assert client.get("/api/applications", headers=other).json()["total"] == 0
    assert client.get(f"/api/applications/{data['applied'].id}", headers=other).status_code == 404
    r = client.post("/api/applications/approve", headers=other, json={"ids": [data["queued"].id]})
    assert r.json() == {"approved": []}


def test_dashboard_stats(client, auth, data):
    s = client.get("/api/dashboard/stats?days=7", headers=auth).json()
    assert s["by_status"]["applied"] == 1 and s["by_status"]["queued"] == 1
    assert s["applied_by_site"] == {"naukri": 1}
    assert len(s["applied_per_day"]) == 7 and s["applied_per_day"][-1].get("naukri") == 1
    n1 = next(a for a in s["accounts"] if a["label"] == "N1")
    assert n1["applied_today"] == 1 and n1["cap"] == 10
    assert s["attention"] == {"awaiting_approval": 1, "needs_human": 1, "accounts_need_login": 1}
