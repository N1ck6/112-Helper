"""Репозитории оценок, ошибок, рекомендаций и истории обучения."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from app.models.grading import (
    ErrorRecord,
    Evaluation,
    MLResult,
    Recommendation,
    TrainingHistory,
)
from app.repositories.base import BaseRepository


class EvaluationRepository(BaseRepository[Evaluation]):
    model = Evaluation
    default_order = Evaluation.evaluated_at.desc()

    async def for_attempt(self, attempt_id: uuid.UUID) -> Evaluation | None:
        stmt = (
            sa.select(Evaluation)
            .where(Evaluation.attempt_id == attempt_id)
            .options(selectinload(Evaluation.errors))
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def get_full(self, evaluation_id: uuid.UUID) -> Evaluation | None:
        stmt = (
            sa.select(Evaluation)
            .where(Evaluation.id == evaluation_id)
            .options(selectinload(Evaluation.errors))
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def for_lesson(self, lesson_id: uuid.UUID) -> Sequence[Evaluation]:
        stmt = (
            sa.select(Evaluation)
            .where(Evaluation.lesson_id == lesson_id)
            .options(selectinload(Evaluation.errors))
        )
        return (await self.session.execute(stmt)).scalars().unique().all()

    async def avg_score(self, *conditions) -> float | None:
        stmt = sa.select(sa.func.avg(Evaluation.score))
        if conditions:
            stmt = stmt.where(*conditions)
        value = (await self.session.execute(stmt)).scalar_one_or_none()
        return float(value) if value is not None else None


    async def avg_score_by_student(self, lesson_id: uuid.UUID) -> dict[uuid.UUID, float]:
        """Средний балл по каждому участнику занятия — одним запросом."""
        stmt = (
            sa.select(Evaluation.student_id, sa.func.avg(Evaluation.score))
            .where(Evaluation.lesson_id == lesson_id)
            .group_by(Evaluation.student_id)
        )
        return {
            row[0]: float(row[1])
            for row in await self.session.execute(stmt)
            if row[1] is not None
        }


class ErrorRepository(BaseRepository[ErrorRecord]):
    model = ErrorRecord

    async def top_errors(self, *conditions, limit: int = 10) -> list[dict]:
        """Типичные ошибки — основа инсайтов ИИ для преподавателя (п.2.6)."""
        stmt = (
            sa.select(
                ErrorRecord.code,
                ErrorRecord.category,
                sa.func.count().label("cnt"),
            )
            .group_by(ErrorRecord.code, ErrorRecord.category)
            .order_by(sa.desc("cnt"))
            .limit(limit)
        )
        if conditions:
            stmt = stmt.where(*conditions)
        rows = (await self.session.execute(stmt)).all()
        total = sum(row.cnt for row in rows) or 1
        return [
            {
                "code": row.code,
                "category": row.category.value if hasattr(row.category, "value") else str(row.category),
                "count": int(row.cnt),
                "share": round(row.cnt / total, 4),
            }
            for row in rows
        ]

    async def heatmap(self, *conditions, limit: int = 100) -> list[dict]:
        """Матрица «поле карточки × категория ошибки» для тепловой карты."""
        stmt = (
            sa.select(
                sa.func.coalesce(ErrorRecord.field_code, sa.literal("—")).label("field_code"),
                ErrorRecord.category,
                sa.func.count().label("cnt"),
            )
            .group_by("field_code", ErrorRecord.category)
            .order_by(sa.desc("cnt"))
            .limit(limit)
        )
        if conditions:
            stmt = stmt.where(*conditions)
        rows = (await self.session.execute(stmt)).all()
        return [
            {
                "field_code": row.field_code,
                "category": row.category.value if hasattr(row.category, "value") else str(row.category),
                "count": int(row.cnt),
            }
            for row in rows
        ]


class MLResultRepository(BaseRepository[MLResult]):
    model = MLResult
    default_order = MLResult.created_at.desc()


class RecommendationRepository(BaseRepository[Recommendation]):
    model = Recommendation
    default_order = Recommendation.created_at.desc()


class HistoryRepository(BaseRepository[TrainingHistory]):
    model = TrainingHistory
    default_order = TrainingHistory.recorded_at.desc()

    async def series_for_student(self, student_id: uuid.UUID, limit: int = 50) -> Sequence[TrainingHistory]:
        stmt = (
            sa.select(TrainingHistory)
            .where(TrainingHistory.student_id == student_id, TrainingHistory.score.is_not(None))
            .order_by(TrainingHistory.recorded_at)
            .limit(limit)
        )
        return (await self.session.execute(stmt)).scalars().all()
