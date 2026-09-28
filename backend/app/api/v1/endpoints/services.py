from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import CurrentUser, SessionDep, require
from app.core.exceptions import BusinessRuleError, NotFoundError
from app.core.permissions import Perm
from app.models.catalog import DutyService
from app.models.enums import AuditAction, ServiceLevel
from app.schemas.catalog import (
    DutyServiceCreate,
    DutyServiceRead,
    DutyServiceUpdate,
    RoutingPreviewRequest,
)
from app.schemas.common import MessageResponse
from app.services.audit import AuditService
from app.services.cards import CardService
from app.services.routing import RoutingService

router = APIRouter(prefix="/services", tags=["Справочник ДДС"])


@router.get("", response_model=list[DutyServiceRead], summary="Справочник служб")
async def list_services(
    session: SessionDep,
    user: CurrentUser,
    level: ServiceLevel | None = None,
    okrug: str | None = None,
    area: str | None = None,
) -> list[DutyServiceRead]:
    items = await RoutingService(session).list_services(level=level, okrug=okrug, area=area)
    return [DutyServiceRead.model_validate(item) for item in items]


@router.get("/{code}", response_model=DutyServiceRead, summary="Служба по коду")
async def get_service(code: str, session: SessionDep, user: CurrentUser) -> DutyServiceRead:
    service = await RoutingService(session).by_code(code)
    if service is None:
        raise NotFoundError(f"Служба «{code}» не найдена")
    return DutyServiceRead.model_validate(service)


@router.post(
    "",
    response_model=DutyServiceRead,
    status_code=status.HTTP_201_CREATED,
    summary="Добавить службу в справочник",
)
async def create_service(
    data: DutyServiceCreate,
    session: SessionDep,
    request: Request,
    actor=Depends(require(Perm.CATALOG_WRITE)),
) -> DutyServiceRead:
    routing = RoutingService(session)
    if await routing.by_code(data.code) is not None:
        raise BusinessRuleError(f"Служба с кодом «{data.code}» уже есть в справочнике")

    parent = await routing.by_code(data.parent_code) if data.parent_code else None
    if data.parent_code and parent is None:
        raise BusinessRuleError(f"Вышестоящая служба «{data.parent_code}» не найдена")

    service = DutyService(
        code=data.code,
        name=data.name,
        short_name=data.short_name,
        level=data.level,
        okrug=data.okrug,
        area=data.area,
        parent_id=parent.id if parent else None,
        phone_extension=data.phone_extension,
        phone=data.phone,
        supervisor=data.supervisor,
        categories=data.categories,
        is_primary=data.is_primary,
        is_active=data.is_active,
    )
    session.add(service)
    await session.flush()
    await AuditService(session).log(
        AuditAction.CREATE,
        actor=actor,
        object_type="duty_service",
        object_id=service.id,
        summary=f"Добавлена служба {service.code} — {service.name}",
        request=request,
    )
    return DutyServiceRead.model_validate(service)


@router.patch("/{code}", response_model=DutyServiceRead, summary="Изменить службу")
async def update_service(
    code: str,
    data: DutyServiceUpdate,
    session: SessionDep,
    request: Request,
    actor=Depends(require(Perm.CATALOG_WRITE)),
) -> DutyServiceRead:
    routing = RoutingService(session)
    service = await routing.by_code(code)
    if service is None:
        raise NotFoundError(f"Служба «{code}» не найдена")

    payload = data.model_dump(exclude_unset=True)
    parent_code = payload.pop("parent_code", None)
    if parent_code is not None:
        parent = await routing.by_code(parent_code) if parent_code else None
        if parent_code and parent is None:
            raise BusinessRuleError(f"Вышестоящая служба «{parent_code}» не найдена")
        if parent is not None and parent.id == service.id:
            raise BusinessRuleError("Служба не может быть подчинена сама себе")
        service.parent_id = parent.id if parent else None

    for field, value in payload.items():
        if value is not None:
            setattr(service, field, value)
    await session.flush()
    await AuditService(session).log(
        AuditAction.UPDATE,
        actor=actor,
        object_type="duty_service",
        object_id=service.id,
        summary=f"Изменена служба {service.code}",
        request=request,
    )
    return DutyServiceRead.model_validate(service)


@router.delete("/{code}", response_model=MessageResponse, summary="Удалить службу")
async def delete_service(
    code: str,
    session: SessionDep,
    request: Request,
    actor=Depends(require(Perm.CATALOG_WRITE)),
) -> MessageResponse:
    routing = RoutingService(session)
    service = await routing.by_code(code)
    if service is None:
        raise NotFoundError(f"Служба «{code}» не найдена")
    from app.core.security import utcnow

    service.deleted_at = utcnow()
    service.is_active = False
    await session.flush()
    await AuditService(session).log(
        AuditAction.DELETE,
        actor=actor,
        object_type="duty_service",
        object_id=service.id,
        summary=f"Удалена служба {service.code}",
        request=request,
    )
    return MessageResponse(detail="Служба удалена из справочника")


@router.post(
    "/routing/preview",
    summary="Куда уйдёт карточка с таким адресом",
    description=(
        "Собирает список оповещения, не создавая карточку: экстренные службы по ЕКП, "
        "ДДС района по адресу, вышестоящие ДДС по подчинённости и ведомственные "
        "службы по категории. У каждой записи указана причина попадания в список."
    ),
)
async def routing_preview(
    data: RoutingPreviewRequest, session: SessionDep, user: CurrentUser
) -> dict:
    services = await CardService(session).notification_list(
        category_id=data.category_id,
        payload=data.payload,
        extra_services=data.extra_services,
        incident_type_code=data.incident_type_code,
    )
    return {
        "notification_list": services,
        "primary": [item["code"] for item in services if item.get("is_primary")],
        "total": len(services),
    }
