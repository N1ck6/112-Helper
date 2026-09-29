"""Пользователи, роли и учебные группы (п.2.3 ТЗ)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError
from app.core.pagination import PageParams
from app.core.permissions import RoleCode
from app.core.security import (
    hash_password,
    new_opaque_token,
    utcnow,
    validate_password_strength,
)
from app.integrations.directory import get_directory_client
from app.models.enums import AuditAction, UserStatus
from app.models.user import Permission, Role, StudyGroup, User, user_roles
from app.repositories.users import (
    GroupRepository,
    PermissionRepository,
    RoleRepository,
    UserRepository,
)
from app.schemas.user import (
    GroupCreate,
    GroupUpdate,
    RoleCreate,
    RoleUpdate,
    UserCreate,
    UserUpdate,
)
from app.services.audit import AuditService


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.roles = RoleRepository(session)
        self.permissions = PermissionRepository(session)
        self.audit = AuditService(session)

    async def list_users(
        self,
        params: PageParams,
        *,
        query: str | None = None,
        role: str | None = None,
        status: UserStatus | None = None,
    ) -> tuple[Sequence[User], int]:
        stmt = sa.select(User)
        conditions = []
        if query:
            pattern = f"%{query.lower()}%"
            conditions.append(
                sa.or_(
                    sa.func.lower(User.username).like(pattern),
                    sa.func.lower(User.full_name).like(pattern),
                )
            )
        if status:
            conditions.append(User.status == status)
        if role:
            stmt = stmt.join(user_roles, user_roles.c.user_id == User.id).join(
                Role, Role.id == user_roles.c.role_id
            )
            conditions.append(Role.code == role)
        return await self.users.paginate(params, *conditions, stmt=stmt, order_by=User.full_name)

    async def get(self, user_id: uuid.UUID) -> User:
        user = await self.users.get_with_roles(user_id)
        if user is None:
            raise NotFoundError("Пользователь не найден")
        return user

    async def create(self, data: UserCreate, actor: User, request: Request | None = None) -> User:
        if await self.users.by_username(data.username):
            raise ConflictError(f"Логин «{data.username}» уже занят")
        validate_password_strength(data.password)

        user = User(
            username=data.username,
            full_name=data.full_name,
            email=data.email,
            organization=data.organization,
            position=data.position,
            password_hash=hash_password(data.password),
            status=UserStatus.ACTIVE,
            password_changed_at=utcnow(),
        )
        codes = data.role_codes or [RoleCode.STUDENT.value]
        user.roles = list(await self._resolve_roles(codes))
        self.session.add(user)
        await self.session.flush()

        await self.audit.log(
            AuditAction.CREATE,
            actor=actor,
            object_type="user",
            object_id=user.id,
            summary=f"Создан пользователь {user.username}",
            after={"username": user.username, "roles": codes},
            request=request,
        )
        return await self.get(user.id)

    async def sync_directory(
        self, actor: User, *, dry_run: bool = False, request: Request | None = None
    ) -> dict[str, Any]:
        client = get_directory_client()
        if client is None:
            raise BusinessRuleError(
                "Каталог организации не подключён (DIRECTORY_URL): учётные записи "
                "создаёт администратор в разделе «Пользователи»",
                code="directory_not_configured",
            )
        entries = await client.fetch_users()

        created: list[str] = []
        updated: list[str] = []
        missing: list[str] = []
        conflicts: list[str] = []
        now = utcnow()

        for entry in entries:
            username = str(entry.get("username") or "").strip()
            if not username:
                continue
            user = await self.users.by_username(username)

            if user is None:
                if dry_run:
                    created.append(username)
                    continue
                user = User(
                    username=username,
                    full_name=str(entry.get("full_name") or username),
                    email=entry.get("email"),
                    organization=entry.get("organization"),
                    position=entry.get("position"),
                    #: Пароль в тренажёре не задаётся: вход идёт через каталог.
                    password_hash=hash_password(new_opaque_token(32)),
                    status=UserStatus.ACTIVE,
                    external_id=entry.get("external_id"),
                    auth_source="directory",
                    directory_synced_at=now,
                )
                user.roles = list(
                    await self._resolve_roles([str(entry.get("role") or RoleCode.STUDENT.value)])
                )
                self.session.add(user)
                created.append(username)
            elif user.auth_source != "directory":
                conflicts.append(username)
            else:
                differences = {
                    field: entry.get(field)
                    for field in ("full_name", "email", "organization", "position", "external_id")
                    if entry.get(field) and getattr(user, field) != entry.get(field)
                }
                if differences:
                    updated.append(username)
                if not dry_run:
                    for field, value in differences.items():
                        setattr(user, field, value)
                    user.directory_synced_at = now

        known = {str(entry.get("username") or "").strip() for entry in entries}
        for user in await self.users.list_all(User.auth_source == "directory"):
            if user.username not in known:
                missing.append(user.username)

        if not dry_run:
            await self.session.flush()
            await self.audit.log(
                AuditAction.PERMISSION_CHANGE,
                actor=actor,
                object_type="user",
                summary=(
                    f"Синхронизация с каталогом доступа ({client.name}): "
                    f"создано {len(created)}, обновлено {len(updated)}"
                ),
                after={
                    "created": created,
                    "updated": updated,
                    "missing": missing,
                    "conflicts": conflicts,
                },
                request=request,
            )

        return {
            "source": client.name,
            "dry_run": dry_run,
            "total": len(entries),
            "created": created,
            "updated": updated,
            #: Есть в тренажёре, но исчезли из каталога — кандидаты на блокировку.
            "missing_in_directory": missing,
            #: Логин занят локальной учётной записью — нужно решение администратора.
            "conflicts": conflicts,
        }

    async def update(
        self, user_id: uuid.UUID, data: UserUpdate, actor: User, request: Request | None = None
    ) -> User:
        user = await self.get(user_id)
        before = {"full_name": user.full_name, "roles": user.role_codes}

        for field in ("full_name", "email", "organization", "position"):
            value = getattr(data, field)
            if value is not None:
                setattr(user, field, value)
        if data.role_codes is not None:
            user.roles = list(await self._resolve_roles(data.role_codes))
            await self.audit.log(
                AuditAction.PERMISSION_CHANGE,
                actor=actor,
                object_type="user",
                object_id=user.id,
                summary="Изменён набор ролей",
                before={"roles": before["roles"]},
                after={"roles": data.role_codes},
                request=request,
            )
        await self.session.flush()

        await self.audit.log(
            AuditAction.UPDATE,
            actor=actor,
            object_type="user",
            object_id=user.id,
            summary=f"Изменён пользователь {user.username}",
            before=before,
            after={"full_name": user.full_name, "roles": user.role_codes},
            request=request,
        )
        return await self.get(user.id)

    async def set_blocked(
        self,
        user_id: uuid.UUID,
        blocked: bool,
        actor: User,
        reason: str | None = None,
        request: Request | None = None,
    ) -> User:
        user = await self.get(user_id)
        if user.id == actor.id:
            raise BusinessRuleError("Нельзя заблокировать собственную учётную запись")
        user.status = UserStatus.BLOCKED if blocked else UserStatus.ACTIVE
        if not blocked:
            user.failed_login_count = 0
            user.locked_until = None
        await self.session.flush()

        await self.audit.log(
            AuditAction.BLOCK if blocked else AuditAction.UNBLOCK,
            actor=actor,
            object_type="user",
            object_id=user.id,
            summary=reason or ("Блокировка учётной записи" if blocked else "Разблокировка учётной записи"),
            after={"status": user.status.value},
            request=request,
        )
        return user

    async def reset_password(
        self, user_id: uuid.UUID, new_password: str, actor: User, request: Request | None = None
    ) -> None:
        user = await self.get(user_id)
        if user.auth_source == "directory":
            raise BusinessRuleError(
                "Пароль этой учётной записи задаётся в системе управления доступом организации",
                code="directory_managed_account",
            )
        validate_password_strength(new_password)
        user.password_hash = hash_password(new_password)
        user.password_changed_at = utcnow()
        await self.session.flush()
        await self.audit.log(
            AuditAction.UPDATE,
            actor=actor,
            object_type="user",
            object_id=user.id,
            summary="Сброс пароля администратором",
            request=request,
            is_security=True,
        )

    async def deactivate(self, user_id: uuid.UUID, actor: User, request: Request | None = None) -> None:
        """Мягкое удаление: результаты обучения сохраняются (ТЗ запрещает их терять)."""
        user = await self.get(user_id)
        if user.id == actor.id:
            raise BusinessRuleError("Нельзя удалить собственную учётную запись")
        await self.users.soft_delete(user)
        user.status = UserStatus.BLOCKED
        await self.session.flush()
        await self.audit.log(
            AuditAction.DELETE,
            actor=actor,
            object_type="user",
            object_id=user.id,
            summary=f"Учётная запись {user.username} деактивирована",
            request=request,
        )

    async def _resolve_roles(self, codes: Sequence[str]) -> Sequence[Role]:
        roles = await self.roles.by_codes(list(codes))
        missing = set(codes) - {role.code for role in roles}
        if missing:
            raise NotFoundError(f"Неизвестные роли: {', '.join(sorted(missing))}")
        return roles


class RoleService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.roles = RoleRepository(session)
        self.permissions = PermissionRepository(session)
        self.audit = AuditService(session)

    async def list_roles(self) -> Sequence[Role]:
        return await self.roles.list_all()

    async def list_permissions(self) -> Sequence[Permission]:
        return await self.permissions.list_all()

    async def create(self, data: RoleCreate, actor: User, request: Request | None = None) -> Role:
        if await self.roles.by_code(data.code):
            raise ConflictError(f"Роль «{data.code}» уже существует")
        role = Role(code=data.code, name=data.name, description=data.description, is_system=False)
        role.permissions = list(await self._resolve_permissions(data.permission_codes))
        self.session.add(role)
        await self.session.flush()
        await self.audit.log(
            AuditAction.CREATE,
            actor=actor,
            object_type="role",
            object_id=role.id,
            summary=f"Создана роль {role.code}",
            after={"permissions": data.permission_codes},
            request=request,
        )
        return role

    async def update(
        self, role_id: uuid.UUID, data: RoleUpdate, actor: User, request: Request | None = None
    ) -> Role:
        role = await self.roles.get_or_fail(role_id, "Роль не найдена")
        before = {"name": role.name, "permissions": [p.code for p in role.permissions]}
        if data.name is not None:
            role.name = data.name
        if data.description is not None:
            role.description = data.description
        if data.permission_codes is not None:
            role.permissions = list(await self._resolve_permissions(data.permission_codes))
        await self.session.flush()
        await self.audit.log(
            AuditAction.PERMISSION_CHANGE,
            actor=actor,
            object_type="role",
            object_id=role.id,
            summary=f"Изменена роль {role.code}",
            before=before,
            after={"name": role.name, "permissions": [p.code for p in role.permissions]},
            request=request,
        )
        return role

    async def delete(self, role_id: uuid.UUID, actor: User, request: Request | None = None) -> None:
        role = await self.roles.get_or_fail(role_id, "Роль не найдена")
        if role.is_system:
            raise BusinessRuleError("Системную роль удалить нельзя")
        await self.roles.hard_delete(role)
        await self.audit.log(
            AuditAction.DELETE,
            actor=actor,
            object_type="role",
            object_id=role_id,
            summary=f"Удалена роль {role.code}",
            request=request,
        )

    async def _resolve_permissions(self, codes: Sequence[str]) -> Sequence[Permission]:
        perms = await self.permissions.by_codes(list(codes))
        missing = set(codes) - {p.code for p in perms}
        if missing:
            raise NotFoundError(f"Неизвестные права: {', '.join(sorted(missing))}")
        return perms


class GroupService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.groups = GroupRepository(session)
        self.users = UserRepository(session)
        self.audit = AuditService(session)

    async def list_groups(self, params: PageParams) -> tuple[Sequence[StudyGroup], int]:
        return await self.groups.paginate(params, StudyGroup.is_active.is_(True))

    async def get(self, group_id: uuid.UUID) -> StudyGroup:
        group = await self.groups.get_with_students(group_id)
        if group is None:
            raise NotFoundError("Учебная группа не найдена")
        return group

    async def create(self, data: GroupCreate, actor: User, request: Request | None = None) -> StudyGroup:
        if await self.groups.by_code(data.code):
            raise ConflictError(f"Группа «{data.code}» уже существует")
        group = await self.groups.create(**data.model_dump())
        await self.audit.log(
            AuditAction.CREATE,
            actor=actor,
            object_type="group",
            object_id=group.id,
            summary=f"Создана группа {group.code}",
            request=request,
        )
        return await self.get(group.id)

    async def update(
        self, group_id: uuid.UUID, data: GroupUpdate, actor: User, request: Request | None = None
    ) -> StudyGroup:
        group = await self.get(group_id)
        await self.groups.update(group, **data.model_dump(exclude_unset=True))
        await self.audit.log(
            AuditAction.UPDATE,
            actor=actor,
            object_type="group",
            object_id=group.id,
            summary=f"Изменена группа {group.code}",
            request=request,
        )
        return await self.get(group_id)

    async def add_students(
        self, group_id: uuid.UUID, student_ids: list[uuid.UUID], actor: User, request: Request | None = None
    ) -> StudyGroup:
        await self.get(group_id)
        students = await self.users.by_ids(student_ids)
        if len(students) != len(set(student_ids)):
            raise NotFoundError("Часть обучающихся не найдена")
        for student in students:
            if not student.has_role(RoleCode.STUDENT.value):
                raise BusinessRuleError(
                    f"Пользователь {student.username} не является обучающимся"
                )
        added = await self.groups.add_members(group_id, list(student_ids))
        await self.audit.log(
            AuditAction.UPDATE,
            actor=actor,
            object_type="group",
            object_id=group_id,
            summary=f"В группу добавлено обучающихся: {added}",
            after={"student_ids": [str(i) for i in student_ids]},
            request=request,
        )
        return await self.get(group_id)

    async def remove_student(
        self, group_id: uuid.UUID, student_id: uuid.UUID, actor: User, request: Request | None = None
    ) -> StudyGroup:
        await self.get(group_id)
        await self.groups.remove_member(group_id, student_id)
        await self.audit.log(
            AuditAction.UPDATE,
            actor=actor,
            object_type="group",
            object_id=group_id,
            summary="Обучающийся исключён из группы",
            after={"student_id": str(student_id)},
            request=request,
        )
        return await self.get(group_id)
