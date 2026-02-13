"""Notification task handler.

Sends a plain text message through configured output integrations.
"""

from __future__ import annotations

import logging

from core.models.tasks import TaskResult
from core.registry import PluginRegistry

logger = logging.getLogger(__name__)


class NotificationsHandler:
    """Send scheduled notification messages to output adapters."""

    def __init__(self, registry: PluginRegistry) -> None:
        self._registry = registry

    @property
    def name(self) -> str:
        return "notifications.send"

    async def run(self, params: dict) -> TaskResult:
        message = str(params.get("message", "")).strip()
        if not message:
            return TaskResult(
                status="error",
                message="Missing required param: message",
            )

        channel_id = params.get("channel_id")
        outputs = self._registry.get_all("output")
        sent = 0

        for output in outputs:
            send_text = getattr(output, "send_text", None)
            if send_text is None:
                continue
            try:
                await send_text(message, channel_id=channel_id)
                sent += 1
            except Exception:
                logger.exception("Failed to send notification via %s", getattr(output, "name", "unknown"))

        if sent == 0:
            return TaskResult(
                status="error",
                message="No compatible output adapters available for text notifications",
            )

        return TaskResult(
            status="success",
            message=f"Delivered notification via {sent} output adapter(s)",
        )
