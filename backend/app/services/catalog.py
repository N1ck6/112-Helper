"""Классификатор происшествий и нормативы времени."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ConflictError
from app.core.pagination import PageParams
from app.models.catalog import IncidentCategory, TimeNorm
from app.models.enums import AuditAction, LessonMode
from app.models.user import User
from app.repositories.content import CategoryRepository, TimeNormRepository
from app.schemas.catalog import CategoryCreate, CategoryUpdate, TimeNormUpsert
from app.services.audit import AuditService


class CatalogService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.categories = CategoryRepository(session)
        self.norms = TimeNormRepository(session)
        self.audit = AuditService(session)

    # -------------------------------------------------------------- категории
    async def list_categories(
        self, params: PageParams, *, profile: str | None = None
    ) -> tuple[Sequence[IncidentCategory], int]:
        conditions = [IncidentCategory.is_active.is_(True)]
        if profile:
            conditions.append(IncidentCategory.dds_profile == profile)
        return await self.categories.paginate(params, *conditions)

    async def create_category(
        self, data: CategoryCreate, actor: User, request: Request | None = None
    ) -> IncidentCategory:
        if await self.categories.by_code(data.code):
            raise ConflictError(f"Категория «{data.code}» уже существует")
        category = await self.categories.create(**data.model_dump())
        await self.audit.log(
            AuditAction.CREATE,
            actor=actor,
            object_type="incident_category",
            object_id=category.id,
            summary=f"Создана категория происшествий {category.code}",
            request=request,
        )
        return category

    async def update_category(
        self, category_id: uuid.UUID, data: CategoryUpdate, actor: User, request: Request | None = None
    ) -> IncidentCategory:
        category = await self.categories.get_or_fail(category_id, "Категория не найдена")
        await self.categories.update(category, **data.model_dump(exclude_unset=True))
        await self.audit.log(
            AuditAction.UPDATE,
            actor=actor,
            object_type="incident_category",
            object_id=category.id,
            summary=f"Изменена категория {category.code}",
            request=request,
        )
        return category

    async def delete_category(
        self, category_id: uuid.UUID, actor: User, request: Request | None = None
    ) -> None:
        category = await self.categories.get_or_fail(category_id, "Категория не найдена")
        await self.categories.soft_delete(category)
        await self.audit.log(
            AuditAction.DELETE,
            actor=actor,
            object_type="incident_category",
            object_id=category_id,
            summary=f"Категория {category.code} архивирована",
            request=request,
        )

    # -------------------------------------------------------------- нормативы
    async def list_norms(self) -> Sequence[TimeNorm]:
        return await self.norms.list_all()

    async def upsert_norm(
        self, data: TimeNormUpsert, actor: User, request: Request | None = None
    ) -> TimeNorm:
        existing = await self.norms.find_one(
            TimeNorm.category_id == data.category_id,
            TimeNorm.mode == data.mode,
            TimeNorm.action_type == data.action_type,
        )
        if existing:
            existing.seconds = data.seconds
            existing.comment = data.comment
            await self.session.flush()
            norm = existing
        else:
            norm = await self.norms.create(**data.model_dump())
        await self.audit.log(
            AuditAction.CONFIG_CHANGE,
            actor=actor,
            object_type="time_norm",
            object_id=norm.id,
            summary=f"Норматив времени: {norm.seconds} с",
            after=data.model_dump(mode="json"),
            request=request,
        )
        return norm

    async def resolve_time_limit(
        self,
        *,
        category_id: uuid.UUID | None = None,
        mode: LessonMode | None = None,
        explicit: int | None = None,
    ) -> int:
        """Единая точка определения норматива: явное значение → БД → настройка (30 с)."""
        if explicit:
            return explicit
        from_db = await self.norms.resolve(category_id, mode.value if mode else None)
        return from_db or settings.DEFAULT_CARD_TIME_LIMIT_SECONDS
