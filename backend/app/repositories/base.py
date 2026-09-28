from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, Generic, TypeVar

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.core.exceptions import NotFoundError
from app.core.pagination import PageParams
from app.core.security import utcnow
from app.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    model: type[ModelT]
    #: Поле сортировки по умолчанию.
    default_order: Any = None

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------ чтение
    async def get(self, obj_id: uuid.UUID) -> ModelT | None:
        return await self.session.get(self.model, obj_id)

    async def get_or_fail(self, obj_id: uuid.UUID, message: str | None = None) -> ModelT:
        obj = await self.get(obj_id)
        if obj is None:
            raise NotFoundError(message or f"{self.model.__name__}: объект {obj_id} не найден")
        return obj

    async def find_one(self, *conditions: Any) -> ModelT | None:
        stmt = sa.select(self.model).where(*conditions).limit(1)
        return (await self.session.execute(stmt)).scalars().first()

    async def exists(self, *conditions: Any) -> bool:
        stmt = sa.select(sa.literal(1)).select_from(self.model).where(*conditions).limit(1)
        return (await self.session.execute(stmt)).first() is not None

    async def count(self, *conditions: Any) -> int:
        stmt = sa.select(sa.func.count()).select_from(self.model)
        if conditions:
            stmt = stmt.where(*conditions)
        return int((await self.session.execute(stmt)).scalar_one())

    @classmethod
    def _default_order(cls):
        return cls.default_order

    def select(self) -> Select:
        stmt = sa.select(self.model)
        order = self._default_order()
        if order is not None:
            stmt = stmt.order_by(order)
        return stmt

    async def paginate(
        self,
        params: PageParams,
        *conditions: Any,
        stmt: Select | None = None,
        order_by: Any = None,
    ) -> tuple[Sequence[ModelT], int]:
        """Возвращает страницу объектов и общее количество."""
        base = stmt if stmt is not None else sa.select(self.model)
        if conditions:
            base = base.where(*conditions)

        count_stmt = sa.select(sa.func.count()).select_from(base.order_by(None).subquery())
        total = int((await self.session.execute(count_stmt)).scalar_one())

        order = order_by if order_by is not None else self._default_order()
        if order is not None:
            base = base.order_by(order)
        base = base.offset(params.offset).limit(params.limit)
        items = (await self.session.execute(base)).scalars().unique().all()
        return items, total

    async def list_all(self, *conditions: Any, order_by: Any = None, limit: int | None = None) -> Sequence[ModelT]:
        stmt = sa.select(self.model)
        if conditions:
            stmt = stmt.where(*conditions)
        order = order_by if order_by is not None else self._default_order()
        if order is not None:
            stmt = stmt.order_by(order)
        if limit:
            stmt = stmt.limit(limit)
        return (await self.session.execute(stmt)).scalars().unique().all()

    # ------------------------------------------------------------------ запись
    def add(self, obj: ModelT) -> ModelT:
        self.session.add(obj)
        return obj

    async def create(self, **values: Any) -> ModelT:
        obj = self.model(**values)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def update(self, obj: ModelT, **values: Any) -> ModelT:
        for field, value in values.items():
            if value is not None or field in getattr(self.model, "__nullable_updates__", ()):
                setattr(obj, field, value)
        await self.session.flush()
        return obj

    async def soft_delete(self, obj: ModelT) -> ModelT:
        """Мягкое удаление, если модель его поддерживает; иначе — физическое."""
        if hasattr(obj, "is_active"):
            obj.is_active = False
            if hasattr(obj, "deleted_at"):
                obj.deleted_at = utcnow()
            await self.session.flush()
            return obj
        await self.session.delete(obj)
        await self.session.flush()
        return obj

    async def hard_delete(self, obj: ModelT) -> None:
        await self.session.delete(obj)
        await self.session.flush()
