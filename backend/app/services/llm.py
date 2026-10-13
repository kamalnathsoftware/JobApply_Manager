"""LLM access behind one tiny interface (`complete_json`) so the rest of the app -- and the
tests -- do not care which provider is configured.

Providers (LLM_PROVIDER): gemini | groq | ollama | anthropic."""

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
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
DEFAULT_ERRORS = {
    "gemini": "GEMINI_API_KEY is not configured (free key: aistudio.google.com)",
    "groq": "GROQ_API_KEY is not configured (free key: console.groq.com)",
    "anthropic": "ANTHROPIC_API_KEY is not configured",
}


@dataclass
class ProviderConfig:
    provider: str
    api_key: str = ""
    model: str = ""  # blank -> default from settings
    base_url: str = ""  # ollama only


def default_model(provider: str) -> str:
    s = get_settings()
    return {
        "gemini": s.gemini_model,
        "groq": s.groq_model,
        "ollama": s.ollama_model,
        "anthropic": s.anthropic_model,
    }.get(provider, "")


def env_key(provider: str) -> str:
    s = get_settings()
    return {
        "gemini": s.gemini_api_key,
        "groq": s.groq_api_key,
        "anthropic": s.anthropic_api_key,
    }.get(provider, "")


def env_chain() -> list[ProviderConfig]:
    """LLM_PROVIDER may list several providers: 'gemini,groq,ollama' = try in that order."""
    names = [n.strip().lower() for n in get_settings().llm_provider.split(",") if n.strip()]
    return [ProviderConfig(n) for n in names]


def build_single(cfg: ProviderConfig) -> LLMClient:
    s = get_settings()
    p = cfg.provider.lower()
    key = cfg.api_key or env_key(p)
    model = cfg.model or default_model(p)
    if p == "gemini":
        return GeminiLLM(key, model)
    if p == "groq":
        if not key:
            raise LLMError(DEFAULT_ERRORS["groq"])
        return OpenAICompatLLM("https://api.groq.com/openai/v1", model, key)
    if p == "ollama":
        return OpenAICompatLLM(cfg.base_url or s.ollama_base_url, model)
    if p == "anthropic":
        return AnthropicLLM(key, model)
    raise LLMError(f"Unknown LLM_PROVIDER '{cfg.provider}' (use one of {', '.join(PROVIDERS)})")


class FallbackLLM:
    """Tries providers in order; a failure (rate limit, denied key, bad JSON, offline...)
    moves on to the next one. `used` names the provider that answered the last call."""

    def __init__(self, clients: list[tuple[str, LLMClient]]):
        self.clients = clients
        self.used: str | None = None

    @property
    def model(self) -> str:
        name = self.used or self.clients[0][0]
        return next(c.model for n, c in self.clients if n == name)

    def complete_json(self, system: str, user: str, max_tokens: int = 8000) -> dict | list:
        errors = []
        for name, client in self.clients:
            try:
                out = client.complete_json(system, user, max_tokens)
                self.used = name
                return out
            except LLMError as e:
                errors.append(f"{name}: {e}")
        raise LLMError("all LLM providers failed - " + " | ".join(errors))


def build_llm(configs: list[ProviderConfig]) -> LLMClient:
    """Build one client, or a fallback chain, from the usable entries (in order)."""
    built: list[tuple[str, LLMClient]] = []
    errors: list[str] = []
    for cfg in configs:
        try:
            built.append((cfg.provider.lower(), build_single(cfg)))
        except LLMError as e:
            errors.append(str(e))
    if not built:
        raise LLMError("; ".join(errors) or "No LLM provider is configured")
    return built[0][1] if len(built) == 1 else FallbackLLM(built)


def get_llm() -> LLMClient:
    """Env-only factory (used when the user has not saved provider settings in the UI)."""
    return build_llm(env_chain())


def llm_info() -> dict:
    """Which providers the .env selects and whether any is usable (no secrets)."""
    chain = env_chain()
    usable = []
    for c in chain:
        try:
            build_single(c)
            usable.append(c.provider)
        except LLMError:
            pass
    first = chain[0].provider if chain else "?"
    return {
        "provider": ",".join(c.provider for c in chain),
        "model": default_model(first),
        "configured": bool(usable),
        "usable": usable,
    }
