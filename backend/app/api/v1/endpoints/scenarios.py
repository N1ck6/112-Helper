"""Сценарии, эталоны, генерация нейросетью и проверка грамматики (п.2.4, 2.9)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import PageDep, SessionDep, require
from app.core.pagination import Page, build_page
from app.core.permissions import Perm
from app.models.enums import DifficultyLevel, ScenarioStatus
from app.schemas.common import MessageResponse
from app.schemas.scenario import (
    CorrectScenarioRequest,
    GenerateScenariosRequest,
    GrammarCheckRequest,
    ReferenceCreate,
    ReferenceRead,
    ReferenceUpdate,
    ScenarioApproveRequest,
    ScenarioCreate,
    ScenarioRead,
    ScenarioUpdate,
)
from app.services.scenarios import ScenarioService

router = APIRouter(prefix="/scenarios", tags=["Учебные сценарии"])


@router.get("", response_model=Page[ScenarioRead], summary="Список сценариев")
async def list_scenarios(
    session: SessionDep,
    page: PageDep,
    scenario_status: ScenarioStatus | None = Query(None, alias="status"),
    category_id: uuid.UUID | None = None,
    difficulty: DifficultyLevel | None = None,
    _=Depends(require(Perm.SCENARIOS_READ)),
) -> Page[ScenarioRead]:
    items, total = await ScenarioService(session).list_scenarios(
        page, status=scenario_status, category_id=category_id, difficulty=difficulty
    )
    return build_page([ScenarioRead.model_validate(item) for item in items], total, page)


@router.post(
    "", response_model=ScenarioRead, status_code=status.HTTP_201_CREATED, summary="Создать сценарий"
)
async def create_scenario(
    data: ScenarioCreate,
    session: SessionDep,
    request: Request,
    actor=Depends(require(Perm.SCENARIOS_WRITE)),
) -> ScenarioRead:
    return ScenarioRead.model_validate(await ScenarioService(session).create(data, actor, request))


@router.post(
    "/generate",
    response_model=list[ScenarioRead],
    status_code=status.HTTP_201_CREATED,
    summary="Сгенерировать сценарии нейросетью",
    description=(
        "Обращается к ML-сервису, сохраняет сценарии со статусом «на проверке» и создаёт "
        "черновые карточки. В занятие карточки попадут только после утверждения эталонов."
    ),
)
async def generate_scenarios(
    data: GenerateScenariosRequest,
    session: SessionDep,
    request: Request,
    actor=Depends(require(Perm.SCENARIOS_GENERATE)),
) -> list[ScenarioRead]:
    scenarios = await ScenarioService(session).generate(data, actor, request)
    return [ScenarioRead.model_validate(item) for item in scenarios]


@router.get("/{scenario_id}", response_model=ScenarioRead, summary="Сценарий с эталонами")
async def get_scenario(
    scenario_id: uuid.UUID, session: SessionDep, _=Depends(require(Perm.SCENARIOS_READ))
) -> ScenarioRead:
    return ScenarioRead.model_validate(await ScenarioService(session).get(scenario_id))


@router.get(
    "/{scenario_id}/preview",
    summary="Предпросмотр вопросов и правильных ответов",
    description="Для преподавателя: карточки, вопросы и подсветка верных вариантов (п.10 ТЗ).",
)
async def preview_scenario(
    scenario_id: uuid.UUID, session: SessionDep, _=Depends(require(Perm.SCENARIOS_READ))
) -> dict[str, Any]:
    data = await ScenarioService(session).preview(scenario_id)
    return {
        "scenario": ScenarioRead.model_validate(data["scenario"]).model_dump(mode="json"),
        "cards": data["cards"],
        "questions": data["questions"],
    }


@router.patch("/{scenario_id}", response_model=ScenarioRead, summary="Изменить сценарий")
async def update_scenario(
    scenario_id: uuid.UUID,
    data: ScenarioUpdate,
    session: SessionDep,
    request: Request,
    actor=Depends(require(Perm.SCENARIOS_WRITE)),
) -> ScenarioRead:
    scenario = await ScenarioService(session).update(scenario_id, data, actor, request)
    return ScenarioRead.model_validate(scenario)


@router.post(
    "/{scenario_id}/approve",
    response_model=ScenarioRead,
    summary="Утвердить эталоны (полностью или частично)",
)
async def approve_scenario(
    scenario_id: uuid.UUID,
    data: ScenarioApproveRequest,
    session: SessionDep,
    request: Request,
    actor=Depends(require(Perm.SCENARIOS_APPROVE)),
) -> ScenarioRead:
    scenario = await ScenarioService(session).approve(scenario_id, data, actor, request)
    return ScenarioRead.model_validate(scenario)


@router.post(
    "/{scenario_id}/correct",
    response_model=ScenarioRead,
    summary="Скорректировать генерацию комментарием преподавателя",
)
async def correct_scenario(
    scenario_id: uuid.UUID,
    data: CorrectScenarioRequest,
    session: SessionDep,
    request: Request,
    actor=Depends(require(Perm.SCENARIOS_GENERATE)),
) -> ScenarioRead:
    scenario = await ScenarioService(session).correct(scenario_id, data, actor, request)
    return ScenarioRead.model_validate(scenario)


@router.post(
    "/{scenario_id}/references",
    response_model=ReferenceRead,
    status_code=status.HTTP_201_CREATED,
    summary="Добавить эталонный ответ",
)
async def add_reference(
    scenario_id: uuid.UUID,
    data: ReferenceCreate,
    session: SessionDep,
    request: Request,
    actor=Depends(require(Perm.SCENARIOS_WRITE)),
) -> ReferenceRead:
    reference = await ScenarioService(session).add_reference(scenario_id, data, actor, request)
    return ReferenceRead.model_validate(reference)


@router.patch(
    "/references/{reference_id}",
    response_model=ReferenceRead,
    summary="Изменить эталон (снимает утверждение)",
)
async def update_reference(
    reference_id: uuid.UUID,
    data: ReferenceUpdate,
    session: SessionDep,
    request: Request,
    actor=Depends(require(Perm.SCENARIOS_WRITE)),
) -> ReferenceRead:
    reference = await ScenarioService(session).update_reference(reference_id, data, actor, request)
    return ReferenceRead.model_validate(reference)


@router.delete("/{scenario_id}", response_model=MessageResponse, summary="Архивировать сценарий")
async def delete_scenario(
    scenario_id: uuid.UUID,
    session: SessionDep,
    request: Request,
    actor=Depends(require(Perm.SCENARIOS_WRITE)),
) -> MessageResponse:
    await ScenarioService(session).delete(scenario_id, actor, request)
    return MessageResponse(detail="Сценарий архивирован")


@router.post(
    "/grammar-check",
    summary="Принудительная проверка грамматики",
    description="Используется после ручных правок сценария или эталона (п.10 ТЗ).",
)
async def grammar_check(
    data: GrammarCheckRequest, session: SessionDep, _=Depends(require(Perm.SCENARIOS_WRITE))
) -> dict[str, Any]:
    service = ScenarioService(session)
    text = data.text
    if text is None and data.scenario_id:
        scenario = await service.get(data.scenario_id)
        text = " ".join(
            filter(None, [scenario.title, scenario.description, str(scenario.briefing or "")])
        )
    return await service.check_grammar(text or "")
