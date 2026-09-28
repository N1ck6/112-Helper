from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger, get_request_id
from app.core.security import utcnow
from app.models.audit import AuditLog, SystemLog
from app.models.enums import AuditAction, LogLevel
from app.models.user import User

logger = get_logger(__name__)

SECURITY_ACTIONS = {
    AuditAction.LOGIN,
    AuditAction.LOGIN_FAILED,
    AuditAction.LOGOUT,
    AuditAction.BLOCK,
    AuditAction.UNBLOCK,
    AuditAction.PERMISSION_CHANGE,
    AuditAction.GRADE_OVERRIDE,
    AuditAction.CONFIG_CHANGE,
    AuditAction.SERVICE_CONTROL,
    AuditAction.BACKUP,
}


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def log(
        self,
        action: AuditAction,
        *,
        actor: User | None = None,
        actor_username: str | None = None,
        object_type: str | None = None,
        object_id: str | uuid.UUID | None = None,
        summary: str | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        request: Request | None = None,
        result: str = "success",
        is_security: bool | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            action=action,
            actor_id=actor.id if actor else None,
            actor_username=actor.username if actor else actor_username,
            actor_roles=",".join(actor.role_codes) if actor else None,
            object_type=object_type,
            object_id=str(object_id) if object_id else None,
            summary=summary,
            before=before or {},
            after=after or {},
            ip_address=_client_ip(request),
            user_agent=(request.headers.get("user-agent") if request else None),
            request_id=get_request_id(),
            result=result,
            is_security=is_security if is_security is not None else action in SECURITY_ACTIONS,
        )
        self.session.add(entry)
        await self.session.flush()
        logger.info(
            "audit",
            extra={
                "action": action.value,
                "object_type": object_type,
                "object_id": str(object_id) if object_id else None,
                "actor": entry.actor_username,
                "result": result,
            },
        )
        return entry

    async def system(
        self,
        message: str,
        *,
        level: LogLevel = LogLevel.INFO,
        component: str = "backend",
        context: dict[str, Any] | None = None,
        traceback: str | None = None,
    ) -> SystemLog:
        entry = SystemLog(
            message=message,
            level=level,
            component=component,
            logger=__name__,
            context=context or {},
            request_id=get_request_id(),
            traceback=traceback,
        )
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def purge_expired(self) -> int:
        threshold = utcnow() - _days(settings.SECURITY_LOG_RETENTION_DAYS)
        result = await self.session.execute(
            sa.delete(AuditLog).where(AuditLog.at < threshold, AuditLog.is_security.is_(False))
        )
        removed = int(result.rowcount or 0)

        #: Системный журнал — технические сообщения, их срок хранения короче.
        system_threshold = utcnow() - _days(settings.SYSTEM_LOG_RETENTION_DAYS)
        system_result = await self.session.execute(
            sa.delete(SystemLog).where(SystemLog.at < system_threshold)
        )
        return removed + int(system_result.rowcount or 0)


def _client_ip(request: Request | None) -> str | None:
    if request is None:
        return None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def _days(count: int):
    from datetime import timedelta

    return timedelta(days=count)
