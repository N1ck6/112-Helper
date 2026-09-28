from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

from app.core.logging import get_logger

logger = get_logger(__name__)


class LessonHub:
    def __init__(self) -> None:
        self._subscribers: dict[uuid.UUID, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def subscribe(self, lesson_id: uuid.UUID, websocket: WebSocket) -> None:
        async with self._lock:
            self._subscribers[lesson_id].add(websocket)
        logger.info("ws_subscribed", extra={"lesson_id": str(lesson_id)})

    async def unsubscribe(self, lesson_id: uuid.UUID, websocket: WebSocket) -> None:
        async with self._lock:
            self._subscribers[lesson_id].discard(websocket)
            if not self._subscribers[lesson_id]:
                self._subscribers.pop(lesson_id, None)

    async def publish(self, lesson_id: uuid.UUID, event: str, data: dict[str, Any]) -> int:
        """Рассылает событие подписчикам занятия. Возвращает число доставок."""
        message = {"event": event, "lesson_id": str(lesson_id), "data": data}
        async with self._lock:
            targets = list(self._subscribers.get(lesson_id, ()))

        delivered = 0
        stale: list[WebSocket] = []
        for websocket in targets:
            try:
                await websocket.send_json(message)
                delivered += 1
            except Exception:  # noqa: BLE001 — подписчик отвалился
                stale.append(websocket)
        if stale:
            async with self._lock:
                for websocket in stale:
                    self._subscribers[lesson_id].discard(websocket)
        return delivered


lesson_hub = LessonHub()
