import json

import httpx
import pytest

from app.core.config import get_settings
from app.schemas.resume import ParsedResume
from app.services import llm as llm_mod
from app.services.llm import GeminiLLM, LLMError, OpenAICompatLLM, get_llm, llm_info
from app.services.matching import score_job
from tests.helpers import FakeLLM


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def gemini_reply(text):
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def openai_reply(text):
    return {"choices": [{"message": {"content": text}}]}


def test_gemini_request_shape_and_parse():
    seen = {}

    def handler(req: httpx.Request):
        seen["url"], seen["key"], seen["body"] = (
            str(req.url),
            req.headers["x-goog-api-key"],
            json.loads(req.content),
        )
        return httpx.Response(200, json=gemini_reply('{"score": 80}'))

    g = GeminiLLM("KEY123", "gemini-2.5-flash", client=client_for(handler))
    assert g.complete_json("sys", "user text") == {"score": 80}
    assert (
        seen["url"].endswith("/models/gemini-2.5-flash:generateContent")
        and "KEY123" not in seen["url"]
    )
    assert seen["key"] == "KEY123"
    b = seen["body"]
    assert b["contents"][0]["parts"][0]["text"] == "user text"
    assert "JSON" in b["systemInstruction"]["parts"][0]["text"]
    assert b["generationConfig"]["responseMimeType"] == "application/json"


def test_gemini_requires_key_and_reports_blocks():
    with pytest.raises(LLMError, match="GEMINI_API_KEY"):
        GeminiLLM("", "m")
    g = GeminiLLM(
        "k",
        "m",
        client=client_for(
            lambda r: httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}})
        ),
    )
    with pytest.raises(LLMError, match="SAFETY"):
        g.complete_json("s", "u")


def test_openai_compat_for_groq_and_ollama():
    seen = {}

    def handler(req: httpx.Request):
        seen["url"], seen["auth"], seen["body"] = (
            str(req.url),
            req.headers.get("authorization"),
            json.loads(req.content),
        )
        return httpx.Response(200, json=openai_reply('```json\n{"ok": true}\n```'))

    groq = OpenAICompatLLM(
        "https://api.groq.com/openai/v1/", "llama-x", "GK", client=client_for(handler)
    )
    assert groq.complete_json("s", "u") == {"ok": True}
    assert (
        seen["url"] == "https://api.groq.com/openai/v1/chat/completions"
        and seen["auth"] == "Bearer GK"
    )
    assert (
        seen["body"]["response_format"] == {"type": "json_object"}
        and seen["body"]["model"] == "llama-x"
    )
    ollama = OpenAICompatLLM("http://localhost:11434/v1", "qwen2.5:7b", client=client_for(handler))
    ollama.complete_json("s", "u")
    assert seen["auth"] is None  # no key for local Ollama


def test_invalid_json_is_retried_once():
    replies = iter(["Sorry, here you go: not json", '{"fixed": 1}'])
    calls = []

    def handler(req):
        calls.append(json.loads(req.content))
        return httpx.Response(200, json=openai_reply(next(replies)))

    out = OpenAICompatLLM("http://x/v1", "m", client=client_for(handler)).complete_json("s", "u")
    assert out == {"fixed": 1} and len(calls) == 2
    assert "not valid JSON" in calls[1]["messages"][1]["content"]


def test_invalid_json_twice_raises():
    h = lambda req: httpx.Response(200, json=openai_reply("nope"))  # noqa: E731
    with pytest.raises(LLMError):
        OpenAICompatLLM("http://x/v1", "m", client=client_for(h)).complete_json("s", "u")


def test_rate_limit_retries_with_retry_after_then_succeeds():
    seq = iter(
        [
            httpx.Response(429, headers={"retry-after": "3"}),
            httpx.Response(503),
            httpx.Response(200, json=openai_reply('{"a": 1}')),
        ]
    )
    sleeps = []
    c = OpenAICompatLLM(
        "http://x/v1", "m", client=client_for(lambda r: next(seq)), sleep=sleeps.append
    )
    assert c.complete_json("s", "u") == {"a": 1}
    assert sleeps[0] == 3.0 and len(sleeps) == 2


