"""Карточки происшествий и шаблоны карточек (п.2.5 ТЗ)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.arm112 import CARD_FIELD_GROUPS, build_notification_list
from app.core.arm112 import DEFAULT_TEMPLATE_FIELDS as ARM112_TEMPLATE_FIELDS
from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError
from app.core.pagination import PageParams
from app.models.card import CardTemplate, IncidentCard
from app.models.enums import AuditAction, CardOrigin, CardStatus, DifficultyLevel
from app.models.training import CardAttempt
from app.models.user import User
from app.repositories.content import (
    CardRepository,
    CardTemplateRepository,
    CategoryRepository,
    IncidentTypeRepository,
)
from app.schemas.card import CardCreate, CardTemplateCreate, CardUpdate
from app.services.audit import AuditService
from app.services.routing import RoutingService

DEFAULT_TEMPLATE_FIELDS = ARM112_TEMPLATE_FIELDS


class CardService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.cards = CardRepository(session)
        self.templates = CardTemplateRepository(session)
        self.categories = CategoryRepository(session)
        self.incident_types = IncidentTypeRepository(session)
        self.routing = RoutingService(session)
        self.audit = AuditService(session)

    # ------------------------------------------------------- список оповещения
    async def notification_list(
        self,
        category_id: uuid.UUID | None,
        payload: dict | None = None,
        extra_services: list[str] | None = None,
        incident_type_code: str | None = None,
    ) -> list[dict]:
        from_type: list[dict] = []
        if incident_type_code:
            entry = await self.incident_types.by_code(incident_type_code)
            if entry is not None:
                from_type = list(entry.services or [])

        chain = await self.categories.ancestry(category_id)
        catalog = {
            category.code: category.notify_services
            for category in chain
            if category.notify_services
        }
        computed = build_notification_list(
            [category.code for category in chain],
            flags=payload or {},
            extra_services=extra_services,
            catalog=catalog or None,
        )
        if from_type:
            known = {item.get("code") for item in from_type}
            computed = [*from_type, *(item for item in computed if item.get("code") not in known)]

        territorial = await self.routing.services_for(
            payload, category_codes=[category.code for category in chain]
        )
        if territorial:
            known = {item.get("code") for item in computed}
            computed = [*computed, *(item for item in territorial if item.get("code") not in known)]
        return computed

    def field_groups(self) -> list[dict]:
        return CARD_FIELD_GROUPS

    # -------------------------------------------------------------- шаблоны
    async def list_templates(self) -> Sequence[CardTemplate]:
        return await self.templates.list_all(CardTemplate.is_active.is_(True))

    async def get_template(self, template_id: uuid.UUID | None) -> CardTemplate | None:
        if template_id is None:
            return await self.templates.default_template()
        return await self.templates.get(template_id)

    async def create_template(
        self, data: CardTemplateCreate, actor: User, request: Request | None = None
    ) -> CardTemplate:
        if await self.templates.by_code(data.code):
            raise ConflictError(f"Шаблон «{data.code}» уже существует")
        if data.is_default:
            for template in await self.templates.list_all(CardTemplate.is_default.is_(True)):
                template.is_default = False
        template = await self.templates.create(
            code=data.code,
            name=data.name,
            fields_schema=data.fields_schema,
            is_default=data.is_default,
        )
        await self.audit.log(
            AuditAction.CREATE,
            actor=actor,
            object_type="card_template",
            object_id=template.id,
            summary=f"Создан шаблон карточки {template.code}",
            request=request,
        )
        return template

    # -------------------------------------------------------------- карточки
    async def list_cards(
        self,
        params: PageParams,
        *,
        category_id: uuid.UUID | None = None,
        origin: CardOrigin | None = None,
        status: CardStatus | None = None,
        difficulty: DifficultyLevel | None = None,
        scenario_id: uuid.UUID | None = None,
    ) -> tuple[Sequence[IncidentCard], int]:
        conditions = [IncidentCard.is_active.is_(True)]
        if category_id:
            conditions.append(IncidentCard.category_id == category_id)
        if origin:
            conditions.append(IncidentCard.origin == origin)
        if status:
            conditions.append(IncidentCard.status == status)
        if difficulty:
            conditions.append(IncidentCard.difficulty == difficulty)
        if scenario_id:
            conditions.append(IncidentCard.scenario_id == scenario_id)
        return await self.cards.paginate(params, *conditions)

    async def get(self, card_id: uuid.UUID) -> IncidentCard:
        card = await self.cards.get(card_id)
        if card is None:
            raise NotFoundError("Карточка не найдена")
        return card

    async def create(self, data: CardCreate, actor: User, request: Request | None = None) -> IncidentCard:
        card_no = data.card_no or await self.cards.next_card_no()
        if await self.cards.find_one(IncidentCard.card_no == card_no):
            raise ConflictError(f"Карточка с номером {card_no} уже существует")
        template = await self.get_template(data.template_id)
        card = await self.cards.create(
            card_no=card_no,
            title=data.title,
            template_id=template.id if template else None,
            scenario_id=data.scenario_id,
            category_id=data.category_id,
            origin=data.origin,
            status=CardStatus.READY,
            difficulty=data.difficulty,
            caller_profile=data.caller_profile,
            payload=data.payload,
            expected_payload=data.expected_payload,
            incident_type_code=data.incident_type_code,
            notification_list=await self.notification_list(
                data.category_id,
                data.payload or data.expected_payload,
                data.extra_services,
                data.incident_type_code,
            ),
            time_limit_seconds=data.time_limit_seconds,
            author_id=actor.id,
        )
        await self.audit.log(
            AuditAction.CREATE,
            actor=actor,
            object_type="incident_card",
            object_id=card.id,
            summary=f"Создана карточка {card.card_no}",
            request=request,
        )
        return card

    async def update(
        self, card_id: uuid.UUID, data: CardUpdate, actor: User, request: Request | None = None
    ) -> IncidentCard:
        card = await self.get(card_id)
        changes = data.model_dump(exclude_unset=True)
        await self.cards.update(card, **changes)
        if {"category_id", "payload", "incident_type_code"} & set(changes):
            recomputed = await self.notification_list(
                card.category_id, card.payload, incident_type_code=card.incident_type_code
            )
            known = {item.get("code") for item in card.notification_list or []}
            card.notification_list = [
                *(card.notification_list or []),
                *(item for item in recomputed if item.get("code") not in known),
            ]
            await self.session.flush()
        await self.audit.log(
            AuditAction.UPDATE,
            actor=actor,
            object_type="incident_card",
            object_id=card.id,
            summary=f"Изменена карточка {card.card_no}",
            request=request,
        )
        return card

    async def delete(self, card_id: uuid.UUID, actor: User, request: Request | None = None) -> None:
        card = await self.get(card_id)
        await self.cards.soft_delete(card)
        card.status = CardStatus.ARCHIVED
        await self.session.flush()
        await self.audit.log(
            AuditAction.DELETE,
            actor=actor,
            object_type="incident_card",
            object_id=card_id,
            summary=f"Карточка {card.card_no} архивирована",
            request=request,
        )

    # ----------------------------------------------------------- обмен данными
    async def export_cards(
        self, *, category_id: uuid.UUID | None = None, limit: int = 100
    ) -> list[IncidentCard]:
        conditions = [IncidentCard.is_active.is_(True), IncidentCard.status == CardStatus.READY]
        if category_id:
            conditions.append(IncidentCard.category_id == category_id)
        return list(await self.cards.list_all(*conditions, limit=limit))

    async def import_cards(
        self,
        items: list[dict],
        category_id: uuid.UUID | None,
        actor: User,
        request: Request | None = None,
    ) -> dict:
        template = await self.templates.default_template()
        imported: list[uuid.UUID] = []
        warnings: list[str] = []

        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                warnings.append(f"Запись №{index}: ожидается объект с полями карточки")
                continue
            fields = item.get("fields") or item.get("payload") or {}
            expected = item.get("expected_fields") or {}
            if not fields and not expected:
                warnings.append(f"Запись №{index}: нет значений полей карточки")
                continue

            card_no = str(item.get("card_no") or "").strip() or await self.cards.next_card_no()
            if await self.cards.find_one(IncidentCard.card_no == card_no):
                warnings.append(f"Карточка {card_no} уже есть в системе — пропущена")
                continue

            target_category = category_id or _as_uuid(item.get("category_id"))
            card = await self.cards.create(
                card_no=card_no,
                title=str(item.get("title") or "Импортированная карточка")[:255],
                template_id=template.id if template else None,
                category_id=target_category,
                origin=_as_origin(item.get("origin")),
                status=CardStatus.READY,
                difficulty=_as_difficulty(item.get("difficulty")),
                caller_profile=item.get("caller_profile") or {},
                payload=fields,
                expected_payload=expected,
                notification_list=await self.notification_list(
                    target_category, fields or expected, item.get("extra_services") or []
                ),
                author_id=actor.id,
            )
            imported.append(card.id)

        await self.audit.log(
            AuditAction.CREATE,
            actor=actor,
            object_type="incident_card",
            summary=f"Импорт карточек: загружено {len(imported)}, пропущено {len(warnings)}",
            after={"imported": len(imported), "skipped": len(warnings)},
            request=request,
        )
        return {
            "imported": len(imported),
            "skipped": len(warnings),
            "card_ids": imported,
            "warnings": warnings,
        }

    async def create_from_attempt(
        self, attempt: CardAttempt, actor: User, request: Request | None = None
    ) -> IncidentCard:
        """Карточка, сформированная обучающимся, — источник заданий второго режима (п.2.5)."""
        if not attempt.submitted_payload:
            raise BusinessRuleError("Карточка обучающегося ещё не заполнена")
        source = await self.get(attempt.card_id)
        card = await self.cards.create(
            card_no=await self.cards.next_card_no(),
            title=f"{source.title} (заполнил {actor.full_name})",
            template_id=source.template_id,
            scenario_id=source.scenario_id,
            category_id=source.category_id,
            origin=CardOrigin.STUDENT,
            status=CardStatus.READY,
            difficulty=source.difficulty,
            caller_profile=source.caller_profile,
            payload=attempt.submitted_payload,
            expected_payload=source.expected_payload,
            notification_list=source.notification_list
            or await self.notification_list(source.category_id, attempt.submitted_payload),
            author_id=attempt.student_id,
            source_attempt_id=attempt.id,
            time_limit_seconds=source.time_limit_seconds,
        )
        await self.audit.log(
            AuditAction.CREATE,
            actor=actor,
            object_type="incident_card",
            object_id=card.id,
            summary=f"Карточка {card.card_no} создана из работы обучающегося",
            request=request,
        )
        return card

    async def ensure_default_template(self) -> CardTemplate:
        """Используется seed-скриптом и тестами."""
        template = await self.templates.default_template()
        if template is None:
            template = await self.templates.create(
                code="arm112_default",
                name="Карточка происшествия АРМ-112",
                fields_schema=DEFAULT_TEMPLATE_FIELDS,
                is_default=True,
            )
        return template


def _as_uuid(value: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except (ValueError, AttributeError):
        return None


def _as_difficulty(value: object) -> DifficultyLevel:
    try:
        return DifficultyLevel(str(value))
    except ValueError:
        return DifficultyLevel.BASIC


def _as_origin(value: object) -> CardOrigin:
    """Источник карточки из файла обмена; неизвестное значение — «создана вручную»."""
    try:
        return CardOrigin(str(value))
    except ValueError:
        return CardOrigin.MANUAL
