import httpx
import pytest

from app.core.config import get_settings
from app.models import LLMProviderSetting, User
from app.services import llm_config
from app.services.llm import (
    FallbackLLM,
    GeminiLLM,
    LLMError,
    OpenAICompatLLM,
    ProviderConfig,
    build_llm,
    env_chain,
    llm_info,
)
from tests.helpers import FakeLLM


class Boom:
    model = "boom-model"

    def __init__(self, msg="denied"):
        self.msg, self.calls = msg, 0

    def complete_json(self, system, user, max_tokens=8000):
        self.calls += 1
        raise LLMError(self.msg)


def test_fallback_moves_to_next_provider_and_remembers_who_answered():
    bad, good = Boom("403 denied"), FakeLLM({"ok": 1})
    chain = FallbackLLM([("gemini", bad), ("groq", good)])
    assert chain.complete_json("s", "u") == {"ok": 1}
    assert chain.used == "groq" and bad.calls == 1 and chain.model == "fake-model"


def test_fallback_all_fail_lists_every_reason():
    chain = FallbackLLM([("gemini", Boom("403")), ("groq", Boom("429 slow"))])
    with pytest.raises(LLMError) as e:
        chain.complete_json("s", "u")
    assert "gemini: 403" in str(e.value) and "groq: 429 slow" in str(e.value)


