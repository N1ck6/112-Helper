from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import session_scope
from app.services.audit import AuditService
from app.services.backup import BackupService
from app.services.training import TrainingService

logger = get_logger(__name__)


class PeriodicTask:
    def __init__(self, name: str, interval_seconds: float, handler: Callable[[], Awaitable[None]]) -> None:
        self.name = name
        self.interval = interval_seconds
        self.handler = handler
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()

    async def _loop(self) -> None:
        logger.info("periodic_task_started", extra={"task": self.name, "interval": self.interval})
        while not self._stopping.is_set():
            try:
                await self.handler()
            except Exception:  # noqa: BLE001 — фоновая задача не должна умирать
                logger.exception("periodic_task_failed", extra={"task": self.name})
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=self.interval)
            except TimeoutError:
                continue

    def start(self) -> None:
        if self._task is None:
            self._stopping.clear()
            self._task = asyncio.create_task(self._loop(), name=self.name)

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None
            logger.info("periodic_task_stopped", extra={"task": self.name})


async def expire_overdue_attempts() -> None:
    async with session_scope() as session:
        service = TrainingService(session)
        late = await service.mark_late_primary_response()
        closed = await service.expire_overdue()
    if late:
        logger.info("primary_status_overdue", extra={"count": late})
    if closed:
        logger.info("attempts_expired", extra={"count": closed})


async def mark_unfinished_cards() -> None:
    """Карточки без «Работы завершены» дольше 48 часов → статус «Не завершено»."""
    async with session_scope() as session:
        marked = await TrainingService(session).mark_unfinished_cards()
    if marked:
        logger.info("cards_marked_unfinished", extra={"count": marked})


async def purge_expired_logs() -> None:
    async with session_scope() as session:
        removed = await AuditService(session).purge_expired()
    if removed:
        logger.info("logs_purged", extra={"count": removed})


async def run_scheduled_backup() -> None:
    """Автоматическое резервное копирование БД по расписанию (п.2.2 ТЗ)."""
    if not settings.BACKUP_ENABLED:
        return
    async with session_scope() as session:
        record = await BackupService(session).create_backup(reason="scheduled")
        logger.info(
            "backup_finished",
            extra={"status": record.status.value, "file": record.path, "bytes": record.size_bytes},
        )


def build_tasks() -> list[PeriodicTask]:
    maintenance_interval = settings.MAINTENANCE_INTERVAL_HOURS * 3600
    return [
        PeriodicTask("expire-attempts", 10.0, expire_overdue_attempts),
        PeriodicTask("unfinished-cards", maintenance_interval, mark_unfinished_cards),
        PeriodicTask("purge-logs", maintenance_interval, purge_expired_logs),
        PeriodicTask("scheduled-backup", settings.BACKUP_INTERVAL_HOURS * 3600, run_scheduled_backup),
    ]
