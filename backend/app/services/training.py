from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from fastapi import Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import difficulty
from app.core.arm112 import (
    COMMENT_EXAMPLES,
    caller_knowledge,
    SERVICE_FORBIDDEN_STATUSES,
    primary_services,
    service_codes,
    service_title,
)
from app.core.config import settings
from app.core.exceptions import BusinessRuleError, NotFoundError, PermissionDeniedError
from app.core.logging import get_logger
from app.core.pagination import PageParams
from app.core.permissions import Perm, RoleCode
from app.core.security import new_opaque_token, utcnow
from app.integrations.monitoring import ACTIVE_ATTEMPTS, ACTIVE_LESSONS
from app.integrations.ml_client import get_ml_client
from app.integrations.telephony_client import get_telephony_client
from app.models.card import IncidentCard
from app.models.enums import (
    COMMENT_REQUIRED_STATUSES,
    LESSON_PURPOSE_TITLES,
    PRIMARY_RESPONSE_STATUSES,
    PROGRESS_RESPONSE_STATUSES,
    RESPONSE_STATUS_TITLES,
    RESPONSE_STATUS_TRANSITIONS,
    SYSTEM_RESPONSE_STATUSES,
    TERMINAL_RESPONSE_STATUSES,
    ActionType,
    AttemptStatus,
    AuditAction,
    CallDirection,
    CallStatus,
    CardLifecycleStatus,
    LessonMode,
    LessonPurpose,
    LessonStatus,
    LogLevel,
    ParticipantStatus,
    ResponseStatus,
)
from app.models.grading import Evaluation
from app.models.system import CallRecord
from app.models.training import (
    Assignment,
    CardAttempt,
    Lesson,
    LessonParticipant,
    ResponseStatusEntry,
    StudentAction,
    Workplace,
)
from app.models.user import User
from app.repositories.content import CardRepository, ReferenceRepository
from app.repositories.grading import EvaluationRepository
from app.repositories.training import (
    ActionRepository,
    AnswerRepository,
    AssignmentRepository,
    AttemptRepository,
    LessonRepository,
    ParticipantRepository,
)
from app.repositories.users import GroupRepository, UserRepository
from app.schemas.card import CardRead
from app.schemas.training import (
    ActionCreate,
    AssignmentCreate,
    LessonCreate,
    LessonFinishRequest,
    LessonUpdate,
    ResponseStatusCreate,
    SubmitRequest,
)
from app.services.audit import AuditService
from app.services.cards import CardService
from app.services.catalog import CatalogService
from app.services.evaluation import EvaluationService
from app.services.realtime import lesson_hub
from app.services.workplaces import WorkplaceService

logger = get_logger(__name__)


