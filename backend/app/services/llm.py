"""LLM access behind one tiny interface (`complete_json`) so the rest of the app -- and the
tests -- do not care which provider is configured.

Providers (LLM_PROVIDER): gemini | groq | ollama | anthropic."""

import json
import re
import time
from collections.abc import Callable
from typing import Protocol

import httpx

from app.core.config import get_settings


class LLMError(Exception):
    pass


class LLMClient(Protocol):
    model: str

    def complete_json(self, system: str, user: str, max_tokens: int = 8000) -> dict | list: ...


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)
JSON_ONLY = "\n\nReply with a single valid JSON value and nothing else."


def extract_json(text: str) -> dict | list:
    """Parse JSON from a model reply, tolerating code fences and surrounding prose."""
    text = _FENCE.sub("", (text or "").strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    starts = [i for i in (text.find("{"), text.find("[")) if i != -1]
    if not starts:
        raise LLMError("model reply did not contain JSON")
    start = min(starts)
    end = max(text.rfind("}"), text.rfind("]"))
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as e:
        raise LLMError(f"invalid JSON in model reply: {e}") from e


class _JsonLLM:
    """Shared behaviour: ask for JSON, retry once if the reply is not valid JSON (small and
    free models slip now and then)."""

    model: str

    def _chat(self, system: str, user: str, max_tokens: int) -> str:
        raise NotImplementedError

    def complete_json(self, system: str, user: str, max_tokens: int = 8000) -> dict | list:
        try:
            return extract_json(self._chat(system + JSON_ONLY, user, max_tokens))
        except LLMError:
            retry_user = user + "\n\nYour previous reply was not valid JSON. Reply with JSON only."
            return extract_json(self._chat(system + JSON_ONLY, retry_user, max_tokens))


class _HttpLLM(_JsonLLM):
    """Adds a polite POST with retries for rate limits (free tiers have tight limits)."""

    MAX_TRIES = 4

    def __init__(
        self, client: httpx.Client | None = None, sleep: Callable[[float], None] = time.sleep
    ):
        self._http = client or httpx.Client(timeout=120)
        self._sleep = sleep

    def _post(self, url: str, *, headers: dict, body: dict) -> dict:
        last = ""
        for attempt in range(self.MAX_TRIES):
            try:
                r = self._http.post(url, headers=headers, json=body)
            except httpx.HTTPError as e:
                raise LLMError(f"cannot reach the LLM service: {e}") from e
            if r.status_code in (429, 500, 502, 503, 504):
                last = f"HTTP {r.status_code}"
                try:
                    wait = float(r.headers.get("retry-after", ""))
                except ValueError:
                    wait = 2.0 * (2**attempt)
                self._sleep(min(wait, 30.0))
                continue
            if r.status_code >= 400:
                raise LLMError(f"LLM service error {r.status_code}: {r.text[:300]}")
            try:
                return r.json()
            except ValueError as e:
                raise LLMError("LLM service returned a non-JSON response") from e
        raise LLMError(f"LLM service busy or rate-limited ({last}); try again later")


class GeminiLLM(_HttpLLM):
    def __init__(self, api_key: str, model: str, **kw):
        super().__init__(**kw)
        if not api_key:
            raise LLMError("GEMINI_API_KEY is not configured (free key: aistudio.google.com)")
        self.api_key, self.model = api_key, model

    def _chat(self, system: str, user: str, max_tokens: int) -> str:
        data = self._post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
            headers={"x-goog-api-key": self.api_key},
            body={
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "maxOutputTokens": max_tokens,
                    "temperature": 0.1,
                },
            },
        )
        try:
            cand = data["candidates"][0]
            return "".join(p.get("text", "") for p in cand["content"]["parts"])
        except (KeyError, IndexError, TypeError) as e:
            reason = (data.get("promptFeedback") or {}).get("blockReason", "no candidates")
            raise LLMError(f"Gemini returned no answer ({reason})") from e


class OpenAICompatLLM(_HttpLLM):
    """Groq and Ollama both expose the OpenAI-style /chat/completions endpoint."""

    def __init__(self, base_url: str, model: str, api_key: str = "", **kw):
        super().__init__(**kw)
        self.base_url, self.model, self.api_key = base_url.rstrip("/"), model, api_key

    def _chat(self, system: str, user: str, max_tokens: int) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        data = self._post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            body={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "response_format": {"type": "json_object"},
                "max_tokens": max_tokens,
                "temperature": 0.1,
            },
        )
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError("LLM service returned an unexpected response shape") from e


class AnthropicLLM(_JsonLLM):
    def __init__(self, api_key: str | None = None, model: str | None = None):
        import anthropic

        s = get_settings()
        key = api_key or s.anthropic_api_key
        if not key:
            raise LLMError("ANTHROPIC_API_KEY is not configured")
        self._client = anthropic.Anthropic(api_key=key)
        self.model = model or s.anthropic_model

    def _chat(self, system: str, user: str, max_tokens: int) -> str:
        import anthropic

        try:
            msg = self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except anthropic.APIError as e:
            raise LLMError(f"Anthropic API error: {e}") from e
        if msg.stop_reason == "max_tokens":
            raise LLMError("model reply was truncated (max_tokens)")
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


PROVIDERS = ("gemini", "groq", "ollama", "anthropic")


def llm_info() -> dict:
    """Which provider/model is configured and whether it looks usable (no secrets)."""
    s = get_settings()
    p = s.llm_provider.lower()
    model = {
        "gemini": s.gemini_model,
        "groq": s.groq_model,
        "ollama": s.ollama_model,
        "anthropic": s.anthropic_model,
    }.get(p, "?")
    key = {
        "gemini": s.gemini_api_key,
        "groq": s.groq_api_key,
        "ollama": "n/a",
        "anthropic": s.anthropic_api_key,
    }.get(p, "")
    return {"provider": p, "model": model, "configured": p in PROVIDERS and bool(key)}


def get_llm() -> LLMClient:
    """FastAPI dependency / factory; tests override this."""
    s = get_settings()
    p = s.llm_provider.lower()
    if p == "gemini":
        return GeminiLLM(s.gemini_api_key, s.gemini_model)
    if p == "groq":
        if not s.groq_api_key:
            raise LLMError("GROQ_API_KEY is not configured (free key: console.groq.com)")
        return OpenAICompatLLM("https://api.groq.com/openai/v1", s.groq_model, s.groq_api_key)
    if p == "ollama":
        return OpenAICompatLLM(s.ollama_base_url, s.ollama_model)
    if p == "anthropic":
        return AnthropicLLM()
    raise LLMError(f"Unknown LLM_PROVIDER '{s.llm_provider}' (use one of {', '.join(PROVIDERS)})")
