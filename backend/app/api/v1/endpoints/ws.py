from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.core.permissions import Perm
from app.core.security import decode_token, utcnow
from app.db.session import session_scope
from app.repositories.users import UserRepository
from app.services.realtime import lesson_hub
from app.services.training import TrainingService

logger = get_logger(__name__)
router = APIRouter()

HEARTBEAT_SECONDS = 20


@router.websocket("/ws/lessons/{lesson_id}")
async def lesson_events(
    websocket: WebSocket,
    lesson_id: uuid.UUID,
    token: str = Query(..., description="Access-токен"),
) -> None:
    try:
        payload = decode_token(token, expected_type="access")
        user_id = uuid.UUID(payload.sub)
    except (AppError, ValueError):
        await websocket.close(code=4401, reason="Некорректный токен")
        return

    async with session_scope() as session:
        user = await UserRepository(session).get_with_roles(user_id)
        if user is None:
            await websocket.close(code=4401, reason="Пользователь не найден")
            return
        allowed = (
            user.has_permission(Perm.LESSONS_MONITOR)
            or user.has_permission(Perm.SYSTEM_MONITOR)
            or user.has_permission(Perm.LESSONS_PARTICIPATE)
        )
        if not allowed:
            await websocket.close(code=4403, reason="Недостаточно прав")
            return
        try:
            lesson = await TrainingService(session).get_lesson(lesson_id)
        except AppError:
            await websocket.close(code=4404, reason="Занятие не найдено")
            return

    await websocket.accept()
    await lesson_hub.subscribe(lesson_id, websocket)
    await websocket.send_json(
        {
            "event": "connected",
            "lesson_id": str(lesson_id),
            "data": {"status": lesson.status.value, "server_time": utcnow().isoformat()},
        }
    )

    try:
        while True:
            try:
                message = await asyncio.wait_for(websocket.receive_text(), timeout=HEARTBEAT_SECONDS)
                if message == "ping":
                    await websocket.send_json({"event": "pong", "lesson_id": str(lesson_id), "data": {}})
            except TimeoutError:
                await websocket.send_json(
                    {
                        "event": "heartbeat",
                        "lesson_id": str(lesson_id),
                        "data": {"server_time": utcnow().isoformat()},
                    }
                )
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        logger.exception("ws_error")
    finally:
        await lesson_hub.unsubscribe(lesson_id, websocket)