class AssignmentService:
    """Назначение заданий группам и обучающимся (п.2.4)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.assignments = AssignmentRepository(session)
        self.groups = GroupRepository(session)
        self.users = UserRepository(session)
        self.audit = AuditService(session)

    async def create(
        self, data: AssignmentCreate, actor: User, request: Request | None = None
    ) -> Assignment:
        if not data.group_id and not data.student_id:
            raise BusinessRuleError("Укажите группу или конкретного обучающегося")
        if data.group_id:
            await self.groups.get_or_fail(data.group_id, "Учебная группа не найдена")
        if data.student_id:
            await self.users.get_or_fail(data.student_id, "Обучающийся не найден")

        assignment = await self.assignments.create(
            **data.model_dump(), assigned_by_id=actor.id
        )
        await self.audit.log(
            AuditAction.CREATE,
            actor=actor,
            object_type="assignment",
            object_id=assignment.id,
            summary=f"Назначено задание «{assignment.title}»",
            request=request,
        )
        return assignment

    async def list_for_actor(
        self, actor: User, params: PageParams
    ) -> tuple[Sequence[Assignment], int]:
        if actor.has_role(RoleCode.STUDENT.value) and not actor.has_permission(Perm.LESSONS_MANAGE):
            group_ids = await self._group_ids(actor.id)
            import sqlalchemy as sa

            conditions = [Assignment.is_active.is_(True)]
            targets = [Assignment.student_id == actor.id]
            if group_ids:
                targets.append(Assignment.group_id.in_(group_ids))
            conditions.append(sa.or_(*targets))
            return await self.assignments.paginate(params, *conditions)
        return await self.assignments.paginate(params, Assignment.is_active.is_(True))

    async def deactivate(
        self, assignment_id: uuid.UUID, actor: User, request: Request | None = None
    ) -> None:
        assignment = await self.assignments.get_or_fail(assignment_id, "Назначение не найдено")
        await self.assignments.soft_delete(assignment)
        await self.audit.log(
            AuditAction.DELETE,
            actor=actor,
            object_type="assignment",
            object_id=assignment_id,
            summary="Назначение отменено",
            request=request,
        )

    async def _group_ids(self, student_id: uuid.UUID) -> list[uuid.UUID]:
        import sqlalchemy as sa

        from app.models.user import group_members

        stmt = sa.select(group_members.c.group_id).where(group_members.c.user_id == student_id)
        return list((await self.session.execute(stmt)).scalars().all())


class TrainingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.lessons = LessonRepository(session)
        self.participants = ParticipantRepository(session)
        self.attempts = AttemptRepository(session)
        self.actions = ActionRepository(session)
        self.answers = AnswerRepository(session)
        self.cards = CardRepository(session)
        self.references = ReferenceRepository(session)
        self.evaluations = EvaluationRepository(session)
        self.users = UserRepository(session)
        self.groups = GroupRepository(session)
        self.assignments = AssignmentRepository(session)
        self.audit = AuditService(session)
        self.catalog = CatalogService(session)
        self.evaluator = EvaluationService(session)
        self.card_service = CardService(session)
        self.workplaces = WorkplaceService(session)
        self.telephony = get_telephony_client()

    async def create_lesson(
        self, data: LessonCreate, actor: User, request: Request | None = None
    ) -> Lesson:
        student_ids = list(data.student_ids)
        if data.group_id and not student_ids:
            students = await self.users.students_of_group(data.group_id)
            student_ids = [student.id for student in students]
        if not student_ids:
            raise BusinessRuleError("Не выбраны обучающиеся: укажите группу или список участников")

        if data.assignment_id:
            await self.assignments.get_or_fail(data.assignment_id, "Назначение не найдено")

        time_limit = await self.catalog.resolve_time_limit(
            category_id=(data.category_ids[0] if data.category_ids else None),
            mode=data.mode,
            explicit=data.time_limit_seconds,
        )
        criteria = {
            "max_errors": settings.DEFAULT_MAX_ERRORS,
            "min_score": 70.0,
            **(data.success_criteria or {}),
        }
        weight, level = difficulty.resolve(data.difficulty_weight, data.difficulty)

        lesson = Lesson(
            title=data.title,
            mode=data.mode,
            purpose=data.purpose,
            passing_score=data.passing_score
            or (settings.ATTESTATION_PASS_SCORE if data.purpose is not LessonPurpose.TRAINING else None),
            teacher_id=actor.id,
            group_id=data.group_id,
            assignment_id=data.assignment_id,
            category_ids=[str(cid) for cid in data.category_ids],
            card_source=data.card_source,
            difficulty=data.difficulty or level,
            difficulty_weight=weight,
            adaptive_difficulty=(
                data.adaptive_difficulty and data.purpose is not LessonPurpose.ATTESTATION
            ),
            time_limit_seconds=time_limit,
            max_cards=data.max_cards,
            success_criteria=criteria,
            status=LessonStatus.PLANNED,
        )
        for student_id in dict.fromkeys(student_ids):
            lesson.participants.append(
                LessonParticipant(student_id=student_id, resume_token=new_opaque_token(24))
            )
        self.session.add(lesson)
        await self.session.flush()

        await self.audit.log(
            AuditAction.CREATE,
            actor=actor,
            object_type="lesson",
            object_id=lesson.id,
            summary=(
                f"{LESSON_PURPOSE_TITLES[lesson.purpose]}: «{lesson.title}» "
                f"({len(student_ids)} участников)"
            ),
            after={
                "mode": lesson.mode.value,
                "purpose": lesson.purpose.value,
                "time_limit": time_limit,
                "passing_score": lesson.passing_score,
            },
            request=request,
        )
        return await self.get_lesson(lesson.id)

    async def get_lesson(self, lesson_id: uuid.UUID) -> Lesson:
        lesson = await self.lessons.get_full(lesson_id)
        if lesson is None:
            raise NotFoundError("Занятие не найдено")
        return lesson

    async def get_lesson_light(self, lesson_id: uuid.UUID) -> Lesson:
        lesson = await self.lessons.get_light(lesson_id)
        if lesson is None:
            raise NotFoundError("Занятие не найдено")
        return lesson

    async def list_lessons(
        self, actor: User, params: PageParams, *, status: LessonStatus | None = None
    ) -> tuple[Sequence[Lesson], int]:
        conditions = []
        if status:
            conditions.append(Lesson.status == status)
        if actor.has_permission(Perm.LESSONS_MANAGE):
            conditions.append(Lesson.teacher_id == actor.id)
        elif actor.has_permission(Perm.LESSONS_PARTICIPATE):
            import sqlalchemy as sa

            stmt = (
                sa.select(Lesson)
                .join(LessonParticipant, LessonParticipant.lesson_id == Lesson.id)
                .where(LessonParticipant.student_id == actor.id)
            )
            return await self.lessons.paginate(params, *conditions, stmt=stmt)
        return await self.lessons.paginate(params, *conditions)

    async def update_lesson(
        self, lesson_id: uuid.UUID, data: LessonUpdate, actor: User, request: Request | None = None
    ) -> Lesson:
        lesson = await self.get_lesson(lesson_id)
        self._ensure_owner(lesson, actor)
        if lesson.status is not LessonStatus.PLANNED:
            raise BusinessRuleError("Параметры можно менять только до старта занятия")
        values = data.model_dump(exclude_unset=True)
        if "category_ids" in values and values["category_ids"] is not None:
            values["category_ids"] = [str(cid) for cid in values["category_ids"]]
        for field, value in values.items():
            if value is not None:
                setattr(lesson, field, value)
        await self.session.flush()
        await self.audit.log(
            AuditAction.UPDATE,
            actor=actor,
            object_type="lesson",
            object_id=lesson.id,
            summary="Изменены параметры занятия",
            request=request,
        )
        return await self.get_lesson(lesson_id)

    async def start_lesson(
        self, lesson_id: uuid.UUID, actor: User, request: Request | None = None
    ) -> Lesson:
        lesson = await self.get_lesson(lesson_id)
        self._ensure_owner(lesson, actor)
        if lesson.status is LessonStatus.RUNNING:
            return lesson
        if lesson.status in (LessonStatus.FINISHED, LessonStatus.ABORTED):
            raise BusinessRuleError("Завершённое занятие нельзя запустить повторно")

        running = await self.lessons.active_count()
        if running >= settings.MAX_CONCURRENT_SESSIONS:
            raise BusinessRuleError(
                f"Достигнут предел одновременных занятий ({settings.MAX_CONCURRENT_SESSIONS}). "
                "Дождитесь завершения активных или увеличьте MAX_CONCURRENT_SESSIONS."
            )

        pool = await self.cards.pool_size(
            category_ids=self._category_uuids(lesson),
            source=lesson.card_source,
        )
        if pool == 0:
            raise BusinessRuleError(
                "В выбранных категориях нет утверждённых карточек. "
                "Сгенерируйте сценарии и утвердите эталоны перед занятием."
            )

        lesson.status = LessonStatus.RUNNING
        lesson.started_at = utcnow()
        await self.session.flush()
        ACTIVE_LESSONS.set(await self.lessons.active_count())

        await self.audit.log(
            AuditAction.LESSON_START,
            actor=actor,
            object_type="lesson",
            object_id=lesson.id,
            summary=f"Занятие запущено, карточек в пуле: {pool}",
            request=request,
        )
        await lesson_hub.publish(lesson.id, "lesson_started", {"started_at": lesson.started_at.isoformat()})
        return await self.get_lesson(lesson_id)

    async def finish_lesson(
        self,
        lesson_id: uuid.UUID,
        data: LessonFinishRequest,
        actor: User,
        request: Request | None = None,
        aborted: bool = False,
    ) -> Lesson:
        """Преподаватель может завершить занятие в любой момент (п.10 ТЗ)."""
        lesson = await self.get_lesson(lesson_id)
        self._ensure_owner(lesson, actor)
        if lesson.status in (LessonStatus.FINISHED, LessonStatus.ABORTED):
            return lesson

        for attempt in await self.attempts.for_lesson(lesson_id):
            if attempt.status in AttemptRepository.ACTIVE_STATUSES:
                await self._close_attempt(attempt, lesson, status=AttemptStatus.EXPIRED)

        for participant in lesson.participants:
            participant.status = ParticipantStatus.FINISHED
            participant.left_at = utcnow()
            await self.workplaces.release(participant.student_id)

        await self._finalize_results(lesson)

        lesson.status = LessonStatus.ABORTED if aborted else LessonStatus.FINISHED
        lesson.finished_at = utcnow()
        lesson.finished_by_id = actor.id
        lesson.abort_reason = data.reason
        await self.session.flush()
        ACTIVE_LESSONS.set(await self.lessons.active_count())
        ACTIVE_ATTEMPTS.set(await self.attempts.active_total())

        await self.audit.log(
            AuditAction.LESSON_FINISH,
            actor=actor,
            object_type="lesson",
            object_id=lesson.id,
            summary=data.reason or "Занятие завершено преподавателем",
            request=request,
        )
        await lesson_hub.publish(lesson.id, "lesson_finished", {"reason": data.reason})
        return await self.get_lesson(lesson_id)

    async def _finalize_results(self, lesson: Lesson) -> None:
        threshold = (
            lesson.passing_score
            or (lesson.success_criteria or {}).get("min_score")
            or settings.ATTESTATION_PASS_SCORE
        )
        is_exam = lesson.purpose in (LessonPurpose.ATTESTATION, LessonPurpose.REFRESHER)
        for participant in lesson.participants:
            average = await self.evaluations.avg_score(
                Evaluation.lesson_id == lesson.id,
                Evaluation.student_id == participant.student_id,
            )
            participant.final_score = round(average, 2) if average is not None else None
            participant.is_passed = (
                None if not is_exam else bool(average is not None and average >= float(threshold))
            )
        await self.session.flush()

        if is_exam:
            await self.audit.log(
                AuditAction.LESSON_FINISH,
                actor=None,
                actor_username="система",
                object_type="lesson",
                object_id=lesson.id,
                summary=f"Подведены итоги: {LESSON_PURPOSE_TITLES[lesson.purpose]}",
                after={
                    "passing_score": float(threshold),
                    "results": {
                        str(participant.student_id): {
                            "score": participant.final_score,
                            "passed": participant.is_passed,
                        }
                        for participant in lesson.participants
                    },
                },
            )

    async def join(
        self, lesson_id: uuid.UUID, student: User, workplace_number: str | None = None
    ) -> dict[str, Any]:
        lesson = await self.get_lesson_light(lesson_id)
        participant = await self._participant(lesson, student.id)

        participant.status = ParticipantStatus.ONLINE
        participant.joined_at = participant.joined_at or utcnow()
        participant.last_seen_at = utcnow()

        workplace = None
        if workplace_number:
            workplace = await self.workplaces.occupy(workplace_number, student)
            participant.workplace_id = workplace.id
        elif participant.workplace_id is None:
            workplace = await self.workplaces.bind_participant(participant, student.id)
        await self.session.flush()

        attempt = await self.attempts.active_for_participant(participant.id)
        await lesson_hub.publish(
            lesson.id,
            "participant_online",
            {
                "student_id": str(student.id),
                "workplace": workplace.number if workplace else None,
            },
        )
        return {
            "lesson": lesson,
            "participant": participant,
            "active_attempt": await self._attempt_view(attempt) if attempt else None,
            "resume_token": participant.resume_token,
            "workplace": workplace.number if workplace else None,
        }

    async def resume(self, resume_token: str) -> dict[str, Any]:
        """Восстановление сессии после сетевого сбоя (п.2.8: до 30 секунд)."""
        participant = await self.participants.by_resume_token(resume_token)
        if participant is None:
            raise NotFoundError("Сессия не найдена: токен возобновления недействителен")
        lesson = await self.get_lesson_light(participant.lesson_id)

        gap = None
        if participant.last_seen_at:
            gap = (utcnow() - participant.last_seen_at).total_seconds()
        participant.status = ParticipantStatus.ONLINE
        participant.last_seen_at = utcnow()
        await self.session.flush()

        attempt = await self.attempts.active_for_participant(participant.id)
        return {
            "lesson": lesson,
            "active_attempt": await self._attempt_view(attempt) if attempt else None,
            "restored_state": {
                **(participant.state or {}),
                "offline_seconds": gap,
                "within_grace_period": (gap is None or gap <= settings.SESSION_RECOVERY_GRACE_SECONDS),
                "draft_payload": attempt.draft_payload if attempt else {},
            },
        }

    async def heartbeat(self, lesson_id: uuid.UUID, student: User, state: dict[str, Any] | None = None) -> None:
        lesson = await self.get_lesson_light(lesson_id)
        participant = await self._participant(lesson, student.id)
        participant.last_seen_at = utcnow()
        participant.status = ParticipantStatus.ONLINE
        if state:
            participant.state = state
        await self.session.flush()

    async def issue_next_card(self, lesson_id: uuid.UUID, student: User) -> dict[str, Any]:
        lesson = await self.get_lesson_light(lesson_id)
        if lesson.status is not LessonStatus.RUNNING:
            raise BusinessRuleError("Занятие не запущено преподавателем")
        participant = await self._participant(lesson, student.id, lock=True)

        window = self._stream_window(lesson)
        active = await self.attempts.active_stream(participant.id)
        if len(active) >= window:
            return await self._attempt_view(active[0])

        issued: list[CardAttempt] = []
        while len(active) + len(issued) < window:
            attempt = await self._issue_one(lesson, participant, student)
            if attempt is None:
                break
            issued.append(attempt)

        if not issued and not active:
            if lesson.max_cards and participant.cards_issued >= lesson.max_cards:
                raise BusinessRuleError("Все карточки занятия отработаны")
            raise BusinessRuleError("Нет доступных карточек для выдачи")

        ACTIVE_ATTEMPTS.set(await self.attempts.active_total())
        current = active[0] if active else issued[0]
        return await self._attempt_view(current)

    async def _issue_one(
        self, lesson: Lesson, participant: LessonParticipant, student: User
    ) -> CardAttempt | None:
        """Создаёт одну попытку. ``None`` — если выдавать больше нечего."""
        if lesson.max_cards and participant.cards_issued >= lesson.max_cards:
            return None

        weight = self._participant_weight(lesson, participant)
        open_now = [item.card_id for item in await self.attempts.active_stream(participant.id)]
        card = await self._take_assigned_card(participant, forbid_ids=open_now)
        if card is None:
            card = await self.cards.pick_random(
                category_ids=self._category_uuids(lesson),
                source=lesson.card_source,
                difficulty=(
                    difficulty.level_of(weight) if lesson.adaptive_difficulty else lesson.difficulty
                ),
                exclude_ids=await self.attempts.issued_card_ids(participant.id),
                forbid_ids=open_now,
            )
        if card is None:
            return None

        norm_seconds = await self.catalog.resolve_time_limit(
            category_id=card.category_id,
            mode=lesson.mode,
            explicit=card.time_limit_seconds or lesson.time_limit_seconds,
        )
        reference = await self.references.for_card(card.id)

        attempt = CardAttempt(
            lesson_id=lesson.id,
            participant_id=participant.id,
            student_id=student.id,
            card_id=card.id,
            scenario_id=card.scenario_id,
            reference_id=reference.id if reference else None,
            sequence_no=await self.attempts.next_sequence_no(participant.id),
            status=AttemptStatus.ISSUED,
            issued_at=utcnow(),
            norm_seconds=norm_seconds,
            difficulty_weight=weight,
            workplace_id=participant.workplace_id,
        )
        if lesson.mode is LessonMode.CARD_ACTION:
            work_limit = int(
                (lesson.success_criteria or {}).get("work_limit_seconds")
                or settings.CARD_ACTION_WORK_LIMIT_SECONDS
            )
            attempt.work_deadline_at = attempt.issued_at + _seconds(work_limit)
            attempt.deadline_at = attempt.issued_at + _seconds(max(work_limit, norm_seconds))
        else:
            #: Норматив заполнения (norm_seconds) штрафует за перерасход при оценке, но карточку
            #: не отнимает: оператор ещё говорит с заявителем. Сама закрывается только брошенная.
            attempt.deadline_at = attempt.issued_at + _seconds(
                max(norm_seconds, settings.CARD_FILL_HARD_LIMIT_SECONDS)
            )
        attempt.notification_list = list(card.notification_list or [])
        attempt.service_code = self._student_service(lesson, attempt.notification_list)
        attempt.response_statuses = []
        attempt.processings = []
        self.session.add(attempt)
        participant.cards_issued += 1
        await self.session.flush()

        #: В режиме заполнения карточки занятие начинается с имитации вызова.
        if lesson.mode is LessonMode.CARD_FILL:
            await self._originate_call(lesson, attempt, card, student)
        else:
            await self._open_response_block(attempt, lesson, student, norm_seconds)

        await lesson_hub.publish(
            lesson.id,
            "card_issued",
            {
                "student_id": str(student.id),
                "attempt_id": str(attempt.id),
                "card_no": card.card_no,
                "workplace": participant.workplace.number if participant.workplace else None,
                "difficulty_weight": weight,
                "deadline_at": attempt.deadline_at.isoformat() if attempt.deadline_at else None,
                "response_deadline_at": (
                    attempt.response_deadline_at.isoformat()
                    if attempt.response_deadline_at
                    else None
                ),
            },
        )
        return attempt

    async def _take_assigned_card(
        self, participant: LessonParticipant, *, forbid_ids: list[uuid.UUID]
    ) -> IncidentCard | None:
        queue = list(participant.assigned_card_ids or [])
        if not queue:
            return None

        forbidden = {str(value) for value in forbid_ids}
        for index, raw in enumerate(queue):
            if str(raw) in forbidden:
                continue
            try:
                card_id = uuid.UUID(str(raw))
            except ValueError:
                participant.assigned_card_ids = [*queue[:index], *queue[index + 1 :]]
                return await self._take_assigned_card(participant, forbid_ids=forbid_ids)

            card = await self.cards.get(card_id)
            participant.assigned_card_ids = [*queue[:index], *queue[index + 1 :]]
            if card is None or not card.is_active:
                logger.info("assigned_card_missing", extra={"card_id": str(card_id)})
                return await self._take_assigned_card(participant, forbid_ids=forbid_ids)
            return card
        return None

    async def assign_cards_to_workplaces(
        self,
        lesson_id: uuid.UUID,
        assignments: dict[str, uuid.UUID],
        actor: User,
        request: Request | None = None,
    ) -> dict[str, Any]:
        lesson = await self.get_lesson(lesson_id)
        self._ensure_owner(lesson, actor, allow_monitor=True)

        assigned: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []
        for number, card_id in assignments.items():
            workplace = await self.workplaces.by_number(str(number))
            if workplace is None:
                skipped.append({"workplace": str(number), "reason": "рабочее место не найдено"})
                continue
            if workplace.occupied_by_id is None:
                skipped.append({"workplace": str(number), "reason": "за местом никто не работает"})
                continue

            card = await self.cards.get(card_id)
            if card is None or not card.is_active:
                skipped.append({"workplace": str(number), "reason": "карточка не найдена"})
                continue

            participant = await self.participants.get_for(lesson.id, workplace.occupied_by_id)
            if participant is None:
                skipped.append(
                    {"workplace": str(number), "reason": "обучающийся не участвует в занятии"}
                )
                continue

            participant.assigned_card_ids = [
                *(participant.assigned_card_ids or []),
                str(card.id),
            ]
            participant.workplace_id = workplace.id
            assigned.append(
                {
                    "workplace": workplace.number,
                    "student_id": str(workplace.occupied_by_id),
                    "card_id": str(card.id),
                    "card_no": card.card_no,
                }
            )

        await self.session.flush()
        if assigned:
            await self.audit.log(
                AuditAction.UPDATE,
                actor=actor,
                object_type="lesson",
                object_id=lesson.id,
                summary=f"Розданы задания по рабочим местам: {len(assigned)}",
                after={"assigned": assigned},
                request=request,
            )
            for item in assigned:
                await lesson_hub.publish(
                    lesson.id,
                    "card_assigned",
                    {
                        "student_id": item["student_id"],
                        "workplace": item["workplace"],
                        "card_no": item["card_no"],
                    },
                )
        return {"assigned": assigned, "skipped": skipped}

    def _stream_window(self, lesson: Lesson) -> int:
        if lesson.mode is not LessonMode.CARD_ACTION:
            return 1
        configured = (lesson.success_criteria or {}).get("stream_window")
        try:
            window = int(configured) if configured is not None else settings.CARD_STREAM_WINDOW
        except (TypeError, ValueError):
            window = settings.CARD_STREAM_WINDOW
        if lesson.max_cards:
            window = min(window, lesson.max_cards)
        return max(1, window)

    def _participant_weight(self, lesson: Lesson, participant: LessonParticipant) -> int:
        """Текущий вес сложности для этого обучающегося (шкала 1–10)."""
        if participant.difficulty_weight is not None:
            return difficulty.clamp_weight(participant.difficulty_weight)
        weight, _ = difficulty.resolve(lesson.difficulty_weight, lesson.difficulty)
        return weight

    async def incident_list(self, lesson_id: uuid.UUID, student: User) -> dict[str, Any]:
        lesson = await self.get_lesson_light(lesson_id)
        participant = await self._participant(lesson, student.id)
        attempts = await self.attempts.active_stream(participant.id)
        now = utcnow()

        rows = []
        for attempt in attempts:
            card = await self.session.get(IncidentCard, attempt.card_id)
            rows.append(
                {
                    "attempt_id": str(attempt.id),
                    "sequence_no": attempt.sequence_no,
                    "card_no": card.card_no if card else None,
                    "title": card.title if card else None,
                    "status": attempt.status.value,
                    "lifecycle_status": attempt.lifecycle_status.value,
                    "difficulty_weight": attempt.difficulty_weight,
                    "issued_at": attempt.issued_at.isoformat(),
                    "opened_at": attempt.opened_at.isoformat() if attempt.opened_at else None,
                    "first_response_status": (
                        attempt.first_response_status.value
                        if attempt.first_response_status
                        else None
                    ),
                    #: Сколько осталось на первичный статус: главный индикатор строки.
                    "response_seconds_left": _seconds_left(attempt.response_deadline_at, now),
                    #: И сколько на отработку карточки целиком.
                    "work_seconds_left": _seconds_left(
                        attempt.work_deadline_at or attempt.deadline_at, now
                    ),
                    "is_response_late": attempt.is_response_late,
                    "service_code": attempt.service_code,
                }
            )

        return {
            "lesson_id": str(lesson.id),
            "mode": lesson.mode.value,
            "stream_window": self._stream_window(lesson),
            "workplace": (
                participant.workplace.number if participant.workplace else None
            ),
            "cards_issued": participant.cards_issued,
            "cards_submitted": participant.cards_submitted,
            "max_cards": lesson.max_cards,
            "rows": rows,
        }

    async def my_attempts(self, lesson_id: uuid.UUID, student: User) -> list[dict[str, Any]]:
        """Все карточки обучающегося в занятии, новые сверху: очередь и история на АРМ.

        Закрытые тоже — после перезагрузки страницы обучающийся видит свою работу и оценки.
        """
        lesson = await self.get_lesson_light(lesson_id)
        participant = await self._participant(lesson, student.id)
        rows = []
        for attempt in await self.attempts.for_participant(participant.id):
            card = await self.session.get(IncidentCard, attempt.card_id)
            evaluation = await self.evaluations.for_attempt(attempt.id)
            sent = attempt.submitted_payload or {}
            rows.append(
                {
                    "attempt_id": attempt.id,
                    "card_no": card.card_no if card else None,
                    #: что сохранил сам обучающийся (для строки очереди)
                    "incident_class": sent.get("incident_class"),
                    "address": sent.get("address_text") or sent.get("address_street"),
                    "phone": sent.get("aon_phone"),
                    "status": attempt.status,
                    "issued_at": attempt.issued_at,
                    "submitted_at": attempt.submitted_at,
                    "first_response_status": attempt.first_response_status,
                    "last_response_status": attempt.last_response_status,
                    "score": evaluation.score if evaluation else None,
                    "passed": evaluation.passed if evaluation else None,
                }
            )
        return rows

    async def open_card(self, attempt_id: uuid.UUID, student: User) -> CardAttempt:
        attempt = await self._own_active_attempt(attempt_id, student)
        if attempt.opened_at is None:
            attempt.opened_at = utcnow()
            await self.session.flush()
        return attempt

    async def dialogue_turn(self, attempt_id: uuid.UUID, data: dict[str, Any], student: User) -> dict[str, Any]:
        """Реплика заявителя для звонка «в браузере»: карточку в ML подставляет сервер."""
        attempt = await self._own_active_attempt(attempt_id, student)
        card = await self.cards.get_or_fail(attempt.card_id, "Карточка не найдена")
        payload = {
            "session_id": str(attempt.lesson_id),
            "scenario_id": "",
            "call_id": f"web-{attempt.id}",
            "call_type": "incident_112",
            "persona": {"service": "Заявитель", "name": (card.caller_profile or {}).get("name"),
                        "position": "заявитель", "gender": (card.caller_profile or {}).get("gender")},
            "context": {"card": caller_knowledge(card.title, card.expected_payload, card.caller_profile)},
            "turn": int(data.get("turn") or 0),
            "history": list(data.get("history") or [])[-30:],
            "operator_text": data.get("operator_text"),
        }
        return await get_ml_client().dialogue_turn(payload)

    async def attempt_with_card(self, attempt_id: uuid.UUID, actor: User) -> dict[str, Any]:
        """Попытка с карточкой по тем же правилам видимости, что при выдаче (в режиме 112 карточка скрыта)."""
        attempt = await self.get_attempt(attempt_id, actor)
        return await self._attempt_view(attempt)

    async def get_attempt(self, attempt_id: uuid.UUID, actor: User) -> CardAttempt:
        attempt = await self.attempts.get_or_fail(attempt_id, "Попытка не найдена")
        await self._ensure_attempt_access(attempt, actor)
        return attempt

    async def save_draft(self, attempt_id: uuid.UUID, payload: dict[str, Any], student: User) -> CardAttempt:
        attempt = await self._own_active_attempt(attempt_id, student)
        attempt.draft_payload = payload
        if attempt.status is AttemptStatus.ISSUED:
            attempt.status = AttemptStatus.IN_PROGRESS
            attempt.started_at = attempt.started_at or utcnow()
        await self.session.flush()
        return attempt

    async def record_action(
        self, attempt_id: uuid.UUID, data: ActionCreate, student: User
    ) -> StudentAction:
        attempt = await self._own_active_attempt(attempt_id, student)
        if attempt.status is AttemptStatus.ISSUED:
            attempt.status = AttemptStatus.IN_PROGRESS
            attempt.started_at = attempt.started_at or utcnow()

        now = utcnow()
        action = StudentAction(
            attempt_id=attempt.id,
            lesson_id=attempt.lesson_id,
            student_id=student.id,
            action_type=data.action_type,
            sequence_no=await self.actions.next_sequence_no(attempt.id),
            field_code=data.field_code,
            value_text=data.value_text,
            payload=data.payload,
            at=now,
            client_at=data.client_at,
            offset_ms=int((now - attempt.issued_at).total_seconds() * 1000),
        )
        self.session.add(action)

        if data.action_type is ActionType.FIELD_FILLED and data.field_code:
            draft = dict(attempt.draft_payload or {})
            draft[data.field_code] = data.value_text
            attempt.draft_payload = draft

        await self.session.flush()
        return action

    async def response_options(self, attempt_id: uuid.UUID, student: User) -> dict[str, Any]:
        """Какие статусы доступны прямо сейчас — для выпадающего списка на АРМ-112."""
        attempt = await self.attempts.get_or_fail(attempt_id, "Попытка не найдена")
        await self._ensure_attempt_access(attempt, student)
        lesson = await self.get_lesson_light(attempt.lesson_id)

        current = attempt.last_response_status
        allowed = RESPONSE_STATUS_TRANSITIONS.get(current, ()) if current else ()
        forbidden = set(SYSTEM_RESPONSE_STATUSES) | SERVICE_FORBIDDEN_STATUSES.get(
            attempt.service_code or "", set()
        )
        if lesson.mode is not LessonMode.CARD_ACTION or attempt.status not in (
            AttemptStatus.ISSUED,
            AttemptStatus.IN_PROGRESS,
        ):
            allowed = ()
        else:
            allowed = tuple(status for status in allowed if status not in forbidden)

        now = utcnow()
        seconds_left = None
        if attempt.response_deadline_at and attempt.first_response_at is None:
            seconds_left = (attempt.response_deadline_at - now).total_seconds()

        return {
            "current_status": current,
            "available": [
                {
                    "status": status.value,
                    "title": RESPONSE_STATUS_TITLES[status],
                    "comment_required": status in COMMENT_REQUIRED_STATUSES,
                    "closes_card": status in TERMINAL_RESPONSE_STATUSES,
                }
                for status in allowed
            ],
            "comment_required": sorted(COMMENT_REQUIRED_STATUSES, key=lambda s: s.value),
            "response_seconds_left": seconds_left,
            "primary_status_set": attempt.first_response_at is not None,
            "service_code": attempt.service_code,
            "service_name": service_title(attempt.service_code) if attempt.service_code else None,
            "is_primary_service": attempt.service_code in primary_services(attempt.notification_list or []),
            "notification_list": attempt.notification_list or [],
            "comment_examples": COMMENT_EXAMPLES,
        }

    async def set_response_status(
        self, attempt_id: uuid.UUID, data: ResponseStatusCreate, student: User
    ) -> dict[str, Any]:
        attempt = await self._own_active_attempt(attempt_id, student, lock=True)
        lesson = await self.get_lesson_light(attempt.lesson_id)
        if lesson.mode is not LessonMode.CARD_ACTION:
            raise BusinessRuleError(
                "Статусы реагирования проставляются в режиме «действия с карточками»"
            )
        if data.status in SYSTEM_RESPONSE_STATUSES:
            raise BusinessRuleError(
                f"Статус «{RESPONSE_STATUS_TITLES[data.status]}» проставляется системой автоматически"
            )

        service_code = data.service_code or attempt.service_code
        known_services = service_codes(attempt.notification_list or [])
        if known_services and service_code not in known_services:
            raise BusinessRuleError(
                f"Служба «{service_title(service_code or '—')}» отсутствует в списке оповещения карточки",
                code="service_not_in_notification_list",
            )
        if data.status in SERVICE_FORBIDDEN_STATUSES.get(service_code or "", set()):
            raise BusinessRuleError(
                f"Служба «{service_title(service_code or '')}» не проставляет статус "
                f"«{RESPONSE_STATUS_TITLES[data.status]}»: вместо него используется "
                "«Работы завершены» с комментарием о завершении работ без бригады",
                code="response_status_not_allowed_for_service",
            )

        current = attempt.last_response_status
        allowed = RESPONSE_STATUS_TRANSITIONS.get(current, ()) if current else ()
        if data.status not in allowed:
            available = ", ".join(f"«{RESPONSE_STATUS_TITLES[s]}»" for s in allowed) or "нет доступных"
            current_title = RESPONSE_STATUS_TITLES[current] if current else "—"
            raise BusinessRuleError(
                f"Из статуса «{current_title}» нельзя перейти в "
                f"«{RESPONSE_STATUS_TITLES[data.status]}». Доступны: {available}",
                code="response_status_transition_denied",
            )

        comment = (data.comment or "").strip() or None
        if data.status in COMMENT_REQUIRED_STATUSES and not comment:
            raise BusinessRuleError(
                f"Для статуса «{RESPONSE_STATUS_TITLES[data.status]}» обязателен комментарий "
                "с причиной и сведениями о передаче информации",
                code="response_comment_required",
            )

        now = utcnow()
        offset_ms = int((now - attempt.issued_at).total_seconds() * 1000)
        is_primary = data.status in PRIMARY_RESPONSE_STATUSES and attempt.first_response_at is None
        is_late = bool(
            is_primary and attempt.response_deadline_at and now > attempt.response_deadline_at
        )

        entry = ResponseStatusEntry(
            lesson_id=lesson.id,
            student_id=student.id,
            service_code=service_code,
            service_name=service_title(service_code) if service_code else student.organization,
            status=data.status,
            sequence_no=len(attempt.response_statuses) + 1,
            comment=comment,
            work_order_no=data.work_order_no,
            at=now,
            offset_ms=offset_ms,
            is_primary=is_primary,
            is_late=is_late,
            set_by_system=False,
        )
        attempt.response_statuses.append(entry)

        attempt.last_response_status = data.status
        if is_primary:
            attempt.first_response_status = data.status
            attempt.first_response_at = now
            attempt.first_response_seconds = round(offset_ms / 1000, 3)
            attempt.is_response_late = is_late
        attempt.lifecycle_status = self._lifecycle_for(attempt, data.status)

        self.session.add(
            StudentAction(
                attempt_id=attempt.id,
                lesson_id=lesson.id,
                student_id=student.id,
                action_type=ActionType.RESPONSE_STATUS_SET,
                sequence_no=await self.actions.next_sequence_no(attempt.id),
                field_code=data.status.value,
                value_text=comment,
                payload={"status": data.status.value, "work_order_no": data.work_order_no},
                at=now,
                client_at=data.client_at,
                offset_ms=offset_ms,
            )
        )
        if attempt.status is AttemptStatus.ISSUED:
            attempt.status = AttemptStatus.IN_PROGRESS
            attempt.started_at = attempt.started_at or now
        await self.session.flush()

        await lesson_hub.publish(
            lesson.id,
            "response_status_set",
            {
                "student_id": str(student.id),
                "attempt_id": str(attempt.id),
                "status": data.status.value,
                "title": RESPONSE_STATUS_TITLES[data.status],
                "is_late": is_late,
                "seconds": attempt.first_response_seconds if is_primary else None,
            },
        )

        closed = data.status in TERMINAL_RESPONSE_STATUSES
        evaluation = None
        next_view = None
        if closed:
            card = await self.cards.get_or_fail(attempt.card_id, "Карточка не найдена")
            attempt.submitted_payload = attempt.draft_payload or {}
            await self._close_attempt(attempt, lesson, status=AttemptStatus.SUBMITTED, card=card)
            evaluation = await self.evaluations.for_attempt(attempt.id)
            participant = await self._participant(lesson, student.id, lock=True)
            participant.cards_submitted += 1
            self._adapt_difficulty(lesson, participant, evaluation)
            await self.session.flush()
            if lesson.status is LessonStatus.RUNNING:
                try:
                    next_view = await self.issue_next_card(lesson.id, student)
                except BusinessRuleError as exc:
                    logger.info("next_card_not_issued", extra={"reason": str(exc)})

        return {
            "entry": entry,
            "attempt": attempt,
            "card_closed": closed,
            "evaluation": evaluation,
            "next_attempt": next_view,
        }

    async def _promote_student_card(
        self,
        attempt: CardAttempt,
        lesson: Lesson,
        evaluation: Evaluation | None,
        student: User,
    ) -> None:
        if lesson.mode is not LessonMode.CARD_FILL:
            return
        if evaluation is None or not evaluation.passed:
            return
        if not attempt.submitted_payload:
            return
        try:
            await self.card_service.create_from_attempt(attempt, student)
        except BusinessRuleError as exc:
            logger.info("student_card_not_promoted", extra={"reason": str(exc)})

    def _adapt_difficulty(
        self, lesson: Lesson, participant: LessonParticipant, evaluation: Evaluation | None
    ) -> None:
        if not lesson.adaptive_difficulty or lesson.purpose is LessonPurpose.ATTESTATION:
            return

        current = self._participant_weight(lesson, participant)
        new_weight, reason = difficulty.adapt(current, evaluation.score if evaluation else None)
        participant.difficulty_weight = new_weight
        participant.difficulty_log = [
            *(participant.difficulty_log or []),
            {
                "at": utcnow().isoformat(),
                "from": current,
                "to": new_weight,
                "score": evaluation.score if evaluation else None,
                "reason": reason,
            },
        ][-20:]

    def _lifecycle_for(self, attempt: CardAttempt, status: ResponseStatus) -> CardLifecycleStatus:
        if status is ResponseStatus.WORK_COMPLETED:
            return CardLifecycleStatus.COMPLETED
        if attempt.is_response_late:
            return CardLifecycleStatus.NOT_NOTIFIED
        if status in COMMENT_REQUIRED_STATUSES:
            return CardLifecycleStatus.REFUSAL
        if status is ResponseStatus.ACCEPTED:
            #: Служба пересмотрела решение — карточка снова в работе.
            return CardLifecycleStatus.REGISTERED
        if attempt.lifecycle_status is CardLifecycleStatus.REFUSAL:
            return CardLifecycleStatus.REGISTERED
        return attempt.lifecycle_status

    async def _open_response_block(
        self, attempt: CardAttempt, lesson: Lesson, student: User, norm_seconds: int
    ) -> None:
        """Системные отметки «Добавлена» и «Получена службой» + отсчёт норматива."""
        attempt.response_deadline_at = attempt.issued_at + _seconds(norm_seconds)
        attempt.lifecycle_status = CardLifecycleStatus.REGISTERED
        service_name = (
            service_title(attempt.service_code) if attempt.service_code else student.organization
        )
        for index, status in enumerate((ResponseStatus.ADDED, ResponseStatus.RECEIVED), start=1):
            attempt.response_statuses.append(
                ResponseStatusEntry(
                    lesson_id=lesson.id,
                    student_id=None,
                    service_code=attempt.service_code,
                    service_name=service_name,
                    status=status,
                    sequence_no=index,
                    at=attempt.issued_at,
                    offset_ms=0,
                    set_by_system=True,
                )
            )
        attempt.last_response_status = ResponseStatus.RECEIVED
        await self.session.flush()

    async def submit(
        self, attempt_id: uuid.UUID, data: SubmitRequest, student: User
    ) -> dict[str, Any]:
        attempt = await self._own_active_attempt(attempt_id, student)
        lesson = await self.get_lesson_light(attempt.lesson_id)
        card = await self.cards.get_or_fail(attempt.card_id, "Карточка не найдена")

        attempt.submitted_payload = data.payload
        await self._close_attempt(attempt, lesson, status=AttemptStatus.SUBMITTED, card=card)

        evaluation = await self.evaluations.for_attempt(attempt.id)
        #: То же, что и при закрытии карточки статусом: пишем по прочитанному.
        participant = await self._participant(lesson, student.id, lock=True)
        participant.cards_submitted += 1
        self._adapt_difficulty(lesson, participant, evaluation)
        await self._promote_student_card(attempt, lesson, evaluation, student)
        await self.session.flush()

        await lesson_hub.publish(
            lesson.id,
            "card_submitted",
            {
                "student_id": str(student.id),
                "attempt_id": str(attempt.id),
                "score": evaluation.score if evaluation else None,
                "duration_ms": attempt.duration_ms,
                "is_overtime": attempt.is_overtime,
            },
        )

        next_view = None
        lesson_finished = lesson.status is not LessonStatus.RUNNING
        if not lesson_finished:
            try:
                next_view = await self.issue_next_card(lesson.id, student)
            except BusinessRuleError as exc:
                logger.info("next_card_not_issued", extra={"reason": str(exc)})

        return {
            "attempt": attempt,
            "evaluation": evaluation,
            "next_attempt": next_view,
            "lesson_finished": lesson_finished,
        }

    async def skip(self, attempt_id: uuid.UUID, student: User) -> CardAttempt:
        attempt = await self._own_active_attempt(attempt_id, student)
        lesson = await self.get_lesson_light(attempt.lesson_id)
        await self._close_attempt(attempt, lesson, status=AttemptStatus.SKIPPED, evaluate=False)
        return attempt

    async def expire_overdue(self) -> int:
        """Фоновое закрытие карточек с истёкшим сроком отработки."""
        closed = 0
        for overdue in await self.attempts.expired():
            try:
                async with self.session.begin_nested():
                    attempt = await self.attempts.get_locked(overdue.id)
                    if attempt is None or attempt.status not in AttemptRepository.ACTIVE_STATUSES:
                        continue
                    lesson = await self.lessons.get_light(attempt.lesson_id)
                    if lesson is None:
                        continue
                    if (
                        attempt.response_deadline_at is not None
                        and attempt.first_response_at is None
                    ):
                        attempt.lifecycle_status = CardLifecycleStatus.NOT_NOTIFIED
                        attempt.is_response_late = True
                    attempt.submitted_payload = (
                        attempt.submitted_payload or attempt.draft_payload or {}
                    )
                    await self._close_attempt(attempt, lesson, status=AttemptStatus.EXPIRED)
                    closed += 1
            except SQLAlchemyError as exc:
                logger.warning(
                    "attempt_expire_failed",
                    extra={"attempt_id": str(overdue.id), "error": str(exc)},
                )
        if closed:
            ACTIVE_ATTEMPTS.set(await self.attempts.active_total())
        return closed

    async def mark_late_primary_response(self) -> int:
        marked = 0
        for attempt in await self.attempts.overdue_primary_response():
            attempt.is_response_late = True
            attempt.lifecycle_status = CardLifecycleStatus.NOT_NOTIFIED
            marked += 1
            await lesson_hub.publish(
                attempt.lesson_id,
                "primary_status_overdue",
                {
                    "student_id": str(attempt.student_id),
                    "attempt_id": str(attempt.id),
                    "norm_seconds": attempt.norm_seconds,
                },
            )
        if marked:
            await self.session.flush()
        return marked

    async def mark_unfinished_cards(self) -> int:
        threshold = utcnow() - timedelta(hours=settings.CARD_COMPLETION_HOURS)
        stale = await self.attempts.list_all(
            CardAttempt.issued_at < threshold,
            CardAttempt.lifecycle_status.in_(
                (CardLifecycleStatus.REGISTERED, CardLifecycleStatus.NOT_NOTIFIED)
            ),
            #: Служба приняла карточку (и, возможно, начала работы), но не закрыла их.
            CardAttempt.last_response_status.in_(
                (ResponseStatus.ACCEPTED, *PROGRESS_RESPONSE_STATUSES)
            ),
        )
        for attempt in stale:
            attempt.lifecycle_status = CardLifecycleStatus.NOT_FINISHED
        if stale:
            await self.session.flush()
        return len(stale)

    async def monitor(self, lesson_id: uuid.UUID, actor: User) -> dict[str, Any]:
        lesson = await self.get_lesson(lesson_id)
        self._ensure_owner(lesson, actor, allow_monitor=True)

        now = utcnow()
        participants = list(lesson.participants)
        if not participants:
            return {"lesson": lesson, "rows": [], "server_time": now}

        student_ids = [p.student_id for p in participants]
        participant_ids = [p.id for p in participants]

        names = await self.users.names_of(student_ids)
        attempts_by_participant = await self.attempts.active_stream_for(participant_ids)
        card_ids = {
            items[0].card_id for items in attempts_by_participant.values() if items
        }
        cards = await self.cards.by_ids(card_ids)
        avg_scores = await self.evaluations.avg_score_by_student(lesson.id)
        error_counts = await self._error_counts(lesson.id)

        rows: list[dict[str, Any]] = []
        for participant in participants:
            active = attempts_by_participant.get(participant.id, [])
            attempt = active[0] if active else None
            card = cards.get(attempt.card_id) if attempt else None
            seconds_left = None
            if attempt:
                deadlines = [
                    value
                    for value in (
                        attempt.response_deadline_at if attempt.first_response_at is None else None,
                        attempt.work_deadline_at,
                        attempt.deadline_at,
                    )
                    if value is not None
                ]
                if deadlines:
                    seconds_left = (min(deadlines) - now).total_seconds()
            rows.append(
                {
                    "student_id": participant.student_id,
                    "student_name": names.get(participant.student_id, "—"),
                    "workplace": (
                        participant.workplace.number if participant.workplace else None
                    ),
                    "participant_status": participant.status,
                    "active_cards": len(active),
                    "current_attempt_id": attempt.id if attempt else None,
                    "current_card_no": card.card_no if card else None,
                    "seconds_left": seconds_left,
                    "cards_issued": participant.cards_issued,
                    "cards_submitted": participant.cards_submitted,
                    "avg_score": avg_scores.get(participant.student_id),
                    "error_count": error_counts.get(participant.student_id, 0),
                    "last_seen_at": participant.last_seen_at,
                }
            )
        return {"lesson": lesson, "rows": rows, "server_time": now}

    def _ensure_owner(self, lesson: Lesson, actor: User, *, allow_monitor: bool = False) -> None:
        if lesson.teacher_id == actor.id:
            return
        if allow_monitor and actor.has_permission(Perm.SYSTEM_MONITOR):
            return
        #: Ограничение из ТЗ: преподаватель не вмешивается в работу других преподавателей.
        raise PermissionDeniedError("Занятие создано другим преподавателем")

    async def _participant(
        self, lesson: Lesson, student_id: uuid.UUID, *, lock: bool = False
    ) -> LessonParticipant:
        participant = (
            await self.participants.lock_for(lesson.id, student_id)
            if lock
            else await self.participants.get_for(lesson.id, student_id)
        )
        if participant is None:
            raise PermissionDeniedError("Вы не являетесь участником этого занятия")
        return participant

    async def _own_active_attempt(
        self, attempt_id: uuid.UUID, student: User, *, lock: bool = False
    ) -> CardAttempt:
        attempt = (
            await self.attempts.get_locked(attempt_id)
            if lock
            else await self.attempts.get(attempt_id)
        )
        if attempt is None:
            raise NotFoundError("Попытка не найдена")
        if attempt.student_id != student.id:
            raise PermissionDeniedError("Это карточка другого обучающегося")
        if attempt.status not in AttemptRepository.ACTIVE_STATUSES:
            raise BusinessRuleError("Карточка уже закрыта")
        return attempt

    async def _ensure_attempt_access(self, attempt: CardAttempt, actor: User) -> None:
        if attempt.student_id == actor.id:
            return
        if actor.has_permission(Perm.EVALUATIONS_READ) or actor.has_permission(Perm.LESSONS_MONITOR):
            return
        raise PermissionDeniedError("Доступ к данным другого обучающегося запрещён")

    async def _close_attempt(
        self,
        attempt: CardAttempt,
        lesson: Lesson,
        *,
        status: AttemptStatus,
        card: IncidentCard | None = None,
        evaluate: bool = True,
    ) -> CardAttempt:
        now = utcnow()
        attempt.status = status
        attempt.submitted_at = now
        started = attempt.started_at or attempt.issued_at
        attempt.duration_ms = int((now - started).total_seconds() * 1000)
        norm_seconds = float(attempt.norm_seconds)
        if lesson.mode is LessonMode.CARD_ACTION and attempt.work_deadline_at is not None:
            norm_seconds = max(
                norm_seconds, (attempt.work_deadline_at - attempt.issued_at).total_seconds()
            )
        attempt.time_delta_seconds = round(attempt.duration_ms / 1000 - norm_seconds, 3)
        attempt.is_overtime = attempt.time_delta_seconds > 0
        #: Нет первичного статуса к моменту закрытия — карточка «Не оповещено».
        if (
            lesson.mode is LessonMode.CARD_ACTION
            and attempt.first_response_at is None
            and status is AttemptStatus.EXPIRED
        ):
            attempt.lifecycle_status = CardLifecycleStatus.NOT_NOTIFIED
        await self.session.flush()

        if attempt.submitted_payload:
            await self.answers.replace_for_attempt(attempt.id, attempt.submitted_payload)

        if evaluate and status in (AttemptStatus.SUBMITTED, AttemptStatus.EXPIRED):
            card = card or await self.cards.get_or_fail(attempt.card_id, "Карточка не найдена")
            await self.evaluator.evaluate(attempt, lesson, card)
            attempt.status = AttemptStatus.EVALUATED if status is AttemptStatus.SUBMITTED else status
            await self.session.flush()
        return attempt

    async def _originate_call(
        self, lesson: Lesson, attempt: CardAttempt, card: IncidentCard, student: User
    ) -> CallRecord | None:
        """Запрос к модулю телефонии на имитацию входящего вызова."""
        #: Куда звонить: SIP-аккаунт из профиля, иначе номер рабочего места, за которым
        #: сидит обучающийся (телефония сопоставляет «05» с аккаунтом ws05).
        callee = (student.preferences or {}).get("sip_extension")
        if not callee and attempt.workplace_id:
            workplace = await self.session.get(Workplace, attempt.workplace_id)
            callee = workplace.number if workplace else None
        try:
            response = await self.telephony.originate_call(
                {
                    "lesson_id": str(lesson.id),
                    "attempt_id": str(attempt.id),
                    "student_id": str(student.id),
                    "card_no": card.card_no,
                    "caller_profile": card.caller_profile,
                    #: Заявитель рассказывает содержание именно этой карточки
                    "card": caller_knowledge(card.title, card.expected_payload, card.caller_profile),
                    "caller_number": (card.caller_profile or {}).get("phone"),
                    "callee_number": callee,
                    "record": True,
                }
            )
        except Exception as exc:  # noqa: BLE001 — занятие продолжается в текстовом режиме
            logger.warning("telephony_unavailable", extra={"error": str(exc)})
            await self.audit.system(
                f"Модуль телефонии недоступен, занятие продолжено в текстовом режиме: {exc}",
                level=LogLevel.WARNING,
                component="telephony",
                context={"lesson_id": str(lesson.id), "attempt_id": str(attempt.id)},
            )
            return None

        call = CallRecord(
            sip_call_id=response.get("sip_call_id"),
            direction=CallDirection.INBOUND,
            status=CallStatus.RINGING,
            lesson_id=lesson.id,
            attempt_id=attempt.id,
            student_id=student.id,
            caller_number=response.get("caller_number"),
            callee_number=response.get("callee_number"),
            latency_ms=response.get("latency_ms"),
            meta={"stub": bool(response.get("stub"))},
        )
        self.session.add(call)
        await self.session.flush()
        attempt.call_id = call.id
        await self.session.flush()
        return call

    async def _attempt_view(self, attempt: CardAttempt) -> dict[str, Any]:
        card = await self.cards.get_or_fail(attempt.card_id, "Карточка не найдена")
        lesson = await self.lessons.get_light(attempt.lesson_id)
        template_fields: list[Any] = []
        if card.template_id:
            from app.models.card import CardTemplate

            template = await self.session.get(CardTemplate, card.template_id)
            template_fields = template.fields_schema if template else []

        now = utcnow()
        seconds_left = None
        if attempt.deadline_at:
            seconds_left = (attempt.deadline_at - now).total_seconds()
        response_seconds_left = None
        if attempt.response_deadline_at and attempt.first_response_at is None:
            response_seconds_left = (attempt.response_deadline_at - now).total_seconds()

        visible_card = CardRead.model_validate(card)
        if lesson and lesson.mode is LessonMode.CARD_FILL:
            visible_card = visible_card.model_copy(
                update={
                    "payload": {},
                    #: АОН определяется автоматически при приёме вызова — его оператор видит сразу
                    "caller_profile": {"phone": (card.expected_payload or {}).get("aon_phone")
                                       or (card.caller_profile or {}).get("phone")},
                    "notification_list": [],
                    "title": f"Входящий вызов, карточка {card.card_no}",
                }
            )
        elif not card.payload:
            visible_card = visible_card.model_copy(
                update={"payload": dict(card.expected_payload or {})}
            )

        return {
            "attempt": attempt,
            "card": visible_card,
            "seconds_left": seconds_left,
            "response_seconds_left": response_seconds_left,
            #: Отдельный отсчёт на отработку карточки целиком — норматив 3 минуты.
            "work_seconds_left": _seconds_left(attempt.work_deadline_at, utcnow()),
            "template_fields": template_fields,
        }

    def _student_service(self, lesson: Lesson, notification_list: list[dict[str, Any]]) -> str | None:
        codes = service_codes(notification_list)
        requested = (lesson.success_criteria or {}).get("service_code")
        if requested and requested in codes:
            return str(requested)
        primary = primary_services(notification_list)
        return primary[0] if primary else (codes[0] if codes else None)

    def _category_uuids(self, lesson: Lesson) -> list[uuid.UUID]:
        result: list[uuid.UUID] = []
        for raw in lesson.category_ids or []:
            try:
                result.append(uuid.UUID(str(raw)))
            except ValueError:
                continue
        return result

    async def _error_counts(self, lesson_id: uuid.UUID) -> dict[uuid.UUID, int]:
        """Число замечаний по каждому обучающемуся занятия — одним запросом."""
        import sqlalchemy as sa

        from app.models.grading import ErrorRecord, Evaluation

        stmt = (
            sa.select(Evaluation.student_id, sa.func.count(ErrorRecord.id))
            .select_from(ErrorRecord)
            .join(Evaluation, Evaluation.id == ErrorRecord.evaluation_id)
            .where(Evaluation.lesson_id == lesson_id)
            .group_by(Evaluation.student_id)
        )
        return {row[0]: int(row[1]) for row in await self.session.execute(stmt)}


def _seconds(value: int) -> timedelta:
    return timedelta(seconds=value)


def _seconds_left(deadline: datetime | None, now: datetime) -> float | None:
    if deadline is None:
        return None
    return round((deadline - now).total_seconds(), 1)
