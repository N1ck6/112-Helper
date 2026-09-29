"""Учебные группы (п.2.4: назначение групп)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import PageDep, SessionDep, require
from app.core.pagination import Page, build_page
from app.core.permissions import Perm
from app.schemas.common import MessageResponse
from app.schemas.user import GroupCreate, GroupMembersRequest, GroupRead, GroupUpdate
from app.services.users import GroupService

router = APIRouter(prefix="/groups", tags=["Учебные группы"])


@router.get("", response_model=Page[GroupRead], summary="Список групп")
async def list_groups(
    session: SessionDep, page: PageDep, _=Depends(require(Perm.GROUPS_READ))
) -> Page[GroupRead]:
    items, total = await GroupService(session).list_groups(page)
    return build_page([GroupRead.model_validate(item) for item in items], total, page)


@router.post("", response_model=GroupRead, status_code=status.HTTP_201_CREATED, summary="Создать группу")
async def create_group(
    data: GroupCreate, session: SessionDep, request: Request, actor=Depends(require(Perm.GROUPS_MANAGE))
) -> GroupRead:
    return GroupRead.model_validate(await GroupService(session).create(data, actor, request))


@router.get("/{group_id}", response_model=GroupRead, summary="Группа и её состав")
async def get_group(
    group_id: uuid.UUID, session: SessionDep, _=Depends(require(Perm.GROUPS_READ))
) -> GroupRead:
    return GroupRead.model_validate(await GroupService(session).get(group_id))


@router.patch("/{group_id}", response_model=GroupRead, summary="Изменить группу")
async def update_group(
    group_id: uuid.UUID,
    data: GroupUpdate,
    session: SessionDep,
    request: Request,
    actor=Depends(require(Perm.GROUPS_MANAGE)),
) -> GroupRead:
    return GroupRead.model_validate(await GroupService(session).update(group_id, data, actor, request))


@router.post(
    "/{group_id}/students",
    response_model=GroupRead,
    summary="Добавить обучающихся в группу",
)
async def add_students(
    group_id: uuid.UUID,
    data: GroupMembersRequest,
    session: SessionDep,
    request: Request,
    actor=Depends(require(Perm.GROUPS_ASSIGN, Perm.GROUPS_MANAGE, any_of=True)),
) -> GroupRead:
    group = await GroupService(session).add_students(group_id, data.student_ids, actor, request)
    return GroupRead.model_validate(group)


@router.delete(
    "/{group_id}/students/{student_id}",
    response_model=GroupRead,
    summary="Исключить обучающегося из группы",
)
async def remove_student(
    group_id: uuid.UUID,
    student_id: uuid.UUID,
    session: SessionDep,
    request: Request,
    actor=Depends(require(Perm.GROUPS_ASSIGN, Perm.GROUPS_MANAGE, any_of=True)),
) -> GroupRead:
    group = await GroupService(session).remove_student(group_id, student_id, actor, request)
    return GroupRead.model_validate(group)


@router.delete("/{group_id}", response_model=MessageResponse, summary="Архивировать группу")
async def delete_group(
    group_id: uuid.UUID,
    session: SessionDep,
    request: Request,
    actor=Depends(require(Perm.GROUPS_MANAGE)),
) -> MessageResponse:
    service = GroupService(session)
    group = await service.get(group_id)
    await service.groups.soft_delete(group)
    return MessageResponse(detail="Группа архивирована")
