"""Классификатор происшествий и нормативы времени."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import PageDep, SessionDep, require
from app.core.pagination import Page, build_page
from app.core.permissions import Perm
from app.schemas.catalog import (
    CategoryCreate,
    CategoryRead,
    CategoryUpdate,
    TimeNormRead,
    TimeNormUpsert,
)
from app.schemas.common import MessageResponse
from app.services.catalog import CatalogService

router = APIRouter(tags=["Классификатор"])


@router.get("/categories", response_model=Page[CategoryRead], summary="Категории происшествий")
async def list_categories(
    session: SessionDep,
    page: PageDep,
    profile: str | None = Query(None, description="Профиль службы (Мосводоканал, Мосгаз, ...)"),
    _=Depends(require(Perm.CATALOG_READ)),
) -> Page[CategoryRead]:
    items, total = await CatalogService(session).list_categories(page, profile=profile)
    return build_page([CategoryRead.model_validate(item) for item in items], total, page)


@router.post(
    "/categories",
    response_model=CategoryRead,
    status_code=status.HTTP_201_CREATED,
    summary="Добавить категорию",
)
async def create_category(
    data: CategoryCreate,
    session: SessionDep,
    request: Request,
    actor=Depends(require(Perm.CATALOG_WRITE)),
) -> CategoryRead:
    category = await CatalogService(session).create_category(data, actor, request)
    return CategoryRead.model_validate(category)


@router.patch("/categories/{category_id}", response_model=CategoryRead, summary="Изменить категорию")
async def update_category(
    category_id: uuid.UUID,
    data: CategoryUpdate,
    session: SessionDep,
    request: Request,
    actor=Depends(require(Perm.CATALOG_WRITE)),
) -> CategoryRead:
    category = await CatalogService(session).update_category(category_id, data, actor, request)
    return CategoryRead.model_validate(category)


@router.delete(
    "/categories/{category_id}", response_model=MessageResponse, summary="Архивировать категорию"
)
async def delete_category(
    category_id: uuid.UUID,
    session: SessionDep,
    request: Request,
    actor=Depends(require(Perm.CATALOG_WRITE)),
) -> MessageResponse:
    await CatalogService(session).delete_category(category_id, actor, request)
    return MessageResponse(detail="Категория архивирована")


@router.get("/time-norms", response_model=list[TimeNormRead], summary="Нормативы времени")
async def list_norms(session: SessionDep, _=Depends(require(Perm.CATALOG_READ))) -> list[TimeNormRead]:
    norms = await CatalogService(session).list_norms()
    return [TimeNormRead.model_validate(norm) for norm in norms]


@router.put(
    "/time-norms",
    response_model=TimeNormRead,
    summary="Задать норматив времени (по умолчанию 30 секунд)",
)
async def upsert_norm(
    data: TimeNormUpsert,
    session: SessionDep,
    request: Request,
    actor=Depends(require(Perm.CATALOG_WRITE)),
) -> TimeNormRead:
    norm = await CatalogService(session).upsert_norm(data, actor, request)
    return TimeNormRead.model_validate(norm)
