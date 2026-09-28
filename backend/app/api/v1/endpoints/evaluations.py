"""Оценки и рекомендации (п.2.6)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Body, Depends, Request

from app.api.deps import CurrentUser, PageDep, SessionDep, require
from app.core.exceptions import PermissionDeniedError
from app.core.pagination import Page, build_page
from app.core.permissions import Perm
from app.schemas.grading import (
    EvaluationOverrideRequest,
    EvaluationRead,
    RecommendationRead,
)
from app.services.analytics import AnalyticsService
from app.services.evaluation import EvaluationService

router = APIRouter(tags=["Оценки и рекомендации"])


@router.get(
    "/evaluations/by-attempt/{attempt_id}",
    response_model=EvaluationRead,
    summary="Оценка по карточке",
)
async def get_by_attempt(
    attempt_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> EvaluationRead:
    evaluation = await EvaluationService(session).for_attempt(attempt_id)
    if evaluation.student_id != user.id and not user.has_permission(Perm.EVALUATIONS_READ):
        raise PermissionDeniedError("Оценка другого обучающегося недоступна")
    return EvaluationRead.model_validate(evaluation)


@router.get(
    "/evaluations/by-lesson/{lesson_id}",
    response_model=list[EvaluationRead],
    summary="Оценки занятия",
)
async def get_by_lesson(
    lesson_id: uuid.UUID, session: SessionDep, _=Depends(require(Perm.EVALUATIONS_READ))
) -> list[EvaluationRead]:
    evaluations = await EvaluationService(session).list_for_lesson(lesson_id)
    return [EvaluationRead.model_validate(item) for item in evaluations]


@router.get(
    "/evaluations/my",
    response_model=Page[EvaluationRead],
    summary="Мои результаты (обучающийся)",
)
async def my_evaluations(
    session: SessionDep, page: PageDep, user: CurrentUser
) -> Page[EvaluationRead]:
    items, total = await EvaluationService(session).list_for_student(user.id, page)
    return build_page([EvaluationRead.model_validate(item) for item in items], total, page)


@router.get(
    "/evaluations/by-student/{student_id}",
    response_model=Page[EvaluationRead],
    summary="Результаты обучающегося",
)
async def student_evaluations(
    student_id: uuid.UUID,
    session: SessionDep,
    page: PageDep,
    _=Depends(require(Perm.EVALUATIONS_READ)),
) -> Page[EvaluationRead]:
    items, total = await EvaluationService(session).list_for_student(student_id, page)
    return build_page([EvaluationRead.model_validate(item) for item in items], total, page)


@router.post(
    "/evaluations/{evaluation_id}/override",
    response_model=EvaluationRead,
    summary="Экспертная корректировка оценки",
    description=(
        "Изменение оценки преподавателем. Исходное значение сохраняется, а факт "
        "изменения обязательно фиксируется в журнале аудита (требование ТЗ)."
    ),
)
async def override_evaluation(
    evaluation_id: uuid.UUID,
    data: EvaluationOverrideRequest,
    session: SessionDep,
    request: Request,
    actor=Depends(require(Perm.EVALUATIONS_OVERRIDE)),
) -> EvaluationRead:
    evaluation = await EvaluationService(session).override(evaluation_id, data, actor, request)
    return EvaluationRead.model_validate(evaluation)


@router.post(
    "/evaluations/{evaluation_id}/comment",
    response_model=EvaluationRead,
    summary="Комментарий преподавателя к результату",
)
async def comment_evaluation(
    evaluation_id: uuid.UUID,
    session: SessionDep,
    request: Request,
    comment: str = Body(..., embed=True, max_length=2000),
    actor=Depends(require(Perm.EVALUATIONS_READ)),
) -> EvaluationRead:
    evaluation = await EvaluationService(session).add_comment(evaluation_id, comment, actor, request)
    return EvaluationRead.model_validate(evaluation)


@router.post(
    "/recommendations/build",
    response_model=list[RecommendationRead],
    summary="Сформировать рекомендации ИИ",
    description="Собирает типичные ошибки и запрашивает у ML-сервиса рекомендации.",
)
async def build_recommendations(
    session: SessionDep,
    student_id: uuid.UUID | None = None,
    group_id: uuid.UUID | None = None,
    lesson_id: uuid.UUID | None = None,
    _=Depends(require(Perm.RECOMMENDATIONS_READ)),
) -> list[RecommendationRead]:
    items = await AnalyticsService(session).build_recommendations(
        student_id=student_id, group_id=group_id, lesson_id=lesson_id
    )
    return [RecommendationRead.model_validate(item) for item in items]


@router.get(
    "/recommendations/my",
    response_model=Page[RecommendationRead],
    summary="Мои рекомендации (обучающийся)",
)
async def my_recommendations(
    session: SessionDep, page: PageDep, user: CurrentUser
) -> Page[RecommendationRead]:
    from app.models.grading import Recommendation
    from app.repositories.grading import RecommendationRepository

    repo = RecommendationRepository(session)
    items, total = await repo.paginate(page, Recommendation.student_id == user.id)
    return build_page([RecommendationRead.model_validate(item) for item in items], total, page)
