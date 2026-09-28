from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import utcnow
from app.db.session import session_scope
from app.models.enums import OutboxStatus
from app.models.system import OutboxMessage

logger = get_logger(__name__)

Handler = Callable[[AsyncSession, dict[str, Any]], Awaitable[None]]
_handlers: dict[str, Handler] = {}


def register_handler(topic: str, handler: Handler) -> None:
    _handlers[topic] = handler


async def enqueue(session: AsyncSession, topic: str, payload: dict[str, Any]) -> OutboxMessage:
    message = OutboxMessage(topic=topic, payload=payload, next_attempt_at=utcnow())
    session.add(message)
    await session.flush()
    return message


def _backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(300, 2 ** min(attempts, 8)))


async def process_batch(limit: int = 20) -> int:
    """Обработать порцию сообщений. Возвращает число успешно отправленных."""
    processed = 0
    async with session_scope() as session:
        stmt = (
            sa.select(OutboxMessage)
            .where(
                OutboxMessage.status == OutboxStatus.PENDING,
                OutboxMessage.next_attempt_at <= utcnow(),
            )
            .order_by(OutboxMessage.next_attempt_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        messages = (await session.execute(stmt)).scalars().all()

        for message in messages:
            handler = _handlers.get(message.topic)
            message.attempts += 1
            if handler is None:
                message.status = OutboxStatus.DEAD
                message.last_error = f"Нет обработчика для топика {message.topic}"
                continue
            try:
                await handler(session, message.payload)
                message.status = OutboxStatus.SENT
                message.sent_at = utcnow()
                processed += 1
            except Exception as exc:  # noqa: BLE001 - фиксируем любую ошибку доставки
                message.last_error = str(exc)[:1000]
                if message.attempts >= settings.OUTBOX_MAX_ATTEMPTS:
                    message.status = OutboxStatus.DEAD
                    logger.error(
                        "outbox_message_dead",
                        extra={"topic": message.topic, "attempts": message.attempts},
                    )
                else:
                    message.next_attempt_at = utcnow() + _backoff(message.attempts)
    return processed


class OutboxWorker:
    """Фоновый воркер, запускается вместе с приложением."""

    def __init__(self, interval_seconds: int | None = None) -> None:
        self.interval = interval_seconds or settings.OUTBOX_POLL_SECONDS
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()

    async def _loop(self) -> None:
        logger.info("outbox_worker_started", extra={"interval": self.interval})
        while not self._stopping.is_set():
            try:
                await process_batch()
            except Exception:  # noqa: BLE001
                logger.exception("outbox_worker_iteration_failed")
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=self.interval)
            except TimeoutError:
                continue

    def start(self) -> None:
        if self._task is None:
            self._stopping.clear()
            self._task = asyncio.create_task(self._loop(), name="outbox-worker")

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None
            logger.info("outbox_worker_stopped")
