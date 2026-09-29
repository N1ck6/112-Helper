from __future__ import annotations

import time
import uuid
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BusinessRuleError, NotFoundError
from app.core.logging import get_logger
from app.core.pagination import PageParams
from app.core.security import utcnow
from app.integrations.ml_client import get_ml_client
from app.integrations.telephony_client import get_telephony_client
from app.models.audit import AuditLog, SystemLog
from app.models.enums import (
    AuditAction,
    LessonStatus,
    ServiceStatus,
)
from app.models.grading import Evaluation
from app.models.system import ServiceState, SystemSetting
from app.models.training import CardAttempt, Lesson
from app.models.user import User
from app.repositories.system import (
    AuditRepository,
    OutboxRepository,
    ServiceStateRepository,
    SettingRepository,
    SystemLogRepository,
)
from app.repositories.users import UserRepository
from app.schemas.system import ServiceControlRequest, SettingUpsert
from app.services.audit import AuditService

logger = get_logger(__name__)

PROTECTED_SETTING_PREFIXES = ("security.", "auth.")
START_TIME = time.monotonic()


class AdminService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings_repo = SettingRepository(session)
        self.services = ServiceStateRepository(session)
        self.audit_repo = AuditRepository(session)
        self.logs = SystemLogRepository(session)
        self.outbox = OutboxRepository(session)
        self.users = UserRepository(session)
        self.audit = AuditService(session)

    # ------------------------------------------------------------- конфигурация
    async def list_settings(self) -> Sequence[SystemSetting]:
        # Служебные записи (метки seed) в интерфейсе не показываются
        return [s for s in await self.settings_repo.list_all() if s.category != "internal"]

    async def upsert_setting(
        self, data: SettingUpsert, actor: User, request: Request | None = None
    ) -> SystemSetting:
        protected = data.key.startswith(PROTECTED_SETTING_PREFIXES)
        if protected and not actor.has_permission("system:config"):
            raise BusinessRuleError("Изменение параметров безопасности требует отдельного права")

        setting = await self.settings_repo.by_key(data.key)
        value = data.value if isinstance(data.value, dict | list) else {"value": data.value}
        before = setting.value if setting else None
        if setting is None:
            setting = await self.settings_repo.create(
                key=data.key,
                value=value,
                category=data.category,
                description=data.description,
                is_protected=protected,
                updated_by_id=actor.id,
            )
        else:
            setting.value = value
            setting.category = data.category
            setting.description = data.description or setting.description
            setting.updated_by_id = actor.id
            await self.session.flush()

        await self.audit.log(
            AuditAction.CONFIG_CHANGE,
            actor=actor,
            object_type="system_setting",
            object_id=setting.id,
            summary=f"Изменён параметр {data.key}",
            before={"value": before},
            after={"value": value},
            request=request,
        )
        return setting

    # ----------------------------------------------------------------- сервисы
    async def list_services(self) -> Sequence[ServiceState]:
        await self._refresh_components()
        return await self.services.list_all()

    async def control_service(
        self,
        name: str,
        data: ServiceControlRequest,
        actor: User,
        request: Request | None = None,
    ) -> ServiceState:
        state = await self.services.by_name(name)
        if state is None:
            raise NotFoundError(f"Сервис «{name}» не зарегистрирован")

        running = await self.session.execute(
            sa.select(sa.func.count()).select_from(Lesson).where(
                Lesson.status.in_([LessonStatus.RUNNING, LessonStatus.PAUSED])
            )
        )
        if int(running.scalar_one()) and data.action in ("stop", "restart"):
            raise BusinessRuleError(
                "Идут активные занятия: остановка сервисов запрещена. Завершите занятия."
            )

        requested = {
            "start": ServiceStatus.RUNNING,
            "stop": ServiceStatus.STOPPED,
            "restart": ServiceStatus.RUNNING,
        }[data.action]
        state.details = {
            **(state.details or {}),
            "requested_action": data.action,
            "requested_at": utcnow().isoformat(),
            "requested_by": actor.username,
        }
        state.status = requested
        await self.session.flush()

        await self.audit.log(
            AuditAction.SERVICE_CONTROL,
            actor=actor,
            object_type="service",
            object_id=state.id,
            summary=f"Команда «{data.action}» для сервиса {name}: {data.reason or 'без комментария'}",
            after={"status": state.status.value},
            request=request,
        )
        return state

    async def _refresh_components(self) -> None:
        """Опрашивает ML и телефонию, фиксируя их доступность."""
        ml = get_ml_client()
        telephony = get_telephony_client()
        try:
            ml_health = await ml.health()
        except Exception as exc:  # noqa: BLE001
            ml_health = {"status": "down", "error": str(exc)}
        try:
            tel_health = await telephony.health()
        except Exception as exc:  # noqa: BLE001
            tel_health = {"status": "down", "error": str(exc)}

        await self.services.upsert(
            "backend",
            kind="api",
            status=ServiceStatus.RUNNING,
            version=settings.APP_VERSION,
            last_heartbeat_at=utcnow(),
            details={"env": settings.APP_ENV},
        )
        await self.services.upsert(
            "database",
            kind="storage",
            status=ServiceStatus.RUNNING if await self._db_alive() else ServiceStatus.DEGRADED,
            endpoint=f"{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}",
            last_heartbeat_at=utcnow(),
        )
        await self.services.upsert(
            "ml",
            kind="service",
            status=_map_status(ml_health.get("status")),
            endpoint=settings.ML_SERVICE_URL,
            last_heartbeat_at=utcnow(),
            details=ml_health,
            last_error=ml_health.get("error"),
        )
        await self.services.upsert(
            "telephony",
            kind="service",
            status=_map_status(tel_health.get("status")),
            endpoint=settings.TELEPHONY_SERVICE_URL,
            last_heartbeat_at=utcnow(),
            details=tel_health,
            last_error=tel_health.get("error"),
        )

    async def _db_alive(self) -> bool:
        try:
            await self.session.execute(sa.text("SELECT 1"))
            return True
        except Exception:  # noqa: BLE001
            return False

    # --------------------------------------------------------------- статистика
    async def stats(self) -> dict[str, Any]:
        day_start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        users_total = await self.users.count()
        users_active = await self.users.count(User.is_active.is_(True))
        lessons_running = int(
            (
                await self.session.execute(
                    sa.select(sa.func.count()).select_from(Lesson).where(
                        Lesson.status.in_([LessonStatus.RUNNING, LessonStatus.PAUSED])
                    )
                )
            ).scalar_one()
        )
        attempts_today = int(
            (
                await self.session.execute(
                    sa.select(sa.func.count()).select_from(CardAttempt).where(
                        CardAttempt.issued_at >= day_start
                    )
                )
            ).scalar_one()
        )
        evaluations_today = int(
            (
                await self.session.execute(
                    sa.select(sa.func.count()).select_from(Evaluation).where(
                        Evaluation.evaluated_at >= day_start
                    )
                )
            ).scalar_one()
        )

        db_size = None
        try:
            db_size = int(
                (
                    await self.session.execute(
                        sa.text("SELECT pg_database_size(current_database())")
                    )
                ).scalar_one()
            )
        except Exception:  # noqa: BLE001 — функция специфична для PostgreSQL
            db_size = None

        return {
            "users_total": users_total,
            "users_active": users_active,
            "lessons_running": lessons_running,
            "attempts_today": attempts_today,
            "evaluations_today": evaluations_today,
            "db_size_bytes": db_size,
            "outbox_pending": await self.outbox.pending_count(),
            "services": list(await self.list_services()),
            "uptime_seconds": round(time.monotonic() - START_TIME, 1),
        }

    # ------------------------------------------------------------------ журналы
    async def list_audit(
        self,
        params: PageParams,
        *,
        action: str | None = None,
        actor_id: uuid.UUID | None = None,
        object_type: str | None = None,
        security_only: bool = False,
    ) -> tuple[Sequence[AuditLog], int]:
        conditions = []
        if action:
            conditions.append(AuditLog.action == action)
        if actor_id:
            conditions.append(AuditLog.actor_id == actor_id)
        if object_type:
            conditions.append(AuditLog.object_type == object_type)
        if security_only:
            conditions.append(AuditLog.is_security.is_(True))
        return await self.audit_repo.paginate(params, *conditions)

    async def list_logs(
        self, params: PageParams, *, level: str | None = None, component: str | None = None
    ) -> tuple[Sequence[SystemLog], int]:
        conditions = []
        if level:
            conditions.append(SystemLog.level == level)
        if component:
            conditions.append(SystemLog.component == component)
        return await self.logs.paginate(params, *conditions)


def _map_status(value: str | None) -> ServiceStatus:
    return {
        "ok": ServiceStatus.RUNNING,
        "degraded": ServiceStatus.DEGRADED,
        "down": ServiceStatus.STOPPED,
    }.get(value or "", ServiceStatus.UNKNOWN)
