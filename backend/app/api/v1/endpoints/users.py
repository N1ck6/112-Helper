"""Пользователи, роли и права — кабинет администратора (п.1.3, 2.3)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import CurrentUser, PageDep, SessionDep, require
from app.core.pagination import Page, build_page
from app.core.permissions import Perm
from app.models.enums import UserStatus
from app.schemas.common import MessageResponse
from app.schemas.user import (
    DirectorySyncResult,
    PermissionRead,
    RoleCreate,
    RoleRead,
    RoleUpdate,
    UserBlockRequest,
    UserCreate,
    UserPasswordReset,
    UserRead,
    UserUpdate,
)
from app.services.users import RoleService, UserService

router = APIRouter(tags=["Пользователи"])


@router.post(
    "/users/sync-directory",
    response_model=DirectorySyncResult,
    summary="Синхронизация с локальной системой управления доступом",
    description=(
        "Забирает учётные записи из каталога организации (LDAP/AD-шлюз локального "
        "контура, п.2.9 ТЗ): создаёт новых пользователей, обновляет данные существующих "
        "и показывает тех, кто пропал из каталога. Пароли таких учётных записей "
        "проверяет каталог, тренажёр их не хранит. Параметр dry_run показывает, что "
        "изменится, ничего не меняя."
    ),
)
async def sync_directory(
    session: SessionDep,
    request: Request,
    dry_run: bool = Query(False, description="Только показать изменения"),
    actor=Depends(require(Perm.USERS_WRITE)),
) -> DirectorySyncResult:
    result = await UserService(session).sync_directory(actor, dry_run=dry_run, request=request)
    return DirectorySyncResult.model_validate(result)


# ------------------------------------------------------------------- справочники
@router.get("/roles", response_model=list[RoleRead], summary="Список ролей")
async def list_roles(session: SessionDep, _: CurrentUser) -> list[RoleRead]:
    roles = await RoleService(session).list_roles()
    return [RoleRead.model_validate(role) for role in roles]


@router.get("/permissions", response_model=list[PermissionRead], summary="Каталог прав")
async def list_permissions(
    session: SessionDep, _=Depends(require(Perm.ROLES_MANAGE))
) -> list[PermissionRead]:
    perms = await RoleService(session).list_permissions()
    return [PermissionRead.model_validate(p) for p in perms]


@router.post(
    "/roles",
    response_model=RoleRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создать роль",
)
async def create_role(
    data: RoleCreate, session: SessionDep, request: Request, actor=Depends(require(Perm.ROLES_MANAGE))
) -> RoleRead:
    role = await RoleService(session).create(data, actor, request)
    return RoleRead.model_validate(role)


@router.patch("/roles/{role_id}", response_model=RoleRead, summary="Изменить права роли")
async def update_role(
    role_id: uuid.UUID,
    data: RoleUpdate,
    session: SessionDep,
    request: Request,
    actor=Depends(require(Perm.ROLES_MANAGE)),
) -> RoleRead:
    role = await RoleService(session).update(role_id, data, actor, request)
    return RoleRead.model_validate(role)


@router.delete("/roles/{role_id}", response_model=MessageResponse, summary="Удалить роль")
async def delete_role(
    role_id: uuid.UUID, session: SessionDep, request: Request, actor=Depends(require(Perm.ROLES_MANAGE))
) -> MessageResponse:
    await RoleService(session).delete(role_id, actor, request)
    return MessageResponse(detail="Роль удалена")


# ---------------------------------------------------------------- пользователи
@router.get("/users", response_model=Page[UserRead], summary="Список пользователей")
async def list_users(
    session: SessionDep,
    page: PageDep,
    query: str | None = Query(None, description="Поиск по логину и ФИО"),
    role: str | None = Query(None, description="Фильтр по коду роли"),
    user_status: UserStatus | None = Query(None, alias="status"),
    _=Depends(require(Perm.USERS_READ)),
) -> Page[UserRead]:
    items, total = await UserService(session).list_users(
        page, query=query, role=role, status=user_status
    )
    return build_page([UserRead.model_validate(item) for item in items], total, page)


@router.post(
    "/users",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создать пользователя",
)
async def create_user(
    data: UserCreate, session: SessionDep, request: Request, actor=Depends(require(Perm.USERS_WRITE))
) -> UserRead:
    user = await UserService(session).create(data, actor, request)
    return UserRead.model_validate(user)


@router.get("/users/{user_id}", response_model=UserRead, summary="Карточка пользователя")
async def get_user(
    user_id: uuid.UUID, session: SessionDep, _=Depends(require(Perm.USERS_READ))
) -> UserRead:
    return UserRead.model_validate(await UserService(session).get(user_id))


@router.patch("/users/{user_id}", response_model=UserRead, summary="Изменить пользователя")
async def update_user(
    user_id: uuid.UUID,
    data: UserUpdate,
    session: SessionDep,
    request: Request,
    actor=Depends(require(Perm.USERS_WRITE)),
) -> UserRead:
    user = await UserService(session).update(user_id, data, actor, request)
    return UserRead.model_validate(user)


@router.post("/users/{user_id}/block", response_model=UserRead, summary="Заблокировать")
async def block_user(
    user_id: uuid.UUID,
    data: UserBlockRequest,
    session: SessionDep,
    request: Request,
    actor=Depends(require(Perm.USERS_BLOCK)),
) -> UserRead:
    user = await UserService(session).set_blocked(user_id, True, actor, data.reason, request)
    return UserRead.model_validate(await UserService(session).get(user.id))


@router.post("/users/{user_id}/unblock", response_model=UserRead, summary="Разблокировать")
async def unblock_user(
    user_id: uuid.UUID,
    session: SessionDep,
    request: Request,
    actor=Depends(require(Perm.USERS_BLOCK)),
) -> UserRead:
    user = await UserService(session).set_blocked(user_id, False, actor, None, request)
    return UserRead.model_validate(await UserService(session).get(user.id))


@router.post(
    "/users/{user_id}/password",
    response_model=MessageResponse,
    summary="Сбросить пароль пользователю",
)
async def reset_password(
    user_id: uuid.UUID,
    data: UserPasswordReset,
    session: SessionDep,
    request: Request,
    actor=Depends(require(Perm.USERS_WRITE)),
) -> MessageResponse:
    await UserService(session).reset_password(user_id, data.new_password, actor, request)
    return MessageResponse(detail="Пароль пользователя обновлён")


@router.delete(
    "/users/{user_id}",
    response_model=MessageResponse,
    summary="Деактивировать учётную запись (мягкое удаление)",
)
async def deactivate_user(
    user_id: uuid.UUID,
    session: SessionDep,
    request: Request,
    actor=Depends(require(Perm.USERS_WRITE)),
) -> MessageResponse:
    await UserService(session).deactivate(user_id, actor, request)
    return MessageResponse(detail="Учётная запись деактивирована, результаты обучения сохранены")
