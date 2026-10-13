from contextlib import nullcontext

import pytest
from apscheduler.schedulers.background import BackgroundScheduler

from app.core.db import get_session_factory
from app.main import app
from app.models import ApplicationLog, Schedule, ScheduleRun, SiteAccount
from app.workers import jobs
from app.workers.main import JOB_PREFIX, recover_interrupted_runs, sync_schedules


@pytest.fixture()
def auth(client):
    client.post("/api/auth/register", json={"email": "u@example.com", "password": "password123"})
    t = client.post(
        "/api/auth/login", json={"email": "u@example.com", "password": "password123"}
    ).json()
    return {"Authorization": f"Bearer {t['access_token']}", "token": t["access_token"]}


def H(auth):
    return {"Authorization": auth["Authorization"]}


@pytest.fixture()
def setup(client, auth):
    acct = client.post(
        "/api/accounts", headers=H(auth), json={"site": "naukri", "label": "n"}
    ).json()
    sp = client.post(
        "/api/search-profiles",
        headers=H(auth),
        json={"name": "Py", "keywords": [" python ", ""], "sites": ["naukri"], "location": "Pune"},
    ).json()
    return acct, sp


def body(acct, sp, **kw):
    return {
        "name": "Daily",
        "search_profile_id": sp["id"],
        "account_ids": [acct["id"]],
        "mode": "review",
        "kind": "daily",
        "time_of_day": "09:00",
        "timezone": "Asia/Kolkata",
    } | kw


def test_search_profile_crud_and_validation(client, auth):
    h = H(auth)
    r = client.post(
        "/api/search-profiles", headers=h, json={"name": "a", "keywords": [" python ", " "]}
    )
    assert r.status_code == 201 and r.json()["keywords"] == ["python"]
    assert (
        client.post(
            "/api/search-profiles", headers=h, json={"name": "a", "keywords": []}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/search-profiles",
            headers=h,
            json={"name": "a", "keywords": ["x"], "sites": ["monster"]},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/search-profiles",
            headers=h,
            json={"name": "a", "keywords": ["x"], "experience_min": 5, "experience_max": 2},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/search-profiles",
            headers=h,
            json={"name": "a", "keywords": ["x"], "company_urls": ["ftp://x"]},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/search-profiles",
            headers=h,
            json={"name": "a", "keywords": ["x"], "account_id": 99},
        ).status_code
        == 422
    )
    pid = r.json()["id"]
    r = client.put(f"/api/search-profiles/{pid}", headers=h, json={"name": "b", "keywords": ["go"]})
    assert r.json()["name"] == "b"
    assert client.delete(f"/api/search-profiles/{pid}", headers=h).status_code == 204


def test_schedule_crud_and_validation(client, auth, setup):
    acct, sp = setup
    h = H(auth)
    r = client.post("/api/schedules", headers=h, json=body(acct, sp))
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["next_run_at"] is not None and s["max_concurrency"] == 3 and s["match_threshold"] == 60
    bad = [
        body(acct, sp, time_of_day="25:61"),
        body(acct, sp, kind="cron", cron_expr="nope"),
        body(acct, sp, timezone="Mars/Base"),
        body(acct, sp, account_ids=[999]),
        body(acct, sp, search_profile_id=999),
        body(acct, sp, mode="yolo"),
        body(acct, sp, account_ids=[]),
        body(acct, sp, match_threshold=101),
    ]
    for b in bad:
        assert client.post("/api/schedules", headers=h, json=b).status_code == 422, b
    r = client.put(
        f"/api/schedules/{s['id']}", headers=h, json=body(acct, sp, enabled=False, mode="auto")
    )
    assert r.json()["next_run_at"] is None and r.json()["mode"] == "auto"
    assert len(client.get("/api/schedules", headers=h).json()) == 1
    assert client.delete(f"/api/schedules/{s['id']}", headers=h).status_code == 204


def test_other_users_cannot_use_my_accounts(client, auth, setup):
    acct, sp = setup
    client.post("/api/auth/register", json={"email": "o@example.com", "password": "password123"})
    t = client.post(
        "/api/auth/login", json={"email": "o@example.com", "password": "password123"}
    ).json()
    other = {"Authorization": f"Bearer {t['access_token']}"}
    assert client.post("/api/schedules", headers=other, json=body(acct, sp)).status_code == 422
    sid = client.post("/api/schedules", headers=H(auth), json=body(acct, sp)).json()["id"]
    assert client.post(f"/api/schedules/{sid}/run", headers=other).status_code == 404


