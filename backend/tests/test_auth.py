def _register(client, email="a@example.com", pw="supersecret1"):
    return client.post("/api/auth/register", json={"email": email, "password": pw})


def _login(client, email="a@example.com", pw="supersecret1"):
    return client.post("/api/auth/login", json={"email": email, "password": pw})


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_register_login_me(client):
    r = _register(client)
    assert r.status_code == 201
    assert "password" not in r.text
    tokens = _login(client).json()
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me.status_code == 200 and me.json()["email"] == "a@example.com"


def test_duplicate_email_case_insensitive(client):
    _register(client)
    assert _register(client, email="A@Example.com").status_code == 409


def test_bad_password_and_short_password(client):
    _register(client)
    assert _login(client, pw="wrong-password").status_code == 401
    assert _register(client, email="b@example.com", pw="short").status_code == 422


def test_me_requires_auth(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_refresh_flow_and_token_type_separation(client):
    _register(client)
    t = _login(client).json()
    # refresh token must not work as access token
    bad = client.get("/api/auth/me", headers={"Authorization": f"Bearer {t['refresh_token']}"})
    assert bad.status_code == 401
    # access token must not work as refresh token
    assert (
        client.post("/api/auth/refresh", json={"refresh_token": t["access_token"]}).status_code
        == 401
    )
    ok = client.post("/api/auth/refresh", json={"refresh_token": t["refresh_token"]})
    assert ok.status_code == 200
    new = ok.json()["access_token"]
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {new}"}).status_code == 200
