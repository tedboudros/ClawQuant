"""Web search plugin tool (API-backed, key-configurable)."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx

from core.models.tasks import TaskResult

logger = logging.getLogger(__name__)

PLUGIN_META = {
    "name": "web_search",
    "display_name": "Web Search (Google API)",
    "description": "Search the web via an API-backed Google-compatible provider",
    "category": "task_handler",
    "protocols": ["task_handler"],
    "class_name": "WebSearchHandler",
    "pip_dependencies": [],
    "setup_instructions": """
Configure a search API key (Serper.dev compatible).

Required:
- SERPER_API_KEY environment variable (set by setup wizard)
""",
    "config_fields": [
        {
            "key": "api_key",
            "label": "Serper API Key",
            "type": "secret",
            "required": True,
            "env_var": "SERPER_API_KEY",
            "description": "API key for Google-compatible search via serper.dev",
            "placeholder": "your-key",
        },
        {
            "key": "default_limit",
            "label": "Default result count",
            "type": "number",
            "required": False,
            "default": 5,
            "description": "Default number of results returned by web_search",
            "placeholder": "5",
        },
    ],
}


class WebSearchHandler:
    """Provides the `web_search` plugin tool for the AI interface."""

    def __init__(self, default_limit: int = 5) -> None:
        self._default_limit = default_limit

    @property
    def name(self) -> str:
        return "web.search"

    def get_tools(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "Search the web for recent information. Supports optional as_of cutoff for sandbox-safe lookups.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search query text",
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum results to return (default: 5, max: 10)",
                            },
                            "as_of": {
                                "type": "string",
                                "description": "Optional ISO datetime cutoff. Restricts results to pages published on or before this timestamp.",
                            },
                        },
                        "required": ["query"],
                    },
                },
            }
        ]

    async def call_tool(
        self,
        name: str,
        args: dict,
        source: str | None = None,
        interface: object | None = None,
    ) -> str | None:
        if name != "web_search":
            return None

        api_key = os.environ.get("SERPER_API_KEY", "").strip()
        if not api_key:
            return "Web search is not configured. Set SERPER_API_KEY in your environment or via setup."

        query = str(args.get("query", "")).strip()
        if not query:
            return "web_search requires a non-empty query."

        limit = int(args.get("limit", self._default_limit))
        limit = max(1, min(limit, 10))
        as_of = _parse_as_of(args.get("as_of"))

        payload: dict[str, Any] = {"q": query, "num": limit}
        if as_of:
            # Best-effort date bound understood by Google-compatible search backends.
            payload["tbs"] = f"cdr:1,cd_max:{as_of.strftime('%m/%d/%Y')}"

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    "https://google.serper.dev/search",
                    headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
        except Exception:
            logger.exception("web_search request failed")
            return "Web search failed due to API/network error."

        results = data.get("organic", []) or []
        if not results:
            return "No web search results found."

        lines = []
        for idx, item in enumerate(results[:limit], start=1):
            title = str(item.get("title", "")).strip()
            link = str(item.get("link", "")).strip()
            snippet = str(item.get("snippet", "")).strip()
            date_text = str(item.get("date", "")).strip()
            line = f"{idx}. {title}" if title else f"{idx}. {link}"
            if date_text:
                line += f" ({date_text})"
            if link:
                line += f"\n   {link}"
            if snippet:
                line += f"\n   {snippet}"
            lines.append(line)

        as_of_note = ""
        if as_of:
            as_of_note = f"\n(Filtered with as_of <= {as_of.isoformat()} where provider metadata allows.)"

        return f"Web results for '{query}':\n" + "\n".join(lines) + as_of_note

    async def run(self, params: dict) -> TaskResult:
        """No scheduled behavior by default; this plugin is primarily tool-driven."""
        return TaskResult(
            status="no_action",
            message="web.search is a tool plugin; use the 'web_search' AI tool.",
        )


def _parse_as_of(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
