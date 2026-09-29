"""Репозитории учебного контента: классификатор, сценарии, материалы, карточки."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from app.models.card import CardTemplate, IncidentCard
from app.models.catalog import IncidentCategory, IncidentType, TimeNorm
from app.models.enums import (
    CardOrigin,
    CardSource,
    CardStatus,
    DifficultyLevel,
)
from app.models.scenario import GenerationRequest, Scenario, ScenarioReference, TrainingMaterial
from app.repositories.base import BaseRepository


class CategoryRepository(BaseRepository[IncidentCategory]):
    model = IncidentCategory
    default_order = IncidentCategory.name

    async def by_code(self, code: str) -> IncidentCategory | None:
        return await self.find_one(IncidentCategory.code == code)

    async def by_ids(self, ids: Sequence[uuid.UUID]) -> Sequence[IncidentCategory]:
        if not ids:
            return []
        stmt = sa.select(IncidentCategory).where(IncidentCategory.id.in_(ids))
        return (await self.session.execute(stmt)).scalars().all()

    async def ancestry(self, category_id: uuid.UUID | None) -> list[IncidentCategory]:
        chain: list[IncidentCategory] = []
        seen: set[uuid.UUID] = set()
        current_id = category_id
        for _ in range(8):
            if current_id is None or current_id in seen:
                break
            seen.add(current_id)
            category = await self.get(current_id)
            if category is None:
                break
            chain.append(category)
            current_id = category.parent_id
        return chain


class IncidentTypeRepository(BaseRepository[IncidentType]):
    """Строки Единого классификатора происшествий."""

    model = IncidentType
    default_order = IncidentType.code

    async def by_code(self, code: str) -> IncidentType | None:
        return await self.find_one(IncidentType.code == code)


class TimeNormRepository(BaseRepository[TimeNorm]):
    model = TimeNorm
    default_order = TimeNorm.seconds

    async def resolve(self, category_id: uuid.UUID | None, mode: str | None) -> int | None:
        """Наиболее конкретный норматив: категория+режим → категория → режим → общий."""
        stmt = sa.select(TimeNorm).where(
            sa.or_(TimeNorm.category_id == category_id, TimeNorm.category_id.is_(None)),
            sa.or_(TimeNorm.mode == mode, TimeNorm.mode.is_(None)),
            TimeNorm.action_type.is_(None),
        )
        norms = (await self.session.execute(stmt)).scalars().all()
        if not norms:
            return None
        norms.sort(
            key=lambda n: ((n.category_id is not None) * 2 + (n.mode is not None)),
            reverse=True,
        )
        return norms[0].seconds


class ScenarioRepository(BaseRepository[Scenario]):
    model = Scenario
    default_order = Scenario.created_at.desc()

    async def get_with_references(self, scenario_id: uuid.UUID) -> Scenario | None:
        stmt = (
            sa.select(Scenario)
            .where(Scenario.id == scenario_id)
            .options(selectinload(Scenario.references))
        )
        return (await self.session.execute(stmt)).scalars().first()


class ReferenceRepository(BaseRepository[ScenarioReference]):
    model = ScenarioReference

    async def for_card(self, card_id: uuid.UUID) -> ScenarioReference | None:
        return await self.find_one(ScenarioReference.card_id == card_id)


class MaterialRepository(BaseRepository[TrainingMaterial]):
    model = TrainingMaterial
    default_order = TrainingMaterial.created_at.desc()


class GenerationRequestRepository(BaseRepository[GenerationRequest]):
    model = GenerationRequest
    default_order = GenerationRequest.created_at.desc()


class CardTemplateRepository(BaseRepository[CardTemplate]):
    model = CardTemplate
    default_order = CardTemplate.code

    async def default_template(self) -> CardTemplate | None:
        return await self.find_one(CardTemplate.is_default.is_(True), CardTemplate.is_active.is_(True))

    async def by_code(self, code: str) -> CardTemplate | None:
        return await self.find_one(CardTemplate.code == code)


class CardRepository(BaseRepository[IncidentCard]):
    model = IncidentCard
    default_order = IncidentCard.created_at.desc()

    async def next_card_no(self) -> str:
        """Учебный номер карточки вида У-000123."""
        total = await self.count()
        return f"У-{total + 1:06d}"

    def _pool_conditions(
        self,
        category_ids: Sequence[uuid.UUID] | None,
        source: CardSource,
        difficulty: DifficultyLevel | None,
    ) -> list:
        conditions = [IncidentCard.is_active.is_(True), IncidentCard.status == CardStatus.READY]
        if category_ids:
            conditions.append(IncidentCard.category_id.in_(category_ids))
        if difficulty:
            conditions.append(IncidentCard.difficulty == difficulty)
        if source == CardSource.GENERATED:
            conditions.append(IncidentCard.origin.in_([CardOrigin.GENERATED, CardOrigin.MANUAL]))
        elif source == CardSource.STUDENT:
            conditions.append(IncidentCard.origin == CardOrigin.STUDENT)
        return conditions

    async def by_ids(self, card_ids) -> dict:
        """Карточки пачкой по идентификаторам."""
        ids = list(card_ids)
        if not ids:
            return {}
        stmt = sa.select(IncidentCard).where(IncidentCard.id.in_(ids))
        return {card.id: card for card in (await self.session.execute(stmt)).scalars().all()}

    async def pick_random(
        self,
        *,
        category_ids: Sequence[uuid.UUID] | None = None,
        source: CardSource = CardSource.GENERATED,
        difficulty: DifficultyLevel | None = None,
        exclude_ids: Sequence[uuid.UUID] = (),
        forbid_ids: Sequence[uuid.UUID] = (),
    ) -> IncidentCard | None:
        variants: list[tuple[DifficultyLevel | None, bool]] = [(difficulty, True)]
        if difficulty is not None:
            variants.append((None, True))
        if exclude_ids:
            variants.append((difficulty, False))
            if difficulty is not None:
                variants.append((None, False))

        for level, respect_exclusions in variants:
            conditions = self._pool_conditions(category_ids, source, level)
            if respect_exclusions and exclude_ids:
                conditions.append(IncidentCard.id.notin_(exclude_ids))
            if forbid_ids:
                conditions.append(IncidentCard.id.notin_(forbid_ids))
            stmt = sa.select(IncidentCard).where(*conditions).order_by(sa.func.random()).limit(1)
            card = (await self.session.execute(stmt)).scalars().first()
            if card is not None:
                return card
        return None

    async def pool_size(
        self,
        *,
        category_ids: Sequence[uuid.UUID] | None = None,
        source: CardSource = CardSource.GENERATED,
        difficulty: DifficultyLevel | None = None,
    ) -> int:
        return await self.count(*self._pool_conditions(category_ids, source, difficulty))
