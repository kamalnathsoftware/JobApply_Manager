import os
import time

import pytest

from app.api import system as system_api
from app.core.config import get_settings
from app.models import ScheduleRun
from app.services import worker_status


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


def test_heartbeat_alive_then_stale():
    assert not worker_status.worker_alive() and worker_status.heartbeat_age() is None
    worker_status.touch_heartbeat()
    assert worker_status.worker_alive()
    old = time.time() - 60
    os.utime(worker_status.heartbeat_path(), (old, old))
    assert not worker_status.worker_alive()


def test_worker_endpoints(client, auth, monkeypatch):
    assert client.get("/api/system/worker", headers=auth).json() == {"alive": False, "age_s": None}
    spawned = []
    monkeypatch.setattr(system_api.worker_status, "spawn_worker", lambda: spawned.append(1))
    assert client.post("/api/system/worker/start", headers=auth).json()["started"] is True
    worker_status.touch_heartbeat()
    assert client.get("/api/system/worker", headers=auth).json()["alive"] is True
    assert client.post("/api/system/worker/start", headers=auth).json()["started"] is False
    assert spawned == [1]


def test_cancel_pending_run_unblocks_run_now(client, auth, db_session):
    a = client.post("/api/accounts", headers=auth, json={"site": "naukri", "label": "n"}).json()
    sp = client.post(
        "/api/search-profiles", headers=auth, json={"name": "p", "keywords": ["qa"]}
    ).json()
    sid = client.post(
        "/api/schedules",
        headers=auth,
        json={
            "name": "s",
            "search_profile_id": sp["id"],
            "account_ids": [a["id"]],
            "time_of_day": "09:00",
        },
    ).json()["id"]
    rid = client.post(f"/api/schedules/{sid}/run", headers=auth).json()["id"]
    assert client.post(f"/api/schedules/{sid}/run", headers=auth).status_code == 409
    out = client.post(f"/api/runs/{rid}/cancel", headers=auth).json()
    assert out["status"] == "failed" and out["error"] == "cancelled by user"
    assert client.post(f"/api/runs/{rid}/cancel", headers=auth).status_code == 409
    assert client.post(f"/api/schedules/{sid}/run", headers=auth).status_code == 202
    db_session.expire_all()
    assert db_session.query(ScheduleRun).count() == 2


def test_api_applies_pending_migrations_on_startup(tmp_path, monkeypatch):
    import sqlalchemy as sa
    from fastapi.testclient import TestClient

    from app.main import app

    db = tmp_path / "fresh.db"
    monkeypatch.setattr(get_settings(), "database_url", f"sqlite:///{db}")
    import alembic.context  # noqa: F401  (env.py reads the url at import time via get_settings)

    with TestClient(app):  # entering the context runs the lifespan
        pass
    tables = sa.inspect(sa.create_engine(f"sqlite:///{db}")).get_table_names()
    assert "personal_details" in tables and "alembic_version" in tables
