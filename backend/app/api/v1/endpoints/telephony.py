"""Телефония: настройка, журнал вызовов, вебхук модуля SIP/VoIP (п.2.9)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request

from app.api.deps import PageDep, SessionDep, require
from app.core.pagination import Page, build_page
from app.core.permissions import Perm
from app.schemas.system import (
    CallEventRequest,
    CallRead,
    TelephonyConfigRead,
    TelephonyConfigUpdate,
)
from app.services.telephony import TelephonyService

router = APIRouter(prefix="/telephony", tags=["Телефония"])


@router.get("/config", response_model=TelephonyConfigRead, summary="Параметры IP-телефонии")
async def get_config(
    session: SessionDep, _=Depends(require(Perm.TELEPHONY_MANAGE))
) -> TelephonyConfigRead:
    return TelephonyConfigRead.model_validate(await TelephonyService(session).get_config())


@router.patch("/config", response_model=TelephonyConfigRead, summary="Изменить параметры телефонии")
async def update_config(
    data: TelephonyConfigUpdate,
    session: SessionDep,
    request: Request,
    actor=Depends(require(Perm.TELEPHONY_MANAGE)),
) -> TelephonyConfigRead:
    config = await TelephonyService(session).update_config(data, actor, request)
    return TelephonyConfigRead.model_validate(config)


@router.get("/calls", response_model=Page[CallRead], summary="Журнал учебных вызовов")
async def list_calls(
    session: SessionDep,
    page: PageDep,
    lesson_id: uuid.UUID | None = None,
    student_id: uuid.UUID | None = None,
    _=Depends(require(Perm.TELEPHONY_MANAGE, Perm.LESSONS_MONITOR, any_of=True)),
) -> Page[CallRead]:
    items, total = await TelephonyService(session).list_calls(
        page, lesson_id=lesson_id, student_id=student_id
    )
    return build_page([CallRead.model_validate(item) for item in items], total, page)


@router.post(
    "/events",
    response_model=CallRead,
    summary="Вебхук модуля телефонии о событии вызова",
    description=(
        "Служебный эндпоинт для компонента SIP/VoIP. Авторизация — заголовок "
        "`X-Telephony-Token` (общий секрет внутри изолированного контура). "
        "Здесь фиксируются статус вызова, задержка (норматив ≤150 мс) и путь к аудиозаписи."
    ),
)
async def call_event(
    data: CallEventRequest,
    session: SessionDep,
    x_telephony_token: Annotated[str | None, Header(alias="X-Telephony-Token")] = None,
) -> CallRead:
    call = await TelephonyService(session).handle_event(data, x_telephony_token)
    return CallRead.model_validate(call)


@router.post("/calls/{call_id}/hangup", response_model=CallRead, summary="Завершить вызов")
async def hangup(
    call_id: uuid.UUID, session: SessionDep, actor=Depends(require(Perm.TELEPHONY_MANAGE))
) -> CallRead:
    return CallRead.model_validate(await TelephonyService(session).hangup(call_id, actor))
