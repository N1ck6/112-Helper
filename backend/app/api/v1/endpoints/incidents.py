from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile

from app.api.deps import CurrentUser, PageDep, SessionDep, require
from app.core.pagination import Page, build_page
from app.core.permissions import Perm
from app.schemas.catalog import (
    IncidentCategorySummary,
    IncidentFeature,
    IncidentTypeImportRequest,
    IncidentTypeImportResult,
    IncidentTypeRead,
)
from app.services.incidents import IncidentCatalogService

router = APIRouter(prefix="/incidents", tags=["Классификатор происшествий"])


@router.get(
    "/categories",
    response_model=list[IncidentCategorySummary],
    summary="Категории классификатора",
    description=(
        "Категории из классификатора происшествий со счётчиком типов и, если задана, "
        "привязкой к учебной категории занятий."
    ),
)
async def list_categories(session: SessionDep, _: CurrentUser) -> list[IncidentCategorySummary]:
    rows = await IncidentCatalogService(session).categories_summary()
    return [IncidentCategorySummary.model_validate(row) for row in rows]


@router.get(
    "/types",
    response_model=Page[IncidentTypeRead],
    summary="Типы происшествий",
    description=(
        "Постраничный список типов. Фильтры: категория (по названию из таблицы или по "
        "идентификатору учебной категории), главная служба, поиск по наименованию и коду."
    ),
)
async def list_types(
    session: SessionDep,
    page: PageDep,
    _: CurrentUser,
    category: str | None = Query(None, description="Название категории из классификатора"),
    category_id: uuid.UUID | None = Query(None, description="Идентификатор учебной категории"),
    service: str | None = Query(None, description="Главная служба"),
    query: str | None = Query(None, description="Поиск по наименованию или коду"),
) -> Page[IncidentTypeRead]:
    items, total = await IncidentCatalogService(session).list_types(
        page, category_name=category, category_id=category_id, service=service, query=query
    )
    return build_page([IncidentTypeRead.model_validate(item) for item in items], total, page)


@router.post(
    "/import",
    response_model=IncidentTypeImportResult,
    summary="Импорт классификатора",
    description=(
        "Принимает нормализованные записи классификатора (их готовит импортёр таблицы "
        "на стороне ML). Записи с известным кодом обновляются, если не указано иное."
    ),
)
async def import_types(
    data: IncidentTypeImportRequest,
    session: SessionDep,
    request: Request,
    actor=Depends(require(Perm.CATALOG_WRITE)),
) -> IncidentTypeImportResult:
    result = await IncidentCatalogService(session).import_types(
        data.items, update_existing=data.update_existing, actor=actor, request=request
    )
    return IncidentTypeImportResult.model_validate(result)


@router.post(
    "/import/xlsx",
    response_model=IncidentTypeImportResult,
    summary="Импорт классификатора из таблицы XLSX",
    description=(
        "Разбирает таблицу классификатора заказчика и сохраняет нормализованные записи. "
        "Колонки определяются по заголовкам; безымянные колонки сохраняются в исходном "
        "виде, а ведомственные классификаторы — в agency_classifiers. Параметр limit "
        "позволяет загрузить сначала часть таблицы и проверить разбор."
    ),
)
async def import_xlsx(
    session: SessionDep,
    request: Request,
    file: UploadFile = File(..., description="Файл классификатора .xlsx"),
    sheet: str | None = Query(None, description="Лист книги; по умолчанию первый"),
    limit: int | None = Query(None, ge=1, le=100_000, description="Сколько строк загрузить"),
    actor=Depends(require(Perm.CATALOG_WRITE)),
) -> IncidentTypeImportResult:
    service = IncidentCatalogService(session)
    items = service.parse_xlsx(await file.read(), sheet=sheet, limit=limit)
    result = await service.import_types(items, actor=actor, request=request)
    return IncidentTypeImportResult.model_validate(result)


@router.get(
    "/{key}",
    response_model=IncidentTypeRead,
    summary="Тип происшествия",
    description="По коду классификатора (например, 2021103) либо по идентификатору записи.",
)
async def get_type(key: str, session: SessionDep, _: CurrentUser) -> IncidentTypeRead:
    return IncidentTypeRead.model_validate(await IncidentCatalogService(session).get_type(key))


@router.get(
    "/{key}/features",
    response_model=list[IncidentFeature],
    summary="Признаки типа происшествия",
    description="Комбинация признаков, которая в классификаторе даёт этот тип происшествия.",
)
async def get_features(key: str, session: SessionDep, _: CurrentUser) -> list[IncidentFeature]:
    features = await IncidentCatalogService(session).features_of(key)
    return [IncidentFeature.model_validate(feature) for feature in features]
