"""Репозитории учебного процесса."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.orm import noload, selectinload

from app.models.enums import AttemptStatus, LessonStatus
from app.models.training import (
    Assignment,
    CardAnswer,
    CardAttempt,
    Lesson,
    LessonParticipant,
    StudentAction,
)
from app.repositories.base import BaseRepository


class AssignmentRepository(BaseRepository[Assignment]):
    model = Assignment
    default_order = Assignment.created_at.desc()

    async def for_student(self, student_id: uuid.UUID, group_ids: Sequence[uuid.UUID]) -> Sequence[Assignment]:
        conditions = [Assignment.is_active.is_(True)]
        target = [Assignment.student_id == student_id]
        if group_ids:
            target.append(Assignment.group_id.in_(group_ids))
        conditions.append(sa.or_(*target))
        return await self.list_all(*conditions)


class LessonRepository(BaseRepository[Lesson]):
    model = Lesson
    default_order = Lesson.created_at.desc()

    async def get_full(self, lesson_id: uuid.UUID) -> Lesson | None:
        stmt = (
            sa.select(Lesson)
            .where(Lesson.id == lesson_id)
            .options(selectinload(Lesson.participants))
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def get_light(self, lesson_id: uuid.UUID) -> Lesson | None:
        stmt = (
            sa.select(Lesson).where(Lesson.id == lesson_id).options(noload(Lesson.participants))
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def active_count(self) -> int:
        return await self.count(Lesson.status.in_([LessonStatus.RUNNING, LessonStatus.PAUSED]))

    async def for_student(self, student_id: uuid.UUID) -> Sequence[Lesson]:
        stmt = (
            sa.select(Lesson)
            .join(LessonParticipant, LessonParticipant.lesson_id == Lesson.id)
            .where(LessonParticipant.student_id == student_id)
            .order_by(Lesson.created_at.desc())
        )
        return (await self.session.execute(stmt)).scalars().unique().all()


class ParticipantRepository(BaseRepository[LessonParticipant]):
    model = LessonParticipant

    async def get_for(self, lesson_id: uuid.UUID, student_id: uuid.UUID) -> LessonParticipant | None:
        return await self.find_one(
            LessonParticipant.lesson_id == lesson_id,
            LessonParticipant.student_id == student_id,
        )

    async def lock_for(
        self, lesson_id: uuid.UUID, student_id: uuid.UUID
    ) -> LessonParticipant | None:
        stmt = (
            sa.select(LessonParticipant)
            .where(
                LessonParticipant.lesson_id == lesson_id,
                LessonParticipant.student_id == student_id,
            )
            .with_for_update()
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def by_resume_token(self, token: str) -> LessonParticipant | None:
        return await self.find_one(LessonParticipant.resume_token == token)

    async def for_lesson(self, lesson_id: uuid.UUID) -> Sequence[LessonParticipant]:
        return await self.list_all(LessonParticipant.lesson_id == lesson_id)


class AttemptRepository(BaseRepository[CardAttempt]):
    model = CardAttempt
    default_order = CardAttempt.issued_at.desc()

    ACTIVE_STATUSES = (AttemptStatus.ISSUED, AttemptStatus.IN_PROGRESS)

    async def active_for_participant(self, participant_id: uuid.UUID) -> CardAttempt | None:
        stmt = (
            sa.select(CardAttempt)
            .where(
                CardAttempt.participant_id == participant_id,
                CardAttempt.status.in_(self.ACTIVE_STATUSES),
            )
            .order_by(CardAttempt.issued_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def active_stream(self, participant_id: uuid.UUID) -> Sequence[CardAttempt]:
        stmt = (
            sa.select(CardAttempt)
            .where(
                CardAttempt.participant_id == participant_id,
                CardAttempt.status.in_(self.ACTIVE_STATUSES),
            )
            .order_by(CardAttempt.issued_at.asc())
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def active_stream_for(
        self, participant_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, list[CardAttempt]]:
        if not participant_ids:
            return {}
        stmt = (
            sa.select(CardAttempt)
            .where(
                CardAttempt.participant_id.in_(participant_ids),
                CardAttempt.status.in_(self.ACTIVE_STATUSES),
            )
            .order_by(CardAttempt.issued_at.asc())
        )
        grouped: dict[uuid.UUID, list[CardAttempt]] = {}
        for attempt in (await self.session.execute(stmt)).scalars().all():
            grouped.setdefault(attempt.participant_id, []).append(attempt)
        return grouped

    async def active_count(self, participant_id: uuid.UUID) -> int:
        stmt = sa.select(sa.func.count(CardAttempt.id)).where(
            CardAttempt.participant_id == participant_id,
            CardAttempt.status.in_(self.ACTIVE_STATUSES),
        )
        return int((await self.session.execute(stmt)).scalar() or 0)

    async def get_locked(self, attempt_id: uuid.UUID) -> CardAttempt | None:
        stmt = (
            sa.select(CardAttempt)
            .where(CardAttempt.id == attempt_id)
            .with_for_update(of=CardAttempt)
            .options(selectinload(CardAttempt.response_statuses))
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def next_sequence_no(self, participant_id: uuid.UUID) -> int:
        stmt = sa.select(sa.func.coalesce(sa.func.max(CardAttempt.sequence_no), 0)).where(
            CardAttempt.participant_id == participant_id
        )
        return int((await self.session.execute(stmt)).scalar_one()) + 1

    async def issued_card_ids(self, participant_id: uuid.UUID) -> list[uuid.UUID]:
        stmt = sa.select(CardAttempt.card_id).where(CardAttempt.participant_id == participant_id)
        return list((await self.session.execute(stmt)).scalars().all())

    async def for_lesson(self, lesson_id: uuid.UUID) -> Sequence[CardAttempt]:
        return await self.list_all(CardAttempt.lesson_id == lesson_id, order_by=CardAttempt.issued_at)

    async def active_total(self) -> int:
        return await self.count(CardAttempt.status.in_(self.ACTIVE_STATUSES))

    async def expired(self, limit: int = 100) -> Sequence[CardAttempt]:
        stmt = (
            sa.select(CardAttempt)
            .where(
                CardAttempt.status.in_(self.ACTIVE_STATUSES),
                CardAttempt.deadline_at.is_not(None),
                CardAttempt.deadline_at < sa.func.now(),
            )
            .limit(limit)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def overdue_primary_response(self, limit: int = 200) -> Sequence[CardAttempt]:
        stmt = (
            sa.select(CardAttempt)
            .where(
                CardAttempt.status.in_(self.ACTIVE_STATUSES),
                CardAttempt.response_deadline_at.is_not(None),
                CardAttempt.first_response_at.is_(None),
                CardAttempt.response_deadline_at < sa.func.now(),
                CardAttempt.is_response_late.is_(False),
            )
            .limit(limit)
        )
        return (await self.session.execute(stmt)).scalars().all()


class ActionRepository(BaseRepository[StudentAction]):
    model = StudentAction
    default_order = StudentAction.sequence_no

    async def for_attempt(self, attempt_id: uuid.UUID) -> Sequence[StudentAction]:
        return await self.list_all(StudentAction.attempt_id == attempt_id)

    async def next_sequence_no(self, attempt_id: uuid.UUID) -> int:
        stmt = sa.select(sa.func.coalesce(sa.func.max(StudentAction.sequence_no), 0)).where(
            StudentAction.attempt_id == attempt_id
        )
        return int((await self.session.execute(stmt)).scalar_one()) + 1


class AnswerRepository(BaseRepository[CardAnswer]):
    model = CardAnswer

    async def replace_for_attempt(self, attempt_id: uuid.UUID, payload: dict) -> None:
        """Перезаписывает итоговые значения полей карточки."""
        await self.session.execute(sa.delete(CardAnswer).where(CardAnswer.attempt_id == attempt_id))
        for field_code, value in payload.items():
            text = value if isinstance(value, str) else None
            self.session.add(
                CardAnswer(
                    attempt_id=attempt_id,
                    field_code=str(field_code)[:64],
                    value_text=text,
                    value_json={} if text is not None else {"value": value},
                    char_count=len(text or ""),
                )
            )
        await self.session.flush()
