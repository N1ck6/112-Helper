from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import CurrentUser, SessionDep, require
from app.core.permissions import Perm
from app.schemas.common import MessageResponse
from app.schemas.training import (
    WorkplaceAssignRequest,
    WorkplaceCreate,
    WorkplaceRead,
    WorkplaceUpdate,
)
from app.services.training import TrainingService
from app.services.workplaces import WorkplaceService

router = APIRouter(prefix="/workplaces", tags=["Рабочие места"])


@router.get("", response_model=list[WorkplaceRead], summary="Список рабочих мест")
async def list_workplaces(
    session: SessionDep,
    user: CurrentUser,
    only_active: bool = False,
) -> list[WorkplaceRead]:
    items = await WorkplaceService(session).list_all(only_active=only_active)
    return [WorkplaceRead.model_validate(item) for item in items]


@router.get(
    "/class-map",
    summary="Карта класса: место → кто за ним → что назначено",
    description=(
        "Исходные данные экрана раздачи заданий: преподаватель видит занятые и "
        "свободные места, кто за ними работает и сколько карточек уже отработано. "
        "С параметром lesson_id добавляются показатели по конкретному занятию."
    ),
)
async def class_map(
    session: SessionDep,
    teacher=Depends(require(Perm.LESSONS_MONITOR)),
    lesson_id: uuid.UUID | None = None,
) -> list[dict]:
    return await WorkplaceService(session).class_map(lesson_id)


@router.post(
    "",
    response_model=WorkplaceRead,
    status_code=status.HTTP_201_CREATED,
    summary="Добавить рабочее место",
)
async def create_workplace(
    data: WorkplaceCreate,
    session: SessionDep,
    request: Request,
    admin=Depends(require(Perm.USERS_WRITE)),
) -> WorkplaceRead:
    workplace = await WorkplaceService(session).create(data.model_dump(), admin, request)
    return WorkplaceRead.model_validate(workplace)


@router.patch(
    "/{workplace_id}", response_model=WorkplaceRead, summary="Изменить рабочее место"
)
async def update_workplace(
    workplace_id: uuid.UUID,
    data: WorkplaceUpdate,
    session: SessionDep,
    request: Request,
    admin=Depends(require(Perm.USERS_WRITE)),
) -> WorkplaceRead:
    workplace = await WorkplaceService(session).update(
        workplace_id, data.model_dump(exclude_unset=True), admin, request
    )
    return WorkplaceRead.model_validate(workplace)


@router.delete(
    "/{workplace_id}", response_model=MessageResponse, summary="Удалить рабочее место"
)
async def delete_workplace(
    workplace_id: uuid.UUID,
    session: SessionDep,
    request: Request,
    admin=Depends(require(Perm.USERS_WRITE)),
) -> MessageResponse:
    await WorkplaceService(session).delete(workplace_id, admin, request)
    return MessageResponse(detail="Рабочее место удалено")


@router.post(
    "/{number}/occupy",
    response_model=WorkplaceRead,
    summary="Занять рабочее место",
    description=(
        "Обучающийся называет номер места при входе, как на реальном АРМ-112. "
        "Одно место — один обучающийся: занятое место повторно занять нельзя, "
        "иначе преподаватель раздаст задание «пятому месту», а получат его двое."
    ),
)
async def occupy_workplace(
    number: str,
    session: SessionDep,
    student=Depends(require(Perm.LESSONS_PARTICIPATE)),
) -> WorkplaceRead:
    workplace = await WorkplaceService(session).occupy(number, student)
    return WorkplaceRead.model_validate(workplace)


@router.post(
    "/release", response_model=MessageResponse, summary="Освободить своё рабочее место"
)
async def release_workplace(session: SessionDep, user: CurrentUser) -> MessageResponse:
    await WorkplaceService(session).release(user.id)
    return MessageResponse(detail="Рабочее место освобождено")


@router.post(
    "/assign",
    summary="Раздать задания по номерам рабочих мест",
    description=(
        "Преподаватель отмечает, кому что достанется: «первому месту — задание один, "
        "пятому — третье». Назначенные карточки выдаются обучающемуся раньше "
        "случайных, в порядке назначения. Места, за которыми никто не работает, и "
        "несуществующие карточки попадают в `skipped` с причиной — раздача при этом "
        "не отменяется целиком."
    ),
)
async def assign_to_workplaces(
    data: WorkplaceAssignRequest,
    session: SessionDep,
    request: Request,
    teacher=Depends(require(Perm.LESSONS_MANAGE)),
) -> dict:
    return await TrainingService(session).assign_cards_to_workplaces(
        data.lesson_id, data.assignments, teacher, request
    )