def test_env_comma_list_builds_chain_skipping_unusable(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", "gemini, groq ,ollama")
    monkeypatch.setattr(s, "gemini_api_key", "")  # unusable -> skipped
    monkeypatch.setattr(s, "groq_api_key", "gk")
    assert [c.provider for c in env_chain()] == ["gemini", "groq", "ollama"]
    llm = build_llm(env_chain())
    assert isinstance(llm, FallbackLLM) and [n for n, _ in llm.clients] == ["groq", "ollama"]
    info = llm_info()
    assert info["usable"] == ["groq", "ollama"] and info["configured"]


def test_single_usable_provider_is_not_wrapped():
    assert isinstance(build_llm([ProviderConfig("gemini", "k")]), GeminiLLM)
    c = build_llm([ProviderConfig("ollama", base_url="http://pc:11434/v1/", model="llama3")])
    assert (
        isinstance(c, OpenAICompatLLM)
        and c.base_url == "http://pc:11434/v1"
        and c.model == "llama3"
    )


def test_explicit_config_overrides_env_defaults():
    c = build_llm([ProviderConfig("groq", "mykey", "custom-model")])
    assert c.api_key == "mykey" and c.model == "custom-model"


@pytest.fixture()
def auth(client):
    client.post("/api/auth/register", json={"email": "u@example.com", "password": "password123"})
    t = client.post(
        "/api/auth/login", json={"email": "u@example.com", "password": "password123"}
    ).json()
    return {"Authorization": f"Bearer {t['access_token']}"}


def test_providers_api_defaults_to_env_then_saves_to_db(client, auth, db_session, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", "gemini")
    monkeypatch.setattr(s, "gemini_api_key", "env-key")
    v = client.get("/api/llm/providers", headers=auth).json()
    assert v["source"] == "env" and [p["provider"] for p in v["providers"]][0] == "gemini"
    gem = next(p for p in v["providers"] if p["provider"] == "gemini")
    assert gem["enabled"] and gem["env_key"] and not gem["has_key"]

    body = [
        {"provider": "groq", "enabled": True, "priority": 0, "api_key": "gsk-SECRET-VALUE"},
        {"provider": "gemini", "enabled": True, "priority": 1, "model": "gemini-x"},
        {"provider": "ollama", "enabled": False, "priority": 2, "base_url": "http://pc:11434/v1"},
        {"provider": "anthropic", "enabled": False, "priority": 3},
    ]
    r = client.put("/api/llm/providers", headers=auth, json=body)
    assert r.status_code == 200 and r.json()["source"] == "ui"
    assert "gsk-SECRET-VALUE" not in r.text  # keys are never returned
    order = [(p["provider"], p["enabled"], p["has_key"]) for p in r.json()["providers"]]
    assert order[:2] == [("groq", True, True), ("gemini", True, False)]
    # encrypted at rest
    row = db_session.query(LLMProviderSetting).filter_by(provider="groq").one()
    assert "SECRET" not in row.api_key_enc and llm_config.row_key(row) == "gsk-SECRET-VALUE"
    # key=None keeps, key="" removes
    client.put("/api/llm/providers", headers=auth, json=[{"provider": "groq", "priority": 0}])
    assert (
        llm_config.row_key(db_session.query(LLMProviderSetting).filter_by(provider="groq").one())
        == "gsk-SECRET-VALUE"
    )
    client.put(
        "/api/llm/providers",
        headers=auth,
        json=[{"provider": "groq", "priority": 0, "api_key": ""}],
    )
    assert db_session.query(LLMProviderSetting).filter_by(provider="groq").one().api_key_enc is None
    # reset goes back to .env
    assert client.delete("/api/llm/providers", headers=auth).json()["source"] == "env"
    assert db_session.query(LLMProviderSetting).count() == 0


def test_user_configs_resolution_order_and_disabled(client, auth, db_session):
    uid = db_session.query(User).one().id
    client.put(
        "/api/llm/providers",
        headers=auth,
        json=[
            {"provider": "gemini", "priority": 2, "api_key": "g"},
            {"provider": "groq", "priority": 1, "api_key": "q", "model": "m1"},
            {"provider": "anthropic", "enabled": False, "priority": 0, "api_key": "a"},
        ],
    )
    cfgs = llm_config.user_configs(db_session, uid)
    assert [(c.provider, c.api_key, c.model) for c in cfgs] == [
        ("groq", "q", "m1"),
        ("gemini", "g", ""),
    ]
    llm = llm_config.llm_for_user(db_session, uid)
    assert isinstance(llm, FallbackLLM) and [n for n, _ in llm.clients] == ["groq", "gemini"]
    client.put(
        "/api/llm/providers",
        headers=auth,
        json=[{"provider": p, "enabled": False} for p in ("gemini", "groq")],
    )
    with pytest.raises(LLMError, match="No LLM provider is enabled"):
        llm_config.llm_for_user(db_session, uid)


def test_provider_test_endpoint(client, auth, monkeypatch):
    def handler(req):
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]})

    real = OpenAICompatLLM.__init__

    def patched(self, *a, **kw):
        kw["client"] = httpx.Client(transport=httpx.MockTransport(handler))
        real(self, *a, **kw)

    monkeypatch.setattr(OpenAICompatLLM, "__init__", patched)
    client.put("/api/llm/providers", headers=auth, json=[{"provider": "ollama", "priority": 0}])
    r = client.post("/api/llm/test?provider=ollama", headers=auth).json()
    assert r["ok"] and r["provider"] == "ollama"
    assert client.post("/api/llm/test", headers=auth).json()["ok"]
    bad = client.post("/api/llm/test?provider=gemini", headers=auth).json()  # no key anywhere
    assert bad["ok"] is False and "GEMINI_API_KEY" in bad["error"]
    assert client.post("/api/llm/test").status_code == 401
    assert (
        client.put("/api/llm/providers", headers=auth, json=[{"provider": "skynet"}]).status_code
        == 422
    )


def test_optional_llm_uses_the_users_saved_providers(client, auth, db_session, monkeypatch):
    from app.api.deps import optional_llm

    uid = db_session.query(User).one().id
    client.put("/api/llm/providers", headers=auth, json=[{"provider": "ollama", "priority": 0}])
    got = optional_llm(db_session.get(User, uid), db_session)
    assert isinstance(got, OpenAICompatLLM)
    client.put("/api/llm/providers", headers=auth, json=[{"provider": "ollama", "enabled": False}])
    assert optional_llm(db_session.get(User, uid), db_session) is None


GROQ_MODELS = {
    "data": [
        {"id": "whisper-large-v3"},
        {"id": "llama-3.1-8b-instant"},
        {"id": "llama-3.4-70b-versatile"},
        {"id": "meta-llama/llama-guard-4-12b"},
    ]
}


