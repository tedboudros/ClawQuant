"""Scheduler runner -- asyncio loop that checks task files and fires due tasks.

Every `check_interval` seconds:
1. Reads all task JSON files from the tasks/ directory
2. Checks which tasks are due (cron matches or run_at has passed)
3. Looks up the TaskHandler from the registry
4. Fires the handler and publishes schedule.fired events
5. Updates the task file with last_run_at and run_count
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from core.bus import AsyncIOBus
from core.data.store import Store
from core.models.events import Event, EventTypes
from core.models.tasks import Task, TaskResult
from core.registry import PluginRegistry
from scheduler.cron import cron_matches

logger = logging.getLogger(__name__)


class Scheduler:
    """Async scheduler that reads task files and fires due tasks.

    Usage:
        scheduler = Scheduler(store=store, bus=bus, registry=registry)
        await scheduler.start()  # runs until cancelled
    """

    def __init__(
        self,
        store: Store,
        bus: AsyncIOBus,
        registry: PluginRegistry,
        check_interval: int = 60,
        timezone_name: str = "America/New_York",
    ) -> None:
        self._store = store
        self._bus = bus
        self._registry = registry
        self._check_interval = check_interval
        self._tz = ZoneInfo(timezone_name)
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the scheduler loop."""
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Scheduler started (check every %ds)", self._check_interval)

    async def stop(self) -> None:
        """Stop the scheduler loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Scheduler stopped")

    async def _loop(self) -> None:
        """Main scheduler loop."""
        while self._running:
            try:
                await self._check_tasks()
            except Exception:
                logger.exception("Error in scheduler loop")
            await asyncio.sleep(self._check_interval)

    async def _check_tasks(self) -> None:
        """Read all task files and fire any that are due."""
        tasks = self._store.list_json("tasks", Task)
        now_utc = datetime.now(timezone.utc)
        now_local = now_utc.astimezone(self._tz)

        for task in tasks:
            if not task.enabled:
                continue

            try:
                if self._is_due(task, now_utc, now_local):
                    await self._fire_task(task, now_utc)
            except Exception:
                logger.exception("Error checking task %s (%s)", task.name, task.id)

    def _is_due(self, task: Task, now_utc: datetime, now_local: datetime) -> bool:
        """Check if a task should fire at the given time."""
        # One-off tasks: fire if run_at has passed and hasn't run yet
        if task.run_at is not None:
            if task.last_run_at is not None:
                return False  # already ran
            run_at = task.run_at
            if run_at.tzinfo is None:
                run_at = run_at.replace(tzinfo=self._tz)
            return now_utc >= run_at

        # One-off/research with no run_at: fire immediately if never run
        if task.type in ("one_off", "research"):
            return task.last_run_at is None

        # Recurring/comparison tasks: check cron expression in configured timezone
        if task.cron_expression:
            if task.last_run_at is not None:
                last = task.last_run_at.astimezone(self._tz)
                if (
                    last.year == now_local.year
                    and last.month == now_local.month
                    and last.day == now_local.day
                    and last.hour == now_local.hour
                    and last.minute == now_local.minute
                ):
                    return False
            return cron_matches(task.cron_expression, now_local)

        return False

    async def _fire_task(self, task: Task, now: datetime) -> None:
        """Execute a task: look up handler, run it, update task file."""
        logger.info("Firing task: %s (%s)", task.name, task.handler)

        # Publish schedule.fired event
        event = Event(
            type=EventTypes.SCHEDULE_FIRED,
            source="scheduler",
            payload={
                "task_id": task.id,
                "task_name": task.name,
                "handler": task.handler,
                "params": task.params,
            },
        )
        await self._bus.publish(event)

        # Look up and run the handler
        result = TaskResult(status="no_action", message="No handler found")

        if self._registry.has("task_handler", task.handler):
            handler = self._registry.get("task_handler", task.handler)
            try:
                result = await handler.run(task.params)
                logger.info(
                    "Task %s completed: %s - %s",
                    task.name, result.status, result.message,
                )
            except Exception as exc:
                logger.exception("Task %s failed", task.name)
                result = TaskResult(status="error", message=str(exc))
        else:
            logger.warning("No handler registered for '%s'", task.handler)

        # Update task file
        task.last_run_at = now
        task.last_result = result.status
        task.run_count += 1

        # Disable one-off and research tasks after they run
        if task.type in ("one_off", "research"):
            task.enabled = False

        self._store.write_json("tasks", f"{task.id}.json", task)

    async def create_task(self, task: Task) -> Task:
        """Create a new task (write file + publish event)."""
        self._store.write_json("tasks", f"{task.id}.json", task)

        event = Event(
            type=EventTypes.TASK_CREATED,
            source="scheduler",
            payload={
                "task_id": task.id,
                "task_name": task.name,
                "type": task.type,
                "handler": task.handler,
                "created_by": task.created_by,
            },
        )
        await self._bus.publish(event)

        logger.info("Created task: %s (%s by %s)", task.name, task.type, task.created_by)
        return task

    async def delete_task(self, task_id: str) -> bool:
        """Delete a task by ID."""
        deleted = self._store.delete_file("tasks", f"{task_id}.json")
        if deleted:
            logger.info("Deleted task: %s", task_id)
        return deleted

    def list_tasks(self) -> list[Task]:
        """List all tasks."""
        return self._store.list_json("tasks", Task)
