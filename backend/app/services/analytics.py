from __future__ import annotations

import time
import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.integrations.ml_client import get_ml_client
from app.models.enums import (
    AttemptStatus,
    EvaluationSource,
    MLTaskKind,
    MLTaskStatus,
    RecommendationTarget,
)
from app.models.grading import ErrorRecord, Evaluation, MLResult, Recommendation, TrainingHistory
from app.models.training import CardAttempt
from app.models.user import group_members
from app.repositories.grading import (
    ErrorRepository,
    EvaluationRepository,
    HistoryRepository,
    RecommendationRepository,
)
from app.repositories.training import AttemptRepository

TARGET_SCORE = 80.0


class AnalyticsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.evaluations = EvaluationRepository(session)
        self.errors = ErrorRepository(session)
        self.history = HistoryRepository(session)
        self.attempts = AttemptRepository(session)
        self.recommendations = RecommendationRepository(session)
        self.ml = get_ml_client()

    # ------------------------------------------------------------------ сводка
    async def summary(
        self,
        *,
        lesson_id: uuid.UUID | None = None,
        student_id: uuid.UUID | None = None,
        group_id: uuid.UUID | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        attempt_conditions = self._attempt_conditions(lesson_id, student_id, group_id, date_from, date_to)
        eval_conditions = self._eval_conditions(lesson_id, student_id, group_id, date_from, date_to)

        totals = (
            await self.session.execute(
                sa.select(
                    sa.func.count().label("total"),
                    sa.func.sum(
                        sa.case((CardAttempt.status.in_(
                            [AttemptStatus.SUBMITTED, AttemptStatus.EVALUATED]), 1), else_=0)
                    ).label("submitted"),
                    sa.func.sum(sa.case((CardAttempt.is_overtime.is_(True), 1), else_=0)).label("overtime"),
                    sa.func.avg(CardAttempt.duration_ms).label("avg_duration"),
                ).where(*attempt_conditions)
            )
        ).one()

        scores = (
            await self.session.execute(
                sa.select(
                    sa.func.avg(Evaluation.score).label("avg_score"),
                    sa.func.count().label("cnt"),
                    sa.func.sum(sa.case((Evaluation.passed.is_(True), 1), else_=0)).label("passed"),
                ).where(*eval_conditions)
            )
        ).one()

        top_errors = await self.errors.top_errors(
            ErrorRecord.evaluation_id.in_(sa.select(Evaluation.id).where(*eval_conditions))
        )
        heatmap = await self.errors.heatmap(
            ErrorRecord.evaluation_id.in_(sa.select(Evaluation.id).where(*eval_conditions))
        )

        return {
            "scope": self._scope_label(lesson_id, student_id, group_id),
            "attempts_total": int(totals.total or 0),
            "attempts_submitted": int(totals.submitted or 0),
            "attempts_overtime": int(totals.overtime or 0),
            "avg_score": round(float(scores.avg_score), 2) if scores.avg_score is not None else None,
            "pass_rate": (
                round(float(scores.passed or 0) / scores.cnt, 4) if scores.cnt else None
            ),
            "avg_duration_seconds": (
                round(float(totals.avg_duration) / 1000, 2) if totals.avg_duration else None
            ),
            "top_errors": top_errors,
            "timing": await self._timing_points(attempt_conditions),
            "score_dynamics": await self._score_dynamics(eval_conditions),
            "error_heatmap": heatmap,
            "generated_in_ms": int((time.perf_counter() - started) * 1000),
        }

    async def _timing_points(self, conditions: list) -> list[dict[str, Any]]:
        """Фактическое время против норматива — по дням занятия."""
        stmt = (
            sa.select(
                sa.func.date(CardAttempt.issued_at).label("day"),
                sa.func.avg(CardAttempt.duration_ms).label("avg_duration"),
                sa.func.avg(CardAttempt.norm_seconds).label("avg_norm"),
                sa.func.avg(sa.case((CardAttempt.is_overtime.is_(True), 1.0), else_=0.0)).label("overtime"),
            )
            .where(*conditions, CardAttempt.duration_ms.is_not(None))
            .group_by("day")
            .order_by("day")
            .limit(60)
        )
        rows = (await self.session.execute(stmt)).all()
        return [
            {
                "label": str(row.day),
                "avg_duration_seconds": round(float(row.avg_duration or 0) / 1000, 2),
                "norm_seconds": round(float(row.avg_norm or 0), 2),
                "overtime_share": round(float(row.overtime or 0), 4),
            }
            for row in rows
        ]

    async def _score_dynamics(self, conditions: list) -> list[dict[str, Any]]:
        stmt = (
            sa.select(
                sa.func.date(Evaluation.evaluated_at).label("day"),
                sa.func.avg(Evaluation.score).label("avg_score"),
                sa.func.count().label("cnt"),
            )
            .where(*conditions)
            .group_by("day")
            .order_by("day")
            .limit(60)
        )
        rows = (await self.session.execute(stmt)).all()
        return [
            {
                "label": str(row.day),
                "avg_score": round(float(row.avg_score or 0), 2),
                "attempts": int(row.cnt),
            }
            for row in rows
        ]

    # ------------------------------------------------------------------ прогноз
    async def forecast(self, student_id: uuid.UUID, target: float = TARGET_SCORE) -> dict[str, Any]:
        series = await self.history.series_for_student(student_id)
        scores = [float(item.score) for item in series if item.score is not None]
        if not scores:
            raise NotFoundError("Недостаточно данных: у обучающегося нет оценённых попыток")

        n = len(scores)
        xs = list(range(1, n + 1))
        mean_x = sum(xs) / n
        mean_y = sum(scores) / n
        denominator = sum((x - mean_x) ** 2 for x in xs)
        slope = (
            sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, scores, strict=True)) / denominator
            if denominator
            else 0.0
        )
        intercept = mean_y - slope * mean_x
        forecast_next = intercept + slope * (n + 1)

        # Коэффициент детерминации как простая мера доверия к прогнозу.
        ss_tot = sum((y - mean_y) ** 2 for y in scores)
        ss_res = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, scores, strict=True))
        r_squared = 1 - ss_res / ss_tot if ss_tot else 0.0

        attempts_to_target: int | None = None
        current = scores[-1]
        if current >= target:
            attempts_to_target = 0
        elif slope > 0.1:
            attempts_to_target = max(1, int((target - intercept) / slope) - n)

        return {
            "student_id": student_id,
            "attempts_used": n,
            "trend_per_attempt": round(slope, 3),
            "current_score": round(current, 2),
            "forecast_next_score": round(max(0.0, min(100.0, forecast_next)), 2),
            "forecast_attempts_to_target": attempts_to_target,
            "target_score": target,
            "confidence": round(max(0.0, min(1.0, r_squared)), 3),
        }

    # ------------------------------------------------------------ рекомендации
    async def build_recommendations(
        self,
        *,
        student_id: uuid.UUID | None = None,
        group_id: uuid.UUID | None = None,
        lesson_id: uuid.UUID | None = None,
    ) -> list[Recommendation]:
        eval_conditions = self._eval_conditions(lesson_id, student_id, group_id, None, None)
        top_errors = await self.errors.top_errors(
            ErrorRecord.evaluation_id.in_(sa.select(Evaluation.id).where(*eval_conditions))
        )
        if not top_errors:
            return []

        payload = {
            "top_errors": top_errors,
            "scope": self._scope_label(lesson_id, student_id, group_id),
        }
        response = await self.ml.recommendations(payload)
        self.session.add(
            MLResult(
                kind=MLTaskKind.RECOMMENDATION,
                endpoint="recommendations",
                status=MLTaskStatus.STUBBED if response.get("stub") else MLTaskStatus.OK,
                lesson_id=lesson_id,
                request_payload=payload,
                response_payload=response,
                model=response.get("model"),
            )
        )

        created: list[Recommendation] = []
        target = (
            RecommendationTarget.STUDENT
            if student_id
            else RecommendationTarget.GROUP
            if group_id
            else RecommendationTarget.TEACHER
        )
        for item in response.get("recommendations", []):
            recommendation = Recommendation(
                target=target,
                student_id=student_id,
                group_id=group_id,
                lesson_id=lesson_id,
                title=str(item.get("title") or "Рекомендация")[:255],
                text=str(item.get("text") or ""),
                priority=int(item.get("priority") or 3),
                source=EvaluationSource.AI,
                based_on=item.get("based_on") or {},
            )
            self.session.add(recommendation)
            created.append(recommendation)
        await self.session.flush()
        return created

    # ------------------------------------------------------------------ helpers
    def _attempt_conditions(
        self,
        lesson_id: uuid.UUID | None,
        student_id: uuid.UUID | None,
        group_id: uuid.UUID | None,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> list:
        conditions: list = []
        if lesson_id:
            conditions.append(CardAttempt.lesson_id == lesson_id)
        if student_id:
            conditions.append(CardAttempt.student_id == student_id)
        if group_id:
            conditions.append(
                CardAttempt.student_id.in_(
                    sa.select(group_members.c.user_id).where(group_members.c.group_id == group_id)
                )
            )
        if date_from:
            conditions.append(CardAttempt.issued_at >= date_from)
        if date_to:
            conditions.append(CardAttempt.issued_at <= date_to)
        return conditions

    def _eval_conditions(
        self,
        lesson_id: uuid.UUID | None,
        student_id: uuid.UUID | None,
        group_id: uuid.UUID | None,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> list:
        conditions: list = []
        if lesson_id:
            conditions.append(Evaluation.lesson_id == lesson_id)
        if student_id:
            conditions.append(Evaluation.student_id == student_id)
        if group_id:
            conditions.append(
                Evaluation.student_id.in_(
                    sa.select(group_members.c.user_id).where(group_members.c.group_id == group_id)
                )
            )
        if date_from:
            conditions.append(Evaluation.evaluated_at >= date_from)
        if date_to:
            conditions.append(Evaluation.evaluated_at <= date_to)
        return conditions

    def _scope_label(
        self, lesson_id: uuid.UUID | None, student_id: uuid.UUID | None, group_id: uuid.UUID | None
    ) -> str:
        if lesson_id:
            return f"lesson:{lesson_id}"
        if student_id:
            return f"student:{student_id}"
        if group_id:
            return f"group:{group_id}"
        return "all"

    async def student_progress(self, student_id: uuid.UUID, limit: int = 50) -> list[TrainingHistory]:
        return list(await self.history.series_for_student(student_id, limit=limit))
