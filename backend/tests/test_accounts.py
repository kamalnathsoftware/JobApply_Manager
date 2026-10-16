import json

import pytest

from app.api import accounts as accounts_api
from app.models import SiteAccount, User
from app.services import accounts as svc
from app.workers.assisted_login import capture_session


@pytest.fixture()
def auth(client):
    client.post("/api/auth/register", json={"email": "u@example.com", "password": "password123"})
    t = client.post(
        "/api/auth/login", json={"email": "u@example.com", "password": "password123"}
    ).json()
    return {"Authorization": f"Bearer {t['access_token']}"}


def mk(client, auth, **kw):
    body = {"site": "naukri", "label": "Naukri main", "login_email": "me@example.com"} | kw
    return client.post("/api/accounts", headers=auth, json=body)


def test_create_list_update_delete(client, auth):
    r = mk(client, auth, password="s3cret-pw", daily_cap=10)
    assert r.status_code == 201
    a = r.json()
    assert a["has_password"] and not a["has_session"] and a["status"] == "new"
    assert "s3cret-pw" not in r.text
    assert len(client.get("/api/accounts", headers=auth).json()) == 1
    r = client.patch(
        f"/api/accounts/{a['id']}", headers=auth, json={"label": "Renamed", "daily_cap": 5}
    )
    assert r.json()["label"] == "Renamed" and r.json()["daily_cap"] == 5
    assert client.delete(f"/api/accounts/{a['id']}", headers=auth).status_code == 204
    assert client.get("/api/accounts", headers=auth).json() == []


def test_validation(client, auth):
    assert mk(client, auth, site="monster").status_code == 422
    assert mk(client, auth, daily_cap=0).status_code == 422
    assert mk(client, auth, resume_id=999).status_code == 422


def test_password_encrypted_at_rest(client, auth, db_session):
    mk(client, auth, password="s3cret-pw")
    row = db_session.query(SiteAccount).one()
    assert "s3cret-pw" not in row.credentials_enc
    assert svc.get_password(row) == "s3cret-pw"


def test_storage_state_encrypted_and_status(client, auth, db_session):
    mk(client, auth)
    row = db_session.query(SiteAccount).one()
    state = {
        "cookies": [{"name": "nauk_at", "value": "TOP-SECRET", "domain": ".naukri.com"}],
        "origins": [],
    }
    svc.save_storage_state(db_session, row, state, mark_login=True)
    assert "TOP-SECRET" not in row.storage_state_enc
    assert row.status == "active" and row.last_login_at is not None
    assert svc.get_storage_state(row) == state
    out = client.get("/api/accounts", headers=auth).json()[0]
    assert out["has_session"] and "TOP-SECRET" not in json.dumps(out)
    # a state without the login cookie -> needs_login
    svc.save_storage_state(db_session, row, {"cookies": [], "origins": []}, mark_login=True)
    assert row.status == "needs_login"
    out = client.post(f"/api/accounts/{row.id}/session/clear", headers=auth).json()
    assert out["status"] == "new" and not out["has_session"]


def test_start_login_spawns_once(client, auth, monkeypatch):
    spawned = []
    monkeypatch.setattr(accounts_api, "spawn_login_process", lambda aid: spawned.append(aid))
    monkeypatch.setattr(accounts_api, "_has_display", lambda: True)
    aid = mk(client, auth).json()["id"]
    r = client.post(f"/api/accounts/{aid}/login/start", headers=auth)
    assert r.status_code == 202 and r.json()["status"] == "login_in_progress"
    assert client.post(f"/api/accounts/{aid}/login/start", headers=auth).status_code == 409
    assert spawned == [aid]


def test_start_login_without_display(client, auth, monkeypatch):
    monkeypatch.setattr(accounts_api, "_has_display", lambda: False)
    aid = mk(client, auth).json()["id"]
    r = client.post(f"/api/accounts/{aid}/login/start", headers=auth)
    assert r.status_code == 409 and "display" in r.json()["detail"]


def test_accounts_private_per_user(client, auth):
    aid = mk(client, auth).json()["id"]
    client.post("/api/auth/register", json={"email": "o@example.com", "password": "password123"})
    t = client.post(
        "/api/auth/login", json={"email": "o@example.com", "password": "password123"}
    ).json()
    other = {"Authorization": f"Bearer {t['access_token']}"}
    assert (
        client.patch(f"/api/accounts/{aid}", headers=other, json={"label": "x"}).status_code == 404
    )
    assert client.post(f"/api/accounts/{aid}/login/start", headers=other).status_code == 404


