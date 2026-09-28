from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import DutyService
from app.models.enums import ServiceLevel

#: Поля карточки, из которых берётся территория происшествия.
OKRUG_FIELD = "address_district"  # в карточке АРМ-112 это административный округ
AREA_FIELD = "address_area"  # а это район


def _normalize(value: object) -> str:
    text = str(value or "").strip().lower()
    for prefix in ("район ", "р-н ", "г. ", "город ", "дды ", "ддс "):
        if text.startswith(prefix):
            text = text[len(prefix) :]
    return text.replace("ё", "е").replace("-", " ").replace("  ", " ").strip()


class RoutingService:
    """Подбор служб по территории и подчинённости."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def services_for(
        self,
        payload: dict[str, Any] | None,
        category_codes: Sequence[str] = (),
    ) -> list[dict[str, Any]]:
        payload = payload or {}
        okrug = _normalize(payload.get(OKRUG_FIELD))
        area = _normalize(payload.get(AREA_FIELD))
        if not okrug and not area and not category_codes:
            return []

        services = await self._active_services()
        selected: dict[str, DutyService] = {}
        reasons: dict[str, str] = {}

        for service in services:
            reason = self._match_reason(service, okrug=okrug, area=area, categories=category_codes)
            if reason is None:
                continue
            selected[str(service.id)] = service
            reasons[str(service.id)] = reason

        by_id = {str(service.id): service for service in services}
        for key in list(selected):
            parent_id = selected[key].parent_id
            guard = 0
            while parent_id is not None and guard < 8:
                guard += 1
                parent = by_id.get(str(parent_id))
                if parent is None:
                    break
                if str(parent.id) not in selected:
                    selected[str(parent.id)] = parent
                    reasons[str(parent.id)] = f"подчинённость: {selected[key].name}"
                parent_id = parent.parent_id

        return [
            {
                "code": service.code,
                "name": service.name,
                "is_primary": bool(service.is_primary),
                "reason": reasons[key],
                "level": service.level.value,
                "phone": service.phone_extension or service.phone,
            }
            for key, service in sorted(
                selected.items(), key=lambda item: (not item[1].is_primary, item[1].code)
            )
        ]

    async def by_code(self, code: str) -> DutyService | None:
        result = await self.session.execute(
            sa.select(DutyService).where(
                DutyService.code == code, DutyService.deleted_at.is_(None)
            )
        )
        return result.scalar_one_or_none()

    async def list_services(
        self,
        *,
        level: ServiceLevel | None = None,
        okrug: str | None = None,
        area: str | None = None,
    ) -> Sequence[DutyService]:
        query = sa.select(DutyService).where(DutyService.deleted_at.is_(None))
        if level is not None:
            query = query.where(DutyService.level == level)
        if okrug:
            query = query.where(DutyService.okrug == okrug)
        if area:
            query = query.where(DutyService.area == area)
        result = await self.session.execute(query.order_by(DutyService.level, DutyService.code))
        return result.scalars().all()

    # ---------------------------------------------------------------- приватное
    async def _active_services(self) -> Sequence[DutyService]:
        result = await self.session.execute(
            sa.select(DutyService).where(
                DutyService.is_active.is_(True), DutyService.deleted_at.is_(None)
            )
        )
        return result.scalars().all()

    def _match_reason(
        self,
        service: DutyService,
        *,
        okrug: str,
        area: str,
        categories: Sequence[str],
    ) -> str | None:
        service_area = _normalize(service.area)
        service_okrug = _normalize(service.okrug)

        #: Ведомственная ДДС: привлекается по типу происшествия независимо от района.
        if categories and service.categories:
            known = {str(code) for code in service.categories}
            if known.intersection(categories):
                return "ведомственная принадлежность"

        #: Территория: сначала точное совпадение района, затем округ.
        if service_area and area and service_area == area:
            return f"район обслуживания: {service.area}"
        if service_okrug and okrug and service_okrug == okrug and not service_area:
            return f"округ: {service.okrug}"

        return None
