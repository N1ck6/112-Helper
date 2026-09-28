"""Занятия — сторона преподавателя (п.2.4)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import CurrentUser, PageDep, SessionDep, require
from app.core.pagination import Page, build_page
from app.core.permissions import Perm
from app.models.enums import LessonStatus
from app.schemas.common import MessageResponse
from app.schemas.training import (
    AssignmentCreate,
    AssignmentRead,
    LessonCreate,
    LessonFinishRequest,
    LessonMonitorResponse,
    LessonRead,
    LessonUpdate,
)
from app.services.training import AssignmentService, TrainingService

router = APIRouter(tags=["Занятия"])


# --------------------------------------------------------------- назначения
@router.get("/assignments", response_model=Page[AssignmentRead], summary="Назначенные задания")
async def list_assignments(session: SessionDep, page: PageDep, user: CurrentUser) -> Page[AssignmentRead]:
    items, total = await AssignmentService(session).list_for_actor(user, page)
    return build_page([AssignmentRead.model_validate(item) for item in items], total, page)


@router.post(
    "/assignments",
    response_model=AssignmentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Назначить задание группе или обучающемуся",
)
async def create_assignment(
    data: AssignmentCreate,
    session: SessionDep,
    request: Request,
    actor=Depends(require(Perm.LESSONS_MANAGE)),
) -> AssignmentRead:
    assignment = await AssignmentService(session).create(data, actor, request)
    return AssignmentRead.model_validate(assignment)


@router.delete(
    "/assignments/{assignment_id}", response_model=MessageResponse, summary="Отменить назначение"
)
async def delete_assignment(
    assignment_id: uuid.UUID,
    session: SessionDep,
    request: Request,
    actor=Depends(require(Perm.LESSONS_MANAGE)),
) -> MessageResponse:
    await AssignmentService(session).deactivate(assignment_id, actor, request)
    return MessageResponse(detail="Назначение отменено")


# ------------------------------------------------------------------- занятия
@router.get("/lessons", response_model=Page[LessonRead], summary="Список занятий")
async def list_lessons(
    session: SessionDep,
    page: PageDep,
    user: CurrentUser,
    lesson_status: LessonStatus | None = Query(None, alias="status"),
) -> Page[LessonRead]:
    items, total = await TrainingService(session).list_lessons(user, page, status=lesson_status)
    return build_page([LessonRead.model_validate(item) for item in items], total, page)


@router.post(
    "/lessons",
    response_model=LessonRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создать занятие",
    description=(
        "Создаёт занятие в статусе «запланировано». Участники берутся из списка "
        "`student_ids` либо из состава группы. Норматив времени определяется по "
        "нормативам категории, иначе — 30 секунд."
    ),
)
async def create_lesson(
    data: LessonCreate,
    session: SessionDep,
    request: Request,
    actor=Depends(require(Perm.LESSONS_MANAGE)),
) -> LessonRead:
    lesson = await TrainingService(session).create_lesson(data, actor, request)
    return LessonRead.model_validate(lesson)


@router.get("/lessons/{lesson_id}", response_model=LessonRead, summary="Занятие")
async def get_lesson(lesson_id: uuid.UUID, session: SessionDep, _: CurrentUser) -> LessonRead:
    return LessonRead.model_validate(await TrainingService(session).get_lesson(lesson_id))


@router.patch("/lessons/{lesson_id}", response_model=LessonRead, summary="Изменить параметры занятия")
async def update_lesson(
    lesson_id: uuid.UUID,
    data: LessonUpdate,
    session: SessionDep,
    request: Request,
    actor=Depends(require(Perm.LESSONS_MANAGE)),
) -> LessonRead:
    lesson = await TrainingService(session).update_lesson(lesson_id, data, actor, request)
    return LessonRead.model_validate(lesson)


@router.post("/lessons/{lesson_id}/start", response_model=LessonRead, summary="Начать занятие")
async def start_lesson(
    lesson_id: uuid.UUID,
    session: SessionDep,
    request: Request,
    actor=Depends(require(Perm.LESSONS_MANAGE)),
) -> LessonRead:
    lesson = await TrainingService(session).start_lesson(lesson_id, actor, request)
    return LessonRead.model_validate(lesson)


@router.post(
    "/lessons/{lesson_id}/finish",
    response_model=LessonRead,
    summary="Завершить занятие (в любой момент)",
)
async def finish_lesson(
    lesson_id: uuid.UUID,
    data: LessonFinishRequest,
    session: SessionDep,
    request: Request,
    actor=Depends(require(Perm.LESSONS_MANAGE)),
) -> LessonRead:
    lesson = await TrainingService(session).finish_lesson(lesson_id, data, actor, request)
    return LessonRead.model_validate(lesson)


@router.post(
    "/lessons/{lesson_id}/abort",
    response_model=LessonRead,
    summary="Прервать занятие",
)
async def abort_lesson(
    lesson_id: uuid.UUID,
    data: LessonFinishRequest,
    session: SessionDep,
    request: Request,
    actor=Depends(require(Perm.LESSONS_MANAGE)),
) -> LessonRead:
    lesson = await TrainingService(session).finish_lesson(lesson_id, data, actor, request, aborted=True)
    return LessonRead.model_validate(lesson)


@router.get(
    "/lessons/{lesson_id}/monitor",
    response_model=LessonMonitorResponse,
    summary="Мониторинг занятия в реальном времени",
    description=(
        "Срез состояния для кабинета преподавателя: кто онлайн, какая карточка открыта, "
        "сколько секунд осталось до норматива, средний балл и число замечаний. "
        "Для потоковых обновлений используйте WebSocket `/api/v1/ws/lessons/{lesson_id}`."
    ),
)
async def monitor_lesson(
    lesson_id: uuid.UUID,
    session: SessionDep,
    actor=Depends(require(Perm.LESSONS_MONITOR)),
) -> LessonMonitorResponse:
    data = await TrainingService(session).monitor(lesson_id, actor)
    return LessonMonitorResponse.model_validate(data)
