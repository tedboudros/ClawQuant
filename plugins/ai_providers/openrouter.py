"""OpenRouter LLM provider -- unified API for many models via a single endpoint.

OpenRouter provides access to OpenAI, Anthropic, Google, Meta, and many other
models through one API. Uses OpenAI-compatible chat completions format.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from core.protocols import LLMProviderError, ToolCallResult

logger = logging.getLogger(__name__)

_MAX_BODY_LOG_CHARS = 2000


def _extract_api_error(body: str) -> str:
    """Best-effort extraction of an OpenRouter / OpenAI-shape error message."""
    import json as _json
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
    "name": "openrouter",
    "display_name": "OpenRouter",
    "description": "Unified API for multiple LLM providers (OpenAI, Anthropic, Google, Meta, etc.)",
    "category": "ai_provider",
    "protocols": ["llm"],
    "class_name": "OpenRouterProvider",
    "pip_dependencies": [],
    "setup_instructions": """
1. Go to openrouter.ai
2. Sign up or log in
3. Navigate to Keys section
4. Create a new API key
5. Paste it below

OpenRouter provides access to many models through one API (e.g., openai/gpt-4o).
""",
    "config_fields": [
        {
            "key": "api_key",
            "label": "API Key",
            "type": "secret",
            "required": True,
            "env_var": "OPENROUTER_API_KEY",
            "description": "Your OpenRouter API key",
            "placeholder": "sk-or-v1-...",
        },
        {
            "key": "model",
            "label": "Model",
            "type": "string",
            "required": False,
            "default": "openai/gpt-4o",
            "description": "Model identifier (provider/model format)",
            "placeholder": "openai/gpt-4o",
        },
    ],
}

_DEFAULT_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterProvider:
    """LLM provider for OpenRouter's unified API.

    Implements the LLMProvider protocol. Uses OpenAI-compatible format.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "openai/gpt-4o",
        base_url: str = _DEFAULT_URL,
        max_tokens: int = 4096,
        site_name: str = "ClawQuant",
        site_url: str = "https://github.com/tedboudros/ClawQuant",
    ) -> None:
        self._model = model
        self._max_tokens = max_tokens
        self._url = base_url
        self._client = httpx.AsyncClient(
            timeout=120.0,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": site_url,
                "X-Title": site_name,
            },
        )

    @property
    def name(self) -> str:
        return "openrouter"

    async def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        """POST to OpenRouter and return parsed JSON, with rich error handling.

        Translates ``httpx.HTTPStatusError`` and other transport failures into
        ``LLMProviderError`` carrying the upstream body / status code so the
        cause shows up in logs and user-facing messages instead of a bare
        traceback.
        """
        model = body.get("model", self._model)
        try:
            response = await self._client.post(self._url, json=body)
        except httpx.HTTPError as exc:
            logger.error(
                "OpenRouter request transport error (model=%s): %s", model, exc,
            )
            raise LLMProviderError(
                f"network error contacting OpenRouter: {exc}",
                provider=self.name,
                model=str(model),
            ) from exc

        if response.status_code >= 400:
            body_text = response.text or ""
            api_msg = _extract_api_error(body_text)
            logger.error(
                "OpenRouter API error (model=%s, status=%d): %s",
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
                "OpenRouter returned non-JSON response (model=%s): %s",
                model,
                response.text[:_MAX_BODY_LOG_CHARS],
            )
            raise LLMProviderError(
                "invalid JSON response from OpenRouter",
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
                "OpenRouter unexpected response shape (model=%s): %s",
                body["model"], data,
            )
            raise LLMProviderError(
                "unexpected response shape from OpenRouter",
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
                "OpenRouter unexpected tool_call response shape (model=%s): %s",
                body["model"], data,
            )
            raise LLMProviderError(
                "unexpected response shape from OpenRouter",
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
