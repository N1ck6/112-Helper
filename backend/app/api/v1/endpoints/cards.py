"""Карточки происшествий и шаблоны карточек АРМ-112 (п.2.5)."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile, status
from fastapi.responses import JSONResponse

from app.api.deps import CurrentUser, PageDep, SessionDep, require
from app.core.exceptions import BusinessRuleError
from app.core.pagination import Page, build_page
from app.core.permissions import Perm
from app.integrations.exchange import EXCHANGE_VERSION, card_to_dict, cards_from_xml, cards_to_xml
from app.models.enums import CardOrigin, CardStatus, DifficultyLevel
from app.schemas.card import (
    CardCreate,
    CardImportResult,
    CardRead,
    CardTemplateCreate,
    CardTemplateRead,
    CardUpdate,
    CardWithExpected,
)
from app.schemas.common import MessageResponse
from app.services.cards import CardService

router = APIRouter(tags=["Карточки АРМ-112"])


@router.get("/card-templates", response_model=list[CardTemplateRead], summary="Шаблоны карточек")
async def list_templates(session: SessionDep, _: CurrentUser) -> list[CardTemplateRead]:
    templates = await CardService(session).list_templates()
    return [CardTemplateRead.model_validate(item) for item in templates]


@router.get(
    "/card-templates/field-groups",
    response_model=list[dict],
    summary="Разделы карточки АРМ-112",
    description=(
        "Блоки карточки происшествия в том порядке, в котором они идут на АРМ-112: "
        "информация о карточке, телефоны, заявитель, адрес, что случилось, признаки, "
        "описание, отработка и оповещение. Используется frontend'ом для вкладок формы."
    ),
)
async def list_field_groups(session: SessionDep, _: CurrentUser) -> list[dict]:
    return CardService(session).field_groups()


@router.post(
    "/card-templates",
    response_model=CardTemplateRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создать шаблон карточки",
)
async def create_template(
    data: CardTemplateCreate,
    session: SessionDep,
    request: Request,
    actor=Depends(require(Perm.CARDS_WRITE)),
) -> CardTemplateRead:
    template = await CardService(session).create_template(data, actor, request)
    return CardTemplateRead.model_validate(template)


@router.get(
    "/cards",
    response_model=Page[CardRead],
    summary="Список карточек (пул занятий)",
    description=(
        "Пул учебных карточек — инструмент преподавателя и методиста. Обучающемуся "
        "он закрыт: в режиме заполнения карточки список служб оповещения и название "
        "происшествия и есть правильный ответ, и через общий список их можно было бы "
        "подсмотреть в обход маскировки, которая применяется при выдаче карточки."
    ),
)
async def list_cards(
    session: SessionDep,
    page: PageDep,
    category_id: uuid.UUID | None = None,
    origin: CardOrigin | None = Query(None, description="generated / student / manual"),
    card_status: CardStatus | None = Query(None, alias="status"),
    difficulty: DifficultyLevel | None = None,
    scenario_id: uuid.UUID | None = None,
    _=Depends(require(Perm.CARDS_WRITE)),
) -> Page[CardRead]:
    items, total = await CardService(session).list_cards(
        page,
        category_id=category_id,
        origin=origin,
        status=card_status,
        difficulty=difficulty,
        scenario_id=scenario_id,
    )
    return build_page([CardRead.model_validate(item) for item in items], total, page)


@router.post(
    "/cards", response_model=CardWithExpected, status_code=status.HTTP_201_CREATED, summary="Создать карточку"
)
async def create_card(
    data: CardCreate, session: SessionDep, request: Request, actor=Depends(require(Perm.CARDS_WRITE))
) -> CardWithExpected:
    card = await CardService(session).create(data, actor, request)
    return CardWithExpected.model_validate(card)


@router.get(
    "/cards/export",
    summary="Выгрузка карточек (JSON / XML)",
    description=(
        "Обмен с внешними системами в форматах системы-112: JSON для современных "
        "интеграций, XML — для legacy (п.2.1, 2.9 ТЗ). Коды полей совпадают с составом "
        "карточки АРМ-112, поэтому словарь соответствий не нужен."
    ),
)
async def export_cards(
    session: SessionDep,
    fmt: str = Query("json", alias="format", pattern="^(json|xml)$"),
    category_id: uuid.UUID | None = None,
    limit: int = Query(100, ge=1, le=1000),
    with_expected: bool = Query(False, description="Включать эталонные значения полей"),
    _=Depends(require(Perm.CARDS_READ)),
) -> Response:
    cards = await CardService(session).export_cards(category_id=category_id, limit=limit)
    if fmt == "xml":
        payload = cards_to_xml(cards, with_expected=with_expected)
        return Response(content=payload, media_type="application/xml; charset=utf-8")
    return JSONResponse(
        content={
            "version": EXCHANGE_VERSION,
            "count": len(cards),
            "cards": [card_to_dict(card, with_expected=with_expected) for card in cards],
        }
    )


@router.post(
    "/cards/import",
    response_model=CardImportResult,
    status_code=status.HTTP_201_CREATED,
    summary="Пакетный импорт карточек (JSON / XML)",
    description=(
        "Загружает пакет карточек из внешней системы. Формат определяется по расширению "
        "файла или по параметру format. Карточки с уже существующим номером пропускаются, "
        "список оповещения пересчитывается по ЕКП."
    ),
)
async def import_cards(
    session: SessionDep,
    request: Request,
    file: UploadFile = File(..., description="Файл .xml или .json"),
    category_id: uuid.UUID | None = Query(None, description="Категория для импортируемых карточек"),
    actor=Depends(require(Perm.CARDS_WRITE)),
) -> CardImportResult:
    raw = (await file.read()).decode("utf-8-sig", errors="replace")
    name = (file.filename or "").lower()
    try:
        if name.endswith(".xml") or raw.lstrip().startswith("<"):
            items = cards_from_xml(raw)
        else:
            payload = json.loads(raw)
            items = payload.get("cards") if isinstance(payload, dict) else payload
            if not isinstance(items, list) or not items:
                raise ValueError("Ожидается непустой список карточек")
    except ValueError as exc:
        raise BusinessRuleError(f"Не удалось разобрать файл: {exc}") from exc

    result = await CardService(session).import_cards(items, category_id, actor, request)
    return CardImportResult.model_validate(result)


@router.get(
    "/cards/{card_id}",
    response_model=CardWithExpected,
    summary="Карточка с эталоном (для преподавателя)",
)
async def get_card(
    card_id: uuid.UUID, session: SessionDep, _=Depends(require(Perm.CARDS_WRITE))
) -> CardWithExpected:
    return CardWithExpected.model_validate(await CardService(session).get(card_id))


@router.patch("/cards/{card_id}", response_model=CardWithExpected, summary="Изменить карточку")
async def update_card(
    card_id: uuid.UUID,
    data: CardUpdate,
    session: SessionDep,
    request: Request,
    actor=Depends(require(Perm.CARDS_WRITE)),
) -> CardWithExpected:
    card = await CardService(session).update(card_id, data, actor, request)
    return CardWithExpected.model_validate(card)


@router.delete("/cards/{card_id}", response_model=MessageResponse, summary="Архивировать карточку")
async def delete_card(
    card_id: uuid.UUID,
    session: SessionDep,
    request: Request,
    actor=Depends(require(Perm.CARDS_WRITE)),
) -> MessageResponse:
    await CardService(session).delete(card_id, actor, request)
    return MessageResponse(detail="Карточка архивирована")