def test_run_now_creates_pending_run_once(client, auth, setup, db_session):
    acct, sp = setup
    sid = client.post("/api/schedules", headers=H(auth), json=body(acct, sp)).json()["id"]
    r = client.post(f"/api/schedules/{sid}/run", headers=H(auth))
    assert (
        r.status_code == 202 and r.json()["status"] == "pending" and r.json()["trigger"] == "manual"
    )
    assert client.post(f"/api/schedules/{sid}/run", headers=H(auth)).status_code == 409
    assert len(client.get("/api/runs", headers=H(auth)).json()) == 1
    # worker side: atomic claim
    assert jobs.claim_pending_run(lambda: nullcontext(db_session)) == r.json()["id"]
    assert jobs.claim_pending_run(lambda: nullcontext(db_session)) is None
    assert client.get(f"/api/runs/{r.json()['id']}", headers=H(auth)).json()["status"] == "running"


def test_run_logs_and_sse_stream(client, auth, setup, db_session):
    acct, sp = setup
    sid = client.post("/api/schedules", headers=H(auth), json=body(acct, sp)).json()["id"]
    rid = client.post(f"/api/schedules/{sid}/run", headers=H(auth)).json()["id"]
    for i in range(3):
        db_session.add(ApplicationLog(schedule_run_id=rid, message=f"line {i}"))
    run = db_session.get(ScheduleRun, rid)
    run.status = "completed"
    db_session.commit()
    logs = client.get(f"/api/runs/{rid}/logs", headers=H(auth)).json()
    assert [entry["message"] for entry in logs] == ["line 0", "line 1", "line 2"]
    assert (
        client.get(f"/api/runs/{rid}/logs?after={logs[1]['id']}", headers=H(auth)).json()[0][
            "message"
        ]
        == "line 2"
    )

    app.dependency_overrides[get_session_factory] = lambda: lambda: nullcontext(db_session)
    try:
        # EventSource cannot send headers: token goes in the query string
        with client.stream("GET", f"/api/runs/{rid}/events?token={auth['token']}") as resp:
            assert resp.status_code == 200 and resp.headers["content-type"].startswith(
                "text/event-stream"
            )
            text = "".join(resp.iter_text())
        assert text.count("event: log") == 3 and "line 2" in text and "event: end" in text
        assert client.get(f"/api/runs/{rid}/events").status_code == 401
    finally:
        app.dependency_overrides.pop(get_session_factory, None)


def test_worker_sync_schedules_adds_updates_removes(client, auth, setup, db_session):
    acct, sp = setup
    s1 = client.post("/api/schedules", headers=H(auth), json=body(acct, sp)).json()
    s2 = client.post(
        "/api/schedules", headers=H(auth), json=body(acct, sp, name="off", enabled=False)
    ).json()
    sched = BackgroundScheduler()
    sched.start(paused=True)
    try:
        factory = lambda: nullcontext(db_session)  # noqa: E731
        sync_schedules(sched, factory)
        ids = {j.id for j in sched.get_jobs()}
        assert ids == {f"{JOB_PREFIX}{s1['id']}"}  # disabled schedule is not scheduled
        first_trigger = str(sched.get_job(f"{JOB_PREFIX}{s1['id']}").trigger)
        client.put(
            f"/api/schedules/{s1['id']}", headers=H(auth), json=body(acct, sp, time_of_day="18:45")
        )
        client.put(
            f"/api/schedules/{s2['id']}",
            headers=H(auth),
            json=body(acct, sp, name="on", kind="weekdays"),
        )
        sync_schedules(sched, factory)
        assert {j.id for j in sched.get_jobs()} == {
            f"{JOB_PREFIX}{s1['id']}",
            f"{JOB_PREFIX}{s2['id']}",
        }
        assert str(sched.get_job(f"{JOB_PREFIX}{s1['id']}").trigger) != first_trigger
        client.delete(f"/api/schedules/{s1['id']}", headers=H(auth))
        sync_schedules(sched, factory)
        assert {j.id for j in sched.get_jobs()} == {f"{JOB_PREFIX}{s2['id']}"}
    finally:
        sched.shutdown(wait=False)


def test_recover_interrupted_runs(client, auth, setup, db_session):
    acct, sp = setup
    sid = client.post("/api/schedules", headers=H(auth), json=body(acct, sp)).json()["id"]
    rid = client.post(f"/api/schedules/{sid}/run", headers=H(auth)).json()["id"]
    db_session.get(ScheduleRun, rid).status = "running"
    db_session.commit()
    recover_interrupted_runs(lambda: nullcontext(db_session))
    r = db_session.get(ScheduleRun, rid)
    assert r.status == "failed" and "restarted" in r.error


def test_enqueue_run_from_scheduler(client, auth, setup, db_session, monkeypatch):
    acct, sp = setup
    sid = client.post("/api/schedules", headers=H(auth), json=body(acct, sp)).json()["id"]
    monkeypatch.setattr(jobs, "SessionLocal", lambda: nullcontext(db_session))
    jobs.enqueue_run(sid)
    run = db_session.query(ScheduleRun).one()
    assert run.trigger == "schedule" and run.status == "pending"
    db_session.get(Schedule, sid).enabled = False
    db_session.commit()
    jobs.enqueue_run(sid)
    assert db_session.query(ScheduleRun).count() == 1  # disabled -> nothing queued
    _ = SiteAccount