def test_persistent_rate_limit_gives_clear_error():
    c = OpenAICompatLLM(
        "http://x/v1", "m", client=client_for(lambda r: httpx.Response(429)), sleep=lambda s: None
    )
    with pytest.raises(LLMError, match="rate-limited"):
        c.complete_json("s", "u")


def test_client_error_and_unreachable():
    c = OpenAICompatLLM(
        "http://x/v1", "m", client=client_for(lambda r: httpx.Response(401, text="bad key"))
    )
    with pytest.raises(LLMError, match="401"):
        c.complete_json("s", "u")

    def boom(req):
        raise httpx.ConnectError("refused")

    with pytest.raises(LLMError, match="cannot reach"):
        OpenAICompatLLM("http://localhost:11434/v1", "m", client=client_for(boom)).complete_json(
            "s", "u"
        )


@pytest.mark.parametrize(
    "provider,key_attr,expected",
    [
        ("gemini", "gemini_api_key", GeminiLLM),
        ("groq", "groq_api_key", OpenAICompatLLM),
        ("ollama", None, OpenAICompatLLM),
    ],
)
def test_factory_selects_provider(monkeypatch, provider, key_attr, expected):
    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", provider)
    if key_attr:
        monkeypatch.setattr(s, key_attr, "k")
    assert isinstance(get_llm(), expected)
    assert llm_info()["provider"] == provider and llm_info()["configured"] is True
    assert "k" not in json.dumps({**llm_info(), "model": ""}) or key_attr is None


def test_factory_errors(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", "gemini")
    monkeypatch.setattr(s, "gemini_api_key", "")
    with pytest.raises(LLMError, match="GEMINI_API_KEY"):
        get_llm()
    assert llm_info()["configured"] is False
    monkeypatch.setattr(s, "llm_provider", "groq")
    monkeypatch.setattr(s, "groq_api_key", "")
    with pytest.raises(LLMError, match="GROQ_API_KEY"):
        get_llm()
    monkeypatch.setattr(s, "llm_provider", "skynet")
    with pytest.raises(LLMError, match="Unknown LLM_PROVIDER"):
        get_llm()
    assert llm_mod.llm_info()["configured"] is False


def test_system_info_endpoint(client):
    client.post("/api/auth/register", json={"email": "u@example.com", "password": "password123"})
    t = client.post(
        "/api/auth/login", json={"email": "u@example.com", "password": "password123"}
    ).json()
    r = client.get("/api/system/info", headers={"Authorization": f"Bearer {t['access_token']}"})
    assert r.status_code == 200 and set(r.json()["llm"]) == {"provider", "model", "configured"}
    assert client.get("/api/system/info").status_code == 401


def test_resume_schema_tolerates_sloppy_model_output():
    p = ParsedResume.model_validate(
        {
            "contact": {"name": "A", "phone": 9876543210, "email": None},
            "skills": "Python, FastAPI; MySQL",
            "certifications": None,
            "total_experience_years": "about 4.5 years",
            "experience": [
                {"company": "X", "start": 2020, "end": None, "highlights": "Built things"}
            ],
            "projects": [{"name": "P", "technologies": "Go, Rust"}],
        }
    )
    assert p.skills == ["Python", "FastAPI", "MySQL"] and p.certifications == []
    assert p.total_experience_years == 4.5 and p.contact.phone == "9876543210"
    assert p.experience[0].start == "2020" and p.experience[0].highlights == ["Built things"]
    assert p.projects[0].technologies == ["Go", "Rust"]


@pytest.mark.parametrize("raw,expected", [("85/100", 85), ("72%", 72), (" 90 ", 90)])
def test_score_accepts_string_scores(raw, expected):
    assert score_job(FakeLLM({"score": raw}), {}, {"title": "t"}).score == expected