class FakeCtx:
    def __init__(self, states):
        self.states, self.i = states, 0

    def storage_state(self):
        s = self.states[min(self.i, len(self.states) - 1)]
        self.i += 1
        if s is Exception:
            raise RuntimeError("closed")
        return s


class FakePage:
    def __init__(self, closed_after=10**9, urls=None):
        self.n, self.closed_after, self.urls = (
            0,
            closed_after,
            urls or ["https://www.naukri.com/nlogin/login"],
        )

    @property
    def url(self):
        return self.urls[min(self.n - 1, len(self.urls) - 1)]

    def is_closed(self):
        self.n += 1
        return self.n > self.closed_after


NO = {"cookies": [], "origins": []}
YES = {"cookies": [{"name": "nauk_at", "value": "v", "domain": ".naukri.com"}], "origins": []}
OTHER = {
    "cookies": [{"name": "some_other_cookie", "value": "v", "domain": ".naukri.com"}],
    "origins": [],
}


def test_capture_session_stops_on_login_cookie():
    ctx = FakeCtx([NO, NO, YES])
    out = capture_session(ctx, FakePage(), "naukri", sleep=lambda s: None)
    assert out.state == YES and out.logged_in


def test_capture_session_detects_login_from_url_even_if_cookie_name_differs():
    ctx = FakeCtx([NO, OTHER, OTHER])
    page = FakePage(
        urls=[
            "https://www.naukri.com/nlogin/login",
            "https://www.naukri.com/nlogin/login",
            "https://www.naukri.com/mnjuser/homepage",
        ]
    )
    out = capture_session(ctx, page, "naukri", sleep=lambda s: None)
    assert out.logged_in and out.state == OTHER


def test_looks_logged_in_urls():
    from app.workers.assisted_login import looks_logged_in

    assert looks_logged_in("naukri", "https://www.naukri.com/mnjuser/homepage")
    assert not looks_logged_in("naukri", "https://www.naukri.com/nlogin/login")
    assert looks_logged_in("linkedin", "https://www.linkedin.com/feed/")
    assert not looks_logged_in("linkedin", "https://www.linkedin.com/checkpoint/challenge/x")
    assert not looks_logged_in("linkedin", "https://www.linkedin.com/login")
    assert looks_logged_in("indeed", "https://in.indeed.com/")
    assert not looks_logged_in("indeed", "https://secure.indeed.com/auth")
    assert not looks_logged_in("company", "https://careers.x.com/feed")


def test_saved_state_marks_active_when_url_proves_login(db_session, client):
    client.post("/api/auth/register", json={"email": "u@example.com", "password": "password123"})
    uid = db_session.query(User).one().id
    acct = SiteAccount(user_id=uid, site="naukri", label="n")
    db_session.add(acct)
    db_session.commit()
    svc.save_storage_state(db_session, acct, OTHER, mark_login=True)  # unknown cookie, no proof
    assert acct.status == "needs_login"
    svc.save_storage_state(db_session, acct, OTHER, mark_login=True, logged_in=True)
    assert acct.status == "active" and acct.last_login_at is not None


def test_capture_session_keeps_last_snapshot_when_window_closed():
    ctx = FakeCtx([NO, YES])  # user logs in on a site without auto-detect, then closes window
    out = capture_session(ctx, FakePage(closed_after=2), "company", sleep=lambda s: None)
    assert out.state == YES and not out.logged_in


def test_capture_session_timeout_and_closed_browser():
    t = iter(range(0, 1000, 5))
    out = capture_session(
        FakeCtx([NO]),
        FakePage(),
        "naukri",
        timeout_s=20,
        sleep=lambda s: None,
        clock=lambda: next(t),
    )
    assert out.state == NO and not out.logged_in
    assert (
        capture_session(FakeCtx([Exception]), FakePage(), "naukri", sleep=lambda s: None).state
        is None
    )


def test_spawn_writes_a_log_file(tmp_path, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path))
    seen = {}

    class P:
        def __init__(self, cmd, stdout, stderr):
            seen["cmd"], seen["out"] = cmd, stdout.name

    monkeypatch.setattr(accounts_api.subprocess, "Popen", P)
    accounts_api.spawn_login_process(7)
    assert seen["out"].endswith("assisted_login_7.log") and "7" in seen["cmd"]
