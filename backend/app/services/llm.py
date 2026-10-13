"""Thin wrapper around the Anthropic API so the rest of the app (and tests) depend on a
small interface instead of the SDK."""

import json
import re
from typing import Protocol

from app.core.config import get_settings


class LLMError(Exception):
    pass


class LLMClient(Protocol):
    model: str

    def complete_json(self, system: str, user: str, max_tokens: int = 8000) -> dict | list: ...


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)


def extract_json(text: str) -> dict | list:
    """Parse JSON from a model reply, tolerating code fences and surrounding prose."""
    text = _FENCE.sub("", text.strip())
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


class AnthropicLLM:
    def __init__(self, api_key: str | None = None, model: str | None = None):
        import anthropic

        s = get_settings()
        key = api_key or s.anthropic_api_key
        if not key:
            raise LLMError("ANTHROPIC_API_KEY is not configured")
        self._client = anthropic.Anthropic(api_key=key)
        self.model = model or s.anthropic_model

    def complete_json(self, system: str, user: str, max_tokens: int = 8000) -> dict | list:
        import anthropic

        system = system + "\n\nReply with a single valid JSON value and nothing else."
        try:
            msg = self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except anthropic.APIError as e:
            raise LLMError(f"Anthropic API error: {e}") from e
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        if msg.stop_reason == "max_tokens":
            raise LLMError("model reply was truncated (max_tokens)")
        return extract_json(text)


def get_llm() -> LLMClient:
    """FastAPI dependency / factory; tests override this."""
    return AnthropicLLM()
