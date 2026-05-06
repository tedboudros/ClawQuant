"""OpenAI LLM provider -- calls the OpenAI-compatible chat API via httpx.

No SDK dependency. Works with any OpenAI-compatible API (OpenAI, Azure, local).
"""

from __future__ import annotations

import json as _json
import logging
from typing import Any

import httpx

from core.protocols import LLMProviderError, ToolCallResult

logger = logging.getLogger(__name__)

_MAX_BODY_LOG_CHARS = 2000


def _extract_api_error(body: str) -> str:
    """Best-effort extraction of an OpenAI-shape error message."""
    try:
        data = _json.loads(body)
    except Exception:
        return body[:_MAX_BODY_LOG_CHARS]
    err = data.get("error") if isinstance(data, dict) else None
    if isinstance(err, dict):
        msg = err.get("message") or err.get("code") or ""
        if msg:
            return str(msg)
    if isinstance(err, str):
        return err
    return body[:_MAX_BODY_LOG_CHARS]

PLUGIN_META = {
    "name": "openai",
    "display_name": "OpenAI (GPT)",
    "description": "GPT models via the OpenAI API (also works with compatible APIs)",
    "category": "ai_provider",
    "protocols": ["llm"],
    "class_name": "OpenAIProvider",
    "pip_dependencies": [],
    "setup_instructions": """
1. Go to platform.openai.com
2. Navigate to API Keys
3. Create a new secret key
4. Paste it below
""",
    "config_fields": [
        {
            "key": "api_key",
            "label": "API Key",
            "type": "secret",
            "required": True,
            "env_var": "OPENAI_API_KEY",
            "description": "Your OpenAI API key",
            "placeholder": "sk-...",
        },
        {
            "key": "model",
            "label": "Model",
            "type": "string",
            "required": False,
            "default": "gpt-4o",
            "description": "Model name to use",
            "placeholder": "gpt-4o",
        },
    ],
}

_DEFAULT_URL = "https://api.openai.com/v1/chat/completions"


class OpenAIProvider:
    """LLM provider for OpenAI-compatible APIs.

    Implements the LLMProvider protocol.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o",
        base_url: str = _DEFAULT_URL,
        max_tokens: int = 4096,
    ) -> None:
        self._model = model
        self._max_tokens = max_tokens
        self._url = base_url
        self._client = httpx.AsyncClient(
            timeout=120.0,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

    @property
    def name(self) -> str:
        return "openai"

    async def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        """POST and parse JSON, translating failures into ``LLMProviderError``."""
        model = body.get("model", self._model)
        try:
            response = await self._client.post(self._url, json=body)
        except httpx.HTTPError as exc:
            logger.error(
                "OpenAI request transport error (model=%s): %s", model, exc,
            )
            raise LLMProviderError(
                f"network error contacting OpenAI: {exc}",
                provider=self.name,
                model=str(model),
            ) from exc

        if response.status_code >= 400:
            body_text = response.text or ""
            api_msg = _extract_api_error(body_text)
            logger.error(
                "OpenAI API error (model=%s, status=%d): %s",
                model,
                response.status_code,
                body_text[:_MAX_BODY_LOG_CHARS],
            )
            raise LLMProviderError(
                api_msg or response.reason_phrase or "request failed",
                provider=self.name,
                model=str(model),
                status_code=response.status_code,
                response_body=body_text,
            )

        try:
            return response.json()
        except ValueError as exc:
            logger.error(
                "OpenAI returned non-JSON response (model=%s): %s",
                model,
                response.text[:_MAX_BODY_LOG_CHARS],
            )
            raise LLMProviderError(
                "invalid JSON response from OpenAI",
                provider=self.name,
                model=str(model),
                status_code=response.status_code,
                response_body=response.text,
            ) from exc

    async def complete(self, messages: list[dict], **kwargs: Any) -> str:
        """Send messages and return the text response."""
        body = {
            "model": kwargs.get("model", self._model),
            "messages": messages,
            "max_tokens": kwargs.get("max_tokens", self._max_tokens),
        }

        data = await self._post(body)
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            logger.error(
                "OpenAI unexpected response shape (model=%s): %s",
                body["model"], data,
            )
            raise LLMProviderError(
                "unexpected response shape from OpenAI",
                provider=self.name,
                model=str(body["model"]),
                response_body=str(data)[:_MAX_BODY_LOG_CHARS],
            ) from exc

    async def tool_call(
        self,
        messages: list[dict],
        tools: list[dict],
        **kwargs: Any,
    ) -> ToolCallResult:
        """Send messages with tool definitions and return results."""
        body = {
            "model": kwargs.get("model", self._model),
            "messages": messages,
            "max_tokens": kwargs.get("max_tokens", self._max_tokens),
            "tools": tools,
        }

        data = await self._post(body)
        try:
            choice = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            logger.error(
                "OpenAI unexpected tool_call response shape (model=%s): %s",
                body["model"], data,
            )
            raise LLMProviderError(
                "unexpected response shape from OpenAI",
                provider=self.name,
                model=str(body["model"]),
                response_body=str(data)[:_MAX_BODY_LOG_CHARS],
            ) from exc

        usage = data.get("usage", {}) if isinstance(data, dict) else {}

        return ToolCallResult(
            text=choice.get("content", "") or "",
            tool_calls=choice.get("tool_calls", []),
            usage=usage,
        )

    async def close(self) -> None:
        await self._client.aclose()
