"""Телефония со стороны backend: конфигурация, учёт вызовов, приём вебхуков (п.2.9)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.core.pagination import PageParams
from app.core.security import constant_time_equals, utcnow
from app.integrations.telephony_client import get_telephony_client
from app.models.enums import AuditAction, CallStatus, LogLevel
from app.models.system import CallRecord, TelephonyConfig
from app.models.training import CardAttempt
from app.models.user import User
from app.repositories.system import CallRepository, TelephonyConfigRepository
from app.schemas.system import CallEventRequest, TelephonyConfigUpdate
from app.services.audit import AuditService

EVENT_TO_STATUS = {
    "ringing": CallStatus.RINGING,
    "answered": CallStatus.ANSWERED,
    "missed": CallStatus.MISSED,
    "ended": CallStatus.ENDED,
    "failed": CallStatus.FAILED,
}


class TelephonyService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.configs = TelephonyConfigRepository(session)
        self.calls = CallRepository(session)
        self.audit = AuditService(session)
        self.client = get_telephony_client()

    # ------------------------------------------------------------ конфигурация
    async def get_config(self) -> TelephonyConfig:
        config = await self.configs.active()
        if config is None:
            config = await self.configs.create(name="default")
        return config

    async def update_config(
        self, data: TelephonyConfigUpdate, actor: User, request: Request | None = None
    ) -> TelephonyConfig:
        config = await self.get_config()
        before = {
            "sip_host": config.sip_host,
            "sip_port": config.sip_port,
            "codec": config.codec,
            "max_latency_ms": config.max_latency_ms,
        }
        for field, value in data.model_dump(exclude_unset=True).items():
            if value is not None:
                setattr(config, field, value)
        config.updated_by_id = actor.id
        await self.session.flush()

        await self.audit.log(
            AuditAction.CONFIG_CHANGE,
            actor=actor,
            object_type="telephony_config",
            object_id=config.id,
            summary="Изменены параметры IP-телефонии",
            before=before,
            after=data.model_dump(exclude_unset=True, mode="json"),
            request=request,
        )
        return config

    # -------------------------------------------------------------------- вызовы
    async def list_calls(
        self,
        params: PageParams,
        *,
        lesson_id: uuid.UUID | None = None,
        student_id: uuid.UUID | None = None,
    ) -> tuple[Sequence[CallRecord], int]:
        conditions = []
        if lesson_id:
            conditions.append(CallRecord.lesson_id == lesson_id)
        if student_id:
            conditions.append(CallRecord.student_id == student_id)
        return await self.calls.paginate(params, *conditions)

    async def handle_event(self, data: CallEventRequest, token: str | None) -> CallRecord:
        if not token or not constant_time_equals(token, settings.TELEPHONY_WEBHOOK_TOKEN):
            raise PermissionDeniedError("Некорректный токен модуля телефонии", code="invalid_webhook_token")

        call = await self.calls.by_sip_id(data.sip_call_id)
        if call is None:
            call = CallRecord(
                sip_call_id=data.sip_call_id,
                lesson_id=data.lesson_id,
                attempt_id=data.attempt_id,
                student_id=data.student_id,
                caller_number=data.caller_number,
                callee_number=data.callee_number,
            )
            self.session.add(call)

        call.status = EVENT_TO_STATUS[data.event]
        if data.latency_ms is not None:
            call.latency_ms = data.latency_ms
        if data.duration_ms is not None:
            call.duration_ms = data.duration_ms
        if data.audio_path:
            call.audio_path = data.audio_path
            call.audio_format = data.audio_format
        if data.event == "answered":
            call.answered_at = utcnow()
        if data.event in ("ended", "missed", "failed"):
            call.ended_at = utcnow()
        call.meta = {**(call.meta or {}), **data.meta}
        await self.session.flush()

        #: Контроль требования «задержка голоса не более 150 мс» (п.7 ТЗ).
        config = await self.get_config()
        if call.latency_ms and call.latency_ms > config.max_latency_ms:
            await self.audit.system(
                f"Задержка VoIP {call.latency_ms} мс превышает норматив {config.max_latency_ms} мс",
                level=LogLevel.WARNING,
                component="telephony",
                context={"sip_call_id": call.sip_call_id},
            )

        #: Аудиозапись учебного вызова привязывается к карточке для разбора занятия.
        if call.attempt_id and call.audio_path:
            attempt = await self.session.get(CardAttempt, call.attempt_id)
            if attempt is not None and attempt.call_id is None:
                attempt.call_id = call.id
                await self.session.flush()
        return call

    async def hangup(self, call_id: uuid.UUID, actor: User) -> CallRecord:
        call = await self.calls.get(call_id)
        if call is None:
            raise NotFoundError("Вызов не найден")
        if call.sip_call_id:
            await self.client.hangup(call.sip_call_id)
        call.status = CallStatus.ENDED
        call.ended_at = utcnow()
        await self.session.flush()
        return call

    async def health(self) -> dict:
        return await self.client.health()
