"""Аналитика, графики и прогнозирование (п.2.6 + критерии финальной экспертизы)."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query

from app.api.deps import CurrentUser, SessionDep, require
from app.core.exceptions import PermissionDeniedError
from app.core.permissions import Perm
from app.schemas.grading import AnalyticsSummary, HistoryRead, ReadinessForecast
from app.services.analytics import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["Аналитика"])


@router.get(
    "/summary",
    response_model=AnalyticsSummary,
    summary="Сводная аналитика",
    description=(
        "Агрегаты для графиков: средний балл, доля успешных, соблюдение нормативов, "
        "типичные ошибки и данные тепловой карты. Область задаётся одним из фильтров."
    ),
)
async def summary(
    session: SessionDep,
    lesson_id: uuid.UUID | None = None,
    student_id: uuid.UUID | None = None,
    group_id: uuid.UUID | None = None,
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    _=Depends(require(Perm.REPORTS_READ)),
) -> AnalyticsSummary:
    data = await AnalyticsService(session).summary(
        lesson_id=lesson_id,
        student_id=student_id,
        group_id=group_id,
        date_from=date_from,
        date_to=date_to,
    )
    return AnalyticsSummary.model_validate(data)


@router.get(
    "/my-summary",
    response_model=AnalyticsSummary,
    summary="Моя статистика (обучающийся)",
)
async def my_summary(session: SessionDep, user: CurrentUser) -> AnalyticsSummary:
    data = await AnalyticsService(session).summary(student_id=user.id)
    return AnalyticsSummary.model_validate(data)


@router.get(
    "/forecast/{student_id}",
    response_model=ReadinessForecast,
    summary="Прогноз готовности оператора",
    description=(
        "Линейная регрессия по динамике оценок: прогноз следующего результата и "
        "оценка числа попыток до целевого балла. Возвращает и текущее значение — "
        "чтобы прогноз можно было сверить с фактом."
    ),
)
async def forecast(
    student_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    target: float = Query(80.0, ge=1, le=100),
) -> ReadinessForecast:
    if student_id != user.id and not user.has_permission(Perm.REPORTS_READ):
        raise PermissionDeniedError("Прогноз по другому обучающемуся недоступен")
    data = await AnalyticsService(session).forecast(student_id, target)
    return ReadinessForecast.model_validate(data)


@router.get(
    "/progress/{student_id}",
    response_model=list[HistoryRead],
    summary="История обучения",
)
async def progress(
    student_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    limit: int = Query(50, ge=1, le=500),
) -> list[HistoryRead]:
    if student_id != user.id and not user.has_permission(Perm.REPORTS_READ):
        raise PermissionDeniedError("История другого обучающегося недоступна")
    items = await AnalyticsService(session).student_progress(student_id, limit)
    return [HistoryRead.model_validate(item) for item in items]
