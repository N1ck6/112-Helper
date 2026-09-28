from __future__ import annotations

import time
import uuid
from collections.abc import Sequence
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.arm112 import primary_services
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.core.pagination import PageParams
from app.core.security import utcnow
from app.integrations import outbox
from app.integrations.ml_client import get_ml_client
from app.models.card import IncidentCard
from app.models.enums import (
    AuditAction,
    ErrorCategory,
    ErrorSeverity,
    EvaluationSource,
    MLTaskKind,
    MLTaskStatus,
)
from app.models.grading import ErrorRecord, Evaluation, MLResult, TrainingHistory
from app.models.scenario import ScenarioReference
from app.models.training import CardAttempt, Lesson
from app.models.user import User
from app.repositories.content import ReferenceRepository
from app.repositories.grading import ErrorRepository, EvaluationRepository
from app.repositories.training import ActionRepository, AttemptRepository
from app.schemas.grading import EvaluationOverrideRequest
from app.services.audit import AuditService

logger = get_logger(__name__)

OUTBOX_TOPIC_REEVALUATE = "ml.evaluate_attempt"


class EvaluationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.evaluations = EvaluationRepository(session)
        self.errors = ErrorRepository(session)
        self.attempts = AttemptRepository(session)
        self.actions = ActionRepository(session)
        self.references = ReferenceRepository(session)
        self.audit = AuditService(session)
        self.ml = get_ml_client()

    # ------------------------------------------------------------------ чтение
    async def for_attempt(self, attempt_id: uuid.UUID) -> Evaluation:
        evaluation = await self.evaluations.for_attempt(attempt_id)
        if evaluation is None:
            raise NotFoundError("Оценка по этой карточке ещё не сформирована")
        return evaluation

    async def list_for_lesson(self, lesson_id: uuid.UUID) -> Sequence[Evaluation]:
        return await self.evaluations.for_lesson(lesson_id)

    async def list_for_student(
        self, student_id: uuid.UUID, params: PageParams
    ) -> tuple[Sequence[Evaluation], int]:
        return await self.evaluations.paginate(params, Evaluation.student_id == student_id)

    # ------------------------------------------------------------------ оценка
    async def evaluate(
        self, attempt: CardAttempt, lesson: Lesson, card: IncidentCard
    ) -> Evaluation:
        payload = await self._build_payload(attempt, lesson, card)

        started = time.perf_counter()
        try:
            response = await self.ml.evaluate_attempt(payload)
            status = MLTaskStatus.STUBBED if response.get("stub") else MLTaskStatus.OK
            error: str | None = None
        except Exception as exc:  # noqa: BLE001 — недоступность ML не должна терять работу
            logger.warning("ml_evaluate_failed", extra={"attempt_id": str(attempt.id), "error": str(exc)})
            response, status, error = {}, MLTaskStatus.FAILED, str(exc)

        latency_ms = int((time.perf_counter() - started) * 1000)
        self.session.add(
            MLResult(
                kind=MLTaskKind.EVALUATION,
                endpoint="evaluate_attempt",
                status=status,
                attempt_id=attempt.id,
                lesson_id=lesson.id,
                scenario_id=attempt.scenario_id,
                request_payload=payload,
                response_payload=response,
                model=response.get("model"),
                version=response.get("version"),
                latency_ms=latency_ms,
                error=error,
            )
        )

        if status is MLTaskStatus.FAILED:
            evaluation = await self._deferred_evaluation(attempt, lesson, error or "ML недоступен")
            await outbox.enqueue(
                self.session,
                OUTBOX_TOPIC_REEVALUATE,
                {"attempt_id": str(attempt.id), "lesson_id": str(lesson.id)},
            )
            return evaluation

        return await self._persist(attempt, lesson, response)

    async def reevaluate(self, attempt_id: uuid.UUID) -> Evaluation:
        """Повторная оценка (используется outbox-воркером после восстановления ML)."""
        attempt = await self.attempts.get_or_fail(attempt_id, "Попытка не найдена")
        lesson = await self.session.get(Lesson, attempt.lesson_id)
        card = await self.session.get(IncidentCard, attempt.card_id)
        if lesson is None or card is None:
            raise NotFoundError("Занятие или карточка не найдены")
        existing = await self.evaluations.for_attempt(attempt_id)
        if existing is not None:
            if existing.source is EvaluationSource.TEACHER:
                #: Экспертную оценку автоматика не перезаписывает.
                return existing
            await self.session.delete(existing)
            await self.session.flush()
        return await self.evaluate(attempt, lesson, card)

    # ---------------------------------------------------- экспертная коррекция
    async def override(
        self,
        evaluation_id: uuid.UUID,
        data: EvaluationOverrideRequest,
        actor: User,
        request: Request | None = None,
    ) -> Evaluation:
        evaluation = await self.evaluations.get_full(evaluation_id)
        if evaluation is None:
            raise NotFoundError("Оценка не найдена")

        before = {
            "score": evaluation.score,
            "passed": evaluation.passed,
            "source": evaluation.source.value,
        }
        if evaluation.original_score is None:
            evaluation.original_score = evaluation.score
        evaluation.score = data.score
        evaluation.passed = data.passed if data.passed is not None else data.score >= 70
        evaluation.source = EvaluationSource.TEACHER
        evaluation.overridden_by_id = actor.id
        evaluation.overridden_at = utcnow()
        evaluation.override_reason = data.reason
        if data.teacher_comment:
            evaluation.teacher_comment = data.teacher_comment
        await self.session.flush()

        await self._sync_history(evaluation)

        #: ТЗ прямо требует: изменение оценки фиксируется в журнале аудита.
        await self.audit.log(
            AuditAction.GRADE_OVERRIDE,
            actor=actor,
            object_type="evaluation",
            object_id=evaluation.id,
            summary=f"Оценка изменена на {data.score} — {data.reason}",
            before=before,
            after={"score": evaluation.score, "passed": evaluation.passed, "source": "teacher"},
            request=request,
            is_security=True,
        )
        return await self.evaluations.get_full(evaluation.id)  # type: ignore[return-value]

    async def add_comment(
        self, evaluation_id: uuid.UUID, comment: str, actor: User, request: Request | None = None
    ) -> Evaluation:
        evaluation = await self.evaluations.get_full(evaluation_id)
        if evaluation is None:
            raise NotFoundError("Оценка не найдена")
        evaluation.teacher_comment = comment
        await self.session.flush()
        await self.audit.log(
            AuditAction.UPDATE,
            actor=actor,
            object_type="evaluation",
            object_id=evaluation.id,
            summary="Добавлен комментарий преподавателя",
            request=request,
        )
        return evaluation

    # ---------------------------------------------------------------- приватное
    async def _build_payload(
        self, attempt: CardAttempt, lesson: Lesson, card: IncidentCard
    ) -> dict[str, Any]:
        reference: ScenarioReference | None = None
        if attempt.reference_id:
            reference = await self.references.get(attempt.reference_id)
        elif attempt.card_id:
            reference = await self.references.for_card(attempt.card_id)

        actions = await self.actions.for_attempt(attempt.id)
        criteria = {**(lesson.success_criteria or {})}

        #: Блок реагирования — основа оценки в режиме «действия с карточками».
        statuses = sorted(attempt.response_statuses, key=lambda item: item.sequence_no)
        response = {
            "statuses": [
                {
                    "status": entry.status.value,
                    "comment": entry.comment,
                    "offset_ms": entry.offset_ms,
                    "is_primary": entry.is_primary,
                    "is_late": entry.is_late,
                    "set_by_system": entry.set_by_system,
                    "service_code": entry.service_code,
                }
                for entry in statuses
            ],
            "first_status": (
                attempt.first_response_status.value if attempt.first_response_status else None
            ),
            "first_seconds": attempt.first_response_seconds,
            "is_late": attempt.is_response_late,
            "lifecycle_status": attempt.lifecycle_status.value,
            "service_code": attempt.service_code,
            "is_primary_service": attempt.service_code
            in primary_services(attempt.notification_list or []),
            "notification_list": attempt.notification_list or [],
        }
        expected_response = (
            ((reference.expected_text or {}).get("response") if reference else None)
            or (card.expected_payload or {}).get("response")
            or {}
        )

        duration_s = (attempt.duration_ms or 0) / 1000
        return {
            "attempt_id": str(attempt.id),
            "lesson_mode": lesson.mode.value,
            "submitted_payload": attempt.submitted_payload or {},
            "draft_payload": attempt.draft_payload or {},
            "expected_fields": (reference.expected_fields if reference else card.expected_payload) or {},
            "expected_actions": (reference.expected_actions if reference else []) or [],
            "expected_text": (reference.expected_text if reference else {}) or {},
            "required_fields": (criteria.get("required_fields") or []),
            "actions": [
                {
                    "action_type": action.action_type.value,
                    "field_code": action.field_code,
                    "offset_ms": action.offset_ms,
                    "value_length": len(action.value_text or ""),
                }
                for action in actions
            ],
            "duration_seconds": duration_s,
            "norm_seconds": attempt.norm_seconds,
            "response": response,
            "expected_response": expected_response,
            "max_errors": criteria.get("max_errors", settings.DEFAULT_MAX_ERRORS),
            "min_score": criteria.get("min_score", 70.0),
            "weights": criteria.get("weights") or {},
            "address_error_factor": criteria.get(
                "address_error_factor", settings.SCORE_ADDRESS_ERROR_FACTOR
            ),
            "difficulty_weight": attempt.difficulty_weight,
        }

    async def _persist(
        self, attempt: CardAttempt, lesson: Lesson, response: dict[str, Any]
    ) -> Evaluation:
        errors_data: list[dict[str, Any]] = response.get("errors") or []
        evaluation = Evaluation(
            attempt_id=attempt.id,
            lesson_id=lesson.id,
            student_id=attempt.student_id,
            source=EvaluationSource.AI,
            score=float(response.get("score") or 0.0),
            max_score=float(response.get("max_score") or 100.0),
            passed=bool(response.get("passed")),
            timing_score=_as_float(response.get("timing_score")),
            procedure_score=_as_float(response.get("procedure_score")),
            accuracy_score=_as_float(response.get("accuracy_score")),
            grammar_score=_as_float(response.get("grammar_score")),
            error_count=len(errors_data),
            critical_error_count=sum(1 for e in errors_data if e.get("severity") == "critical"),
            details=response.get("details") or {},
            ml_model=response.get("model"),
            ml_version=response.get("version"),
        )
        self.session.add(evaluation)
        await self.session.flush()

        for item in errors_data:
            self.session.add(
                ErrorRecord(
                    evaluation_id=evaluation.id,
                    attempt_id=attempt.id,
                    category=_as_enum(ErrorCategory, item.get("category"), ErrorCategory.PROCEDURE),
                    severity=_as_enum(ErrorSeverity, item.get("severity"), ErrorSeverity.MINOR),
                    code=str(item.get("code") or "unknown")[:64],
                    message=str(item.get("message") or ""),
                    field_code=(str(item["field_code"])[:64] if item.get("field_code") else None),
                    expected=_as_text(item.get("expected")),
                    actual=_as_text(item.get("actual")),
                    position=item.get("position"),
                    penalty=float(item.get("penalty") or 0.0),
                )
            )

        self.session.add(
            TrainingHistory(
                student_id=attempt.student_id,
                lesson_id=lesson.id,
                attempt_id=attempt.id,
                scenario_id=attempt.scenario_id,
                score=evaluation.score,
                passed=evaluation.passed,
                duration_ms=attempt.duration_ms,
                error_count=evaluation.error_count,
            )
        )
        await self.session.flush()
        return await self.evaluations.get_full(evaluation.id)  # type: ignore[return-value]

    async def _deferred_evaluation(
        self, attempt: CardAttempt, lesson: Lesson, reason: str
    ) -> Evaluation:
        """Заглушка оценки на время недоступности ML: работа зафиксирована, оценка отложена."""
        evaluation = Evaluation(
            attempt_id=attempt.id,
            lesson_id=lesson.id,
            student_id=attempt.student_id,
            source=EvaluationSource.SYSTEM,
            score=0.0,
            passed=False,
            error_count=0,
            details={"deferred": True, "reason": reason[:500]},
        )
        self.session.add(evaluation)
        await self.session.flush()
        return evaluation

    async def _sync_history(self, evaluation: Evaluation) -> None:
        import sqlalchemy as sa

        await self.session.execute(
            sa.update(TrainingHistory)
            .where(TrainingHistory.attempt_id == evaluation.attempt_id)
            .values(score=evaluation.score, passed=evaluation.passed)
        )


def _as_float(value: Any) -> float | None:
    return float(value) if value is not None else None


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)[:2000]


def _as_enum(enum_cls, value: Any, default):
    try:
        return enum_cls(value)
    except (ValueError, TypeError):
        return default


async def _reevaluate_handler(session: AsyncSession, payload: dict[str, Any]) -> None:
    """Обработчик outbox: повторная оценка после восстановления ML-сервиса."""
    attempt_id = uuid.UUID(payload["attempt_id"])
    service = EvaluationService(session)
    await service.reevaluate(attempt_id)


outbox.register_handler(OUTBOX_TOPIC_REEVALUATE, _reevaluate_handler)
