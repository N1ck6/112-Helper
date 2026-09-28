"""Репозитории пользователей, ролей, прав и групп."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from app.models.user import Permission, Role, StudyGroup, User, group_members
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User
    default_order = User.full_name

    async def by_username(self, username: str) -> User | None:
        stmt = (
            sa.select(User)
            .where(sa.func.lower(User.username) == username.lower())
            .options(selectinload(User.roles).selectinload(Role.permissions))
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def get_with_roles(self, user_id: uuid.UUID) -> User | None:
        stmt = (
            sa.select(User)
            .where(User.id == user_id)
            .options(selectinload(User.roles).selectinload(Role.permissions))
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def by_ids(self, user_ids: Sequence[uuid.UUID]) -> Sequence[User]:
        if not user_ids:
            return []
        stmt = sa.select(User).where(User.id.in_(user_ids))
        return (await self.session.execute(stmt)).scalars().all()

    async def students_of_group(self, group_id: uuid.UUID) -> Sequence[User]:
        stmt = (
            sa.select(User)
            .join(group_members, group_members.c.user_id == User.id)
            .where(group_members.c.group_id == group_id, User.is_active.is_(True))
            .order_by(User.full_name)
        )
        return (await self.session.execute(stmt)).scalars().all()


    async def names_of(self, user_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, str]:
        """ФИО пачкой: для списков, где иначе вышел бы запрос на каждую строку."""
        if not user_ids:
            return {}
        stmt = sa.select(User.id, User.full_name).where(User.id.in_(user_ids))
        return {row[0]: row[1] for row in await self.session.execute(stmt)}


class RoleRepository(BaseRepository[Role]):
    model = Role
    default_order = Role.code

    async def by_code(self, code: str) -> Role | None:
        return await self.find_one(Role.code == code)

    async def by_codes(self, codes: Sequence[str]) -> Sequence[Role]:
        if not codes:
            return []
        stmt = sa.select(Role).where(Role.code.in_(codes))
        return (await self.session.execute(stmt)).scalars().all()


class PermissionRepository(BaseRepository[Permission]):
    model = Permission
    default_order = Permission.code

    async def by_codes(self, codes: Sequence[str]) -> Sequence[Permission]:
        if not codes:
            return []
        stmt = sa.select(Permission).where(Permission.code.in_(codes))
        return (await self.session.execute(stmt)).scalars().all()


class GroupRepository(BaseRepository[StudyGroup]):
    model = StudyGroup
    default_order = StudyGroup.name

    async def by_code(self, code: str) -> StudyGroup | None:
        return await self.find_one(StudyGroup.code == code)

    async def get_with_students(self, group_id: uuid.UUID) -> StudyGroup | None:
        stmt = (
            sa.select(StudyGroup)
            .where(StudyGroup.id == group_id)
            .options(selectinload(StudyGroup.students))
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def add_members(self, group_id: uuid.UUID, student_ids: list[uuid.UUID]) -> int:
        added = 0
        for student_id in student_ids:
            exists = await self.session.execute(
                sa.select(sa.literal(1)).where(
                    group_members.c.group_id == group_id, group_members.c.user_id == student_id
                )
            )
            if exists.first() is None:
                await self.session.execute(
                    sa.insert(group_members).values(group_id=group_id, user_id=student_id)
                )
                added += 1
        return added

    async def remove_member(self, group_id: uuid.UUID, student_id: uuid.UUID) -> None:
        await self.session.execute(
            sa.delete(group_members).where(
                group_members.c.group_id == group_id, group_members.c.user_id == student_id
            )
        )