def _groq_handler(calls):
    def handler(req: httpx.Request):
        calls.append((req.method, req.url.path))
        if req.method == "GET":
            return httpx.Response(200, json=GROQ_MODELS)
        body = __import__("json").loads(req.content)
        if body["model"] == "llama-3.3-70b-versatile":
            return httpx.Response(
                404,
                text='{"error":{"message":"The model `x` does not exist","code":"model_not_found"}}',
            )
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"used": "' + body["model"] + '"}'}}]}
        )

    return handler


def test_missing_model_is_replaced_by_one_the_provider_offers():
    calls = []
    OpenAICompatLLM._resolved.clear()
    mk = lambda: OpenAICompatLLM(  # noqa: E731
        "https://api.groq.com/openai/v1",
        "llama-3.3-70b-versatile",
        "k",
        client=httpx.Client(transport=httpx.MockTransport(_groq_handler(calls))),
    )
    llm = mk()
    assert llm.complete_json("s", "u") == {
        "used": "llama-3.4-70b-versatile"
    }  # whisper/guard skipped
    assert llm.model == "llama-3.4-70b-versatile"
    assert [c[0] for c in calls] == ["POST", "GET", "POST"]
    # remembered: a new client goes straight to the working model, no 404 round trip
    calls.clear()
    assert mk().complete_json("s", "u") == {"used": "llama-3.4-70b-versatile"}
    assert calls == [("POST", "/openai/v1/chat/completions")]
    OpenAICompatLLM._resolved.clear()


def test_no_usable_model_gives_clear_message():
    OpenAICompatLLM._resolved.clear()

    def handler(req):
        if req.method == "GET":
            return httpx.Response(200, json={"data": [{"id": "whisper-large-v3"}]})
        return httpx.Response(
            404, text='{"error":{"code":"model_not_found","message":"model gone"}}'
        )

    llm = OpenAICompatLLM(
        "https://api.groq.com/openai/v1",
        "gone",
        "k",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(LLMError):
        llm.complete_json("s", "u")


def test_gemini_model_gone_switches_to_listed_flash_model():
    GeminiLLM._resolved.clear()
    seen = []

    def handler(req: httpx.Request):
        seen.append(req.method + " " + req.url.path)
        if req.method == "GET":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": "models/gemini-9-flash-lite",
                            "supportedGenerationMethods": ["generateContent"],
                        },
                        {
                            "name": "models/gemini-9-flash",
                            "supportedGenerationMethods": ["generateContent"],
                        },
                        {
                            "name": "models/text-embedding-9",
                            "supportedGenerationMethods": ["embedContent"],
                        },
                    ]
                },
            )
        if "gemini-2.5-flash" in req.url.path:
            return httpx.Response(
                404,
                text='{"error":{"message":"This model models/gemini-2.5-flash is no longer available"}}',
            )
        return httpx.Response(200, json=gemini_ok)

    gemini_ok = {"candidates": [{"content": {"parts": [{"text": '{"fine": true}'}]}}]}
    g = GeminiLLM(
        "k", "gemini-2.5-flash", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    assert g.complete_json("s", "u") == {"fine": True} and g.model == "gemini-9-flash"
    assert seen[-1].endswith("gemini-9-flash:generateContent")
    GeminiLLM._resolved.clear()


def test_models_endpoint(client, auth, monkeypatch):
    def handler(req):
        return httpx.Response(200, json=GROQ_MODELS)

    real = OpenAICompatLLM.__init__

    def patched(self, *a, **kw):
        kw["client"] = httpx.Client(transport=httpx.MockTransport(handler))
        real(self, *a, **kw)

    monkeypatch.setattr(OpenAICompatLLM, "__init__", patched)
    client.put("/api/llm/providers", headers=auth, json=[{"provider": "groq", "api_key": "k"}])
    r = client.get("/api/llm/models?provider=groq", headers=auth).json()
    assert "llama-3.1-8b-instant" in r["models"]
    bad = client.get("/api/llm/models?provider=gemini", headers=auth).json()
    assert bad["models"] == [] and "GEMINI_API_KEY" in bad["error"]
