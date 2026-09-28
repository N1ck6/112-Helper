from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.arm112 import service_title
from app.core.exceptions import BusinessRuleError, PermissionDeniedError
from app.core.logging import get_logger
from app.core.permissions import Perm
from app.core.security import utcnow
from app.integrations.telephony_client import get_telephony_client
from app.models.card import IncidentCard
from app.models.enums import (
    CallDirection,
    CallStatus,
    LogLevel,
    ProcessingKind,
)
from app.models.system import CallRecord
from app.models.training import CardAttempt, CardProcessing
from app.models.user import User
from app.repositories.training import AttemptRepository
from app.services.audit import AuditService
from app.services.routing import RoutingService

logger = get_logger(__name__)

ANSWERED_BY_REQUIRED = {
    ProcessingKind.SERVICE,
    ProcessingKind.SUPERVISOR,
    ProcessingKind.BRIGADE,
}


class ProcessingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.attempts = AttemptRepository(session)
        self.routing = RoutingService(session)
        self.audit = AuditService(session)
        self.telephony = get_telephony_client()

    # ------------------------------------------------------------------ чтение
    async def for_attempt(self, attempt_id: uuid.UUID, actor: User) -> Sequence[CardProcessing]:
        attempt = await self.attempts.get_or_fail(attempt_id, "Попытка не найдена")
        await self._ensure_access(attempt, actor)
        result = await self.session.execute(
            sa.select(CardProcessing)
            .where(CardProcessing.attempt_id == attempt_id)
            .order_by(CardProcessing.sequence_no)
        )
        return result.scalars().all()

    async def for_lesson(self, lesson_id: uuid.UUID) -> Sequence[CardProcessing]:
        result = await self.session.execute(
            sa.select(CardProcessing)
            .where(CardProcessing.lesson_id == lesson_id)
            .order_by(CardProcessing.at)
        )
        return result.scalars().all()

    async def contacts_for(self, attempt_id: uuid.UUID, actor: User) -> list[dict[str, Any]]:
        attempt = await self.attempts.get_or_fail(attempt_id, "Попытка не найдена")
        await self._ensure_access(attempt, actor)

        contacts: list[dict[str, Any]] = []
        for item in attempt.notification_list or []:
            code = str(item.get("code"))
            if code == attempt.service_code:
                continue
            service = await self.routing.by_code(code)
            contacts.append(
                {
                    "kind": ProcessingKind.SUPERVISOR.value,
                    "service_code": code,
                    "service_name": item.get("name") or service_title(code),
                    "phone": (
                        (service.phone_extension or service.phone) if service else item.get("phone")
                    ),
                    "supervisor": service.supervisor if service else {},
                    "is_primary": bool(item.get("is_primary")),
                }
            )

        card = await self.session.get(IncidentCard, attempt.card_id)
        applicant_phone = (
            _first_phone(attempt.draft_payload)
            or _first_phone(card.payload if card else None)
            or _first_phone(card.expected_payload if card else None)
        )
        if applicant_phone:
            contacts.append(
                {
                    "kind": ProcessingKind.APPLICANT.value,
                    "service_code": None,
                    "service_name": "Заявитель",
                    "phone": applicant_phone,
                    "supervisor": {},
                    "is_primary": False,
                }
            )
        return contacts

    # ------------------------------------------------------------------ запись
    async def register(
        self, attempt_id: uuid.UUID, data: dict[str, Any], student: User
    ) -> CardProcessing:
        """Зафиксировать отработку и, если возможно, поднять учебный вызов."""
        attempt = await self.attempts.get_or_fail(attempt_id, "Попытка не найдена")
        if attempt.student_id != student.id:
            raise PermissionDeniedError("Это карточка другого обучающегося")
        if attempt.status not in AttemptRepository.ACTIVE_STATUSES:
            raise BusinessRuleError("Карточка уже закрыта — отработку добавить нельзя")

        kind = ProcessingKind(str(data.get("kind") or ProcessingKind.SERVICE.value))
        summary = str(data.get("summary") or "").strip()
        if not summary:
            raise BusinessRuleError("Суть сообщения обязательна: это содержание отработки")
        answered_by = str(data.get("answered_by") or "").strip()
        if kind in ANSWERED_BY_REQUIRED and not answered_by:
            raise BusinessRuleError(
                "Укажите, кто принял сообщение: строка отработки без этого недействительна"
            )

        service_code = data.get("service_code")
        phone = data.get("phone")
        service_name = data.get("service_name")
        if service_code:
            service = await self.routing.by_code(str(service_code))
            service_name = service_name or (service.name if service else service_title(str(service_code)))
            phone = phone or (service.phone_extension or service.phone if service else None)

        now = utcnow()
        processing = CardProcessing(
            attempt_id=attempt.id,
            lesson_id=attempt.lesson_id,
            student_id=student.id,
            sequence_no=await self._next_sequence_no(attempt.id),
            kind=kind,
            service_code=str(service_code) if service_code else None,
            service_name=service_name,
            phone=str(phone) if phone else None,
            answered_by=answered_by or None,
            summary=summary,
            at=now,
            offset_ms=int((now - attempt.issued_at).total_seconds() * 1000),
            duration_ms=data.get("duration_ms"),
            workplace_id=attempt.workplace_id,
        )

        call = await self._originate(attempt, processing, student)
        if call is not None:
            processing.call_id = call.id

        self.session.add(processing)
        await self.session.flush()
        return processing

    # ---------------------------------------------------------------- приватное
    async def _next_sequence_no(self, attempt_id: uuid.UUID) -> int:
        stmt = sa.select(sa.func.coalesce(sa.func.max(CardProcessing.sequence_no), 0)).where(
            CardProcessing.attempt_id == attempt_id
        )
        return int((await self.session.execute(stmt)).scalar_one()) + 1

    async def _originate(
        self, attempt: CardAttempt, processing: CardProcessing, student: User
    ) -> CallRecord | None:
        """Попросить телефонию поднять вызов. Недоступность не отменяет отработку."""
        if processing.kind is ProcessingKind.INCOMING_REPORT:
            #: Входящий доклад создаёт телефония сама — вызов уже состоялся.
            return None
        if not processing.phone:
            return None

        try:
            response = await self.telephony.originate_call(
                {
                    "lesson_id": str(attempt.lesson_id),
                    "attempt_id": str(attempt.id),
                    "student_id": str(student.id),
                    "direction": "outbound",
                    "kind": processing.kind.value,
                    "callee_number": processing.phone,
                    "callee_name": processing.service_name,
                    "caller_number": (student.preferences or {}).get("sip_extension"),
                    "record": True,
                }
            )
        except Exception as exc:  # noqa: BLE001 — чужой модуль не должен ломать занятие
            logger.warning("telephony_originate_failed", extra={"error": str(exc)})
            await self.audit.system(
                f"Отработка зафиксирована без вызова: модуль телефонии недоступен ({exc})",
                level=LogLevel.WARNING,
                component="telephony",
                context={"attempt_id": str(attempt.id), "kind": processing.kind.value},
            )
            return None

        call = CallRecord(
            sip_call_id=response.get("sip_call_id"),
            direction=CallDirection.OUTBOUND,
            status=CallStatus.RINGING,
            lesson_id=attempt.lesson_id,
            attempt_id=attempt.id,
            student_id=student.id,
            caller_number=response.get("caller_number"),
            callee_number=processing.phone,
            latency_ms=response.get("latency_ms"),
            meta={"stub": bool(response.get("stub")), "kind": processing.kind.value},
        )
        self.session.add(call)
        await self.session.flush()
        return call

    async def _ensure_access(self, attempt: CardAttempt, actor: User) -> None:
        if attempt.student_id == actor.id:
            return
        if actor.has_permission(Perm.EVALUATIONS_READ) or actor.has_permission(Perm.LESSONS_MONITOR):
            return
        raise PermissionDeniedError("Доступ к данным другого обучающегося запрещён")


def _first_phone(payload: dict[str, Any] | None) -> str | None:
    for field in ("aon_phone", "provided_phone", "site_phone"):
        value = (payload or {}).get(field)
        if value and str(value).strip():
            return str(value).strip()
    return None
