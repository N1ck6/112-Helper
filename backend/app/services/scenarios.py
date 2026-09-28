from __future__ import annotations

import time
import uuid
from collections.abc import Sequence
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessRuleError, NotFoundError
from app.core.pagination import PageParams
from app.core.security import utcnow
from app.integrations.ml_client import get_ml_client
from app.models.card import IncidentCard
from app.models.enums import (
    AuditAction,
    CardOrigin,
    CardStatus,
    DifficultyLevel,
    GenerationStatus,
    MaterialKind,
    MLTaskKind,
    MLTaskStatus,
    ScenarioOrigin,
    ScenarioStatus,
)
from app.models.grading import MLResult
from app.models.scenario import GenerationRequest, Scenario, ScenarioReference, TrainingMaterial
from app.models.user import User
from app.repositories.content import (
    CardRepository,
    CardTemplateRepository,
    CategoryRepository,
    GenerationRequestRepository,
    MaterialRepository,
    ReferenceRepository,
    ScenarioRepository,
)
from app.schemas.scenario import (
    CorrectScenarioRequest,
    GenerateScenariosRequest,
    ReferenceCreate,
    ReferenceUpdate,
    ScenarioApproveRequest,
    ScenarioCreate,
    ScenarioUpdate,
)
from app.services.audit import AuditService
from app.services.cards import CardService


class ScenarioService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.scenarios = ScenarioRepository(session)
        self.references = ReferenceRepository(session)
        self.categories = CategoryRepository(session)
        self.cards = CardRepository(session)
        self.templates = CardTemplateRepository(session)
        self.requests = GenerationRequestRepository(session)
        self.audit = AuditService(session)
        self.ml = get_ml_client()

    async def list_scenarios(
        self,
        params: PageParams,
        *,
        status: ScenarioStatus | None = None,
        category_id: uuid.UUID | None = None,
        difficulty: DifficultyLevel | None = None,
    ) -> tuple[Sequence[Scenario], int]:
        conditions = [Scenario.is_active.is_(True)]
        if status:
            conditions.append(Scenario.status == status)
        if category_id:
            conditions.append(Scenario.category_id == category_id)
        if difficulty:
            conditions.append(Scenario.difficulty == difficulty)
        return await self.scenarios.paginate(params, *conditions)

    async def get(self, scenario_id: uuid.UUID) -> Scenario:
        scenario = await self.scenarios.get_with_references(scenario_id)
        if scenario is None:
            raise NotFoundError("Сценарий не найден")
        return scenario

    async def create(
        self, data: ScenarioCreate, actor: User, request: Request | None = None
    ) -> Scenario:
        scenario = Scenario(
            title=data.title,
            description=data.description,
            category_id=data.category_id,
            difficulty=data.difficulty,
            time_limit_seconds=data.time_limit_seconds,
            success_criteria=data.success_criteria,
            briefing=data.briefing,
            origin=ScenarioOrigin.MANUAL,
            status=ScenarioStatus.DRAFT,
            author_id=actor.id,
        )
        for ref in data.references:
            scenario.references.append(ScenarioReference(**ref.model_dump()))
        self.session.add(scenario)
        await self.session.flush()
        await self.audit.log(
            AuditAction.CREATE,
            actor=actor,
            object_type="scenario",
            object_id=scenario.id,
            summary=f"Создан сценарий «{scenario.title}»",
            request=request,
        )
        return await self.get(scenario.id)

    async def update(
        self, scenario_id: uuid.UUID, data: ScenarioUpdate, actor: User, request: Request | None = None
    ) -> Scenario:
        scenario = await self.get(scenario_id)
        self._ensure_editable(scenario)
        before = {"title": scenario.title, "status": scenario.status.value}
        for field, value in data.model_dump(exclude_unset=True).items():
            if value is not None:
                setattr(scenario, field, value)
        #: Правка утверждённого сценария возвращает его на повторную проверку.
        if scenario.status == ScenarioStatus.APPROVED:
            scenario.status = ScenarioStatus.PENDING_REVIEW
            scenario.approved_at = None
            scenario.approved_by_id = None
        scenario.version += 1
        await self.session.flush()
        await self.audit.log(
            AuditAction.UPDATE,
            actor=actor,
            object_type="scenario",
            object_id=scenario.id,
            summary="Сценарий изменён",
            before=before,
            after={"title": scenario.title, "status": scenario.status.value},
            request=request,
        )
        return await self.get(scenario_id)

    async def delete(self, scenario_id: uuid.UUID, actor: User, request: Request | None = None) -> None:
        scenario = await self.get(scenario_id)
        self._ensure_editable(scenario)
        await self.scenarios.soft_delete(scenario)
        scenario.status = ScenarioStatus.ARCHIVED
        await self.session.flush()
        await self.audit.log(
            AuditAction.DELETE,
            actor=actor,
            object_type="scenario",
            object_id=scenario_id,
            summary="Сценарий архивирован",
            request=request,
        )

    async def add_reference(
        self, scenario_id: uuid.UUID, data: ReferenceCreate, actor: User, request: Request | None = None
    ) -> ScenarioReference:
        scenario = await self.get(scenario_id)
        reference = ScenarioReference(scenario_id=scenario.id, **data.model_dump())
        self.session.add(reference)
        await self.session.flush()
        await self.audit.log(
            AuditAction.CREATE,
            actor=actor,
            object_type="scenario_reference",
            object_id=reference.id,
            summary="Добавлен эталонный ответ",
            request=request,
        )
        return reference

    async def update_reference(
        self, reference_id: uuid.UUID, data: ReferenceUpdate, actor: User, request: Request | None = None
    ) -> ScenarioReference:
        reference = await self.references.get_or_fail(reference_id, "Эталон не найден")
        before = {"expected_fields": reference.expected_fields}
        for field, value in data.model_dump(exclude_unset=True).items():
            if value is not None:
                setattr(reference, field, value)
        reference.approved_at = None
        reference.approved_by_id = None
        await self.session.flush()
        await self.audit.log(
            AuditAction.UPDATE,
            actor=actor,
            object_type="scenario_reference",
            object_id=reference.id,
            summary="Эталон изменён вручную, требуется повторное утверждение",
            before=before,
            request=request,
        )
        return reference

    async def approve(
        self,
        scenario_id: uuid.UUID,
        data: ScenarioApproveRequest,
        actor: User,
        request: Request | None = None,
    ) -> Scenario:
        """Полное или частичное подтверждение эталонов преподавателем (п.10 ТЗ)."""
        scenario = await self.get(scenario_id)
        target_ids = set(data.reference_ids or [])
        approved = 0
        for reference in scenario.references:
            if target_ids and reference.id not in target_ids:
                continue
            reference.approved_by_id = actor.id
            reference.approved_at = utcnow()
            if data.comment:
                reference.teacher_comment = data.comment
            approved += 1

        all_approved = all(ref.approved_at is not None for ref in scenario.references)
        if not scenario.references:
            raise BusinessRuleError("У сценария нет эталонных ответов — утверждать нечего")
        scenario.status = ScenarioStatus.APPROVED if all_approved else ScenarioStatus.PENDING_REVIEW
        if all_approved:
            scenario.approved_by_id = actor.id
            scenario.approved_at = utcnow()
            await self._publish_cards(scenario)
        await self.session.flush()

        await self.audit.log(
            AuditAction.UPDATE,
            actor=actor,
            object_type="scenario",
            object_id=scenario.id,
            summary=f"Утверждено эталонов: {approved}. Статус: {scenario.status.value}",
            after={"status": scenario.status.value},
            request=request,
        )
        return await self.get(scenario_id)

    # ---------------------------------------------------------- генерация ИИ
    async def generate(
        self, data: GenerateScenariosRequest, actor: User, request: Request | None = None
    ) -> list[Scenario]:
        category = None
        if data.category_id:
            category = await self.categories.get_or_fail(data.category_id, "Категория не найдена")

        gen_request = GenerationRequest(
            requested_by_id=actor.id,
            category_id=data.category_id,
            difficulty=data.difficulty,
            count=data.count,
            prompt=data.prompt,
            status=GenerationStatus.IN_PROGRESS,
        )
        self.session.add(gen_request)
        await self.session.flush()

        payload: dict[str, Any] = {
            "count": data.count,
            "difficulty": data.difficulty.value,
            "category_code": category.code if category else None,
            "category_name": category.name if category else None,
            "prompt": data.prompt,
            "required_fields": (category.required_fields if category else []) or [],
        }
        started = time.perf_counter()
        try:
            response = await self.ml.generate_scenarios(payload)
        except Exception as exc:  # noqa: BLE001 — сбой ML не должен ронять запрос
            gen_request.status = GenerationStatus.FAILED
            gen_request.error = str(exc)[:1000]
            await self._log_ml(
                MLTaskKind.GENERATION, "generate_scenarios", payload, {}, MLTaskStatus.FAILED, str(exc)
            )
            raise

        latency = int((time.perf_counter() - started) * 1000)
        await self._log_ml(
            MLTaskKind.GENERATION, "generate_scenarios", payload, response, MLTaskStatus.OK, None, latency
        )

        created: list[Scenario] = []
        for item in response.get("scenarios", []):
            scenario = await self._materialize(item, data, actor, category_id=data.category_id, response=response)
            created.append(scenario)
            if data.with_cards:
                await self._draft_card(scenario, item)

        gen_request.status = GenerationStatus.READY
        gen_request.ml_response = {"count": len(created), "model": response.get("model")}
        gen_request.scenario_id = created[0].id if created else None
        await self.session.flush()

        await self.audit.log(
            AuditAction.CREATE,
            actor=actor,
            object_type="scenario",
            object_id=gen_request.id,
            summary=f"Нейросеть сгенерировала сценариев: {len(created)}",
            after={"model": response.get("model"), "count": len(created)},
            request=request,
        )
        return [await self.get(s.id) for s in created]

    async def correct(
        self,
        scenario_id: uuid.UUID,
        data: CorrectScenarioRequest,
        actor: User,
        request: Request | None = None,
    ) -> Scenario:
        """Коррекция генерации по комментарию преподавателя (п.10, п.3.2 ТЗ)."""
        scenario = await self.get(scenario_id)
        reference = None
        if data.reference_id:
            reference = await self.references.get_or_fail(data.reference_id, "Эталон не найден")
        elif scenario.references:
            reference = scenario.references[0]

        payload = {
            "comment": data.comment,
            "scenario": {
                "title": scenario.title,
                "description": scenario.description,
                "briefing": scenario.briefing,
            },
            "reference": {
                "expected_fields": reference.expected_fields if reference else {},
                "expected_actions": reference.expected_actions if reference else [],
                "expected_text": reference.expected_text if reference else {},
            },
        }
        response = await self.ml.correct_scenario(payload)
        await self._log_ml(MLTaskKind.CORRECTION, "correct_scenario", payload, response, MLTaskStatus.OK)

        corrected = response.get("scenario") or {}
        scenario.description = corrected.get("description", scenario.description)
        scenario.briefing = corrected.get("briefing", scenario.briefing)
        scenario.origin = ScenarioOrigin.AI_CORRECTED
        scenario.status = ScenarioStatus.PENDING_REVIEW
        scenario.approved_at = None
        scenario.approved_by_id = None
        scenario.version += 1

        if reference is not None:
            new_ref = response.get("reference") or {}
            reference.expected_fields = new_ref.get("expected_fields", reference.expected_fields)
            reference.expected_actions = new_ref.get("expected_actions", reference.expected_actions)
            reference.expected_text = new_ref.get("expected_text", reference.expected_text)
            reference.teacher_comment = data.comment
            reference.approved_at = None
            reference.approved_by_id = None

        self.session.add(
            GenerationRequest(
                requested_by_id=actor.id,
                scenario_id=scenario.id,
                category_id=scenario.category_id,
                difficulty=scenario.difficulty,
                count=1,
                teacher_comment=data.comment,
                status=GenerationStatus.READY,
                ml_response={"model": response.get("model")},
            )
        )
        await self.session.flush()
        await self.audit.log(
            AuditAction.UPDATE,
            actor=actor,
            object_type="scenario",
            object_id=scenario.id,
            summary="Сценарий скорректирован по комментарию преподавателя",
            after={"comment": data.comment},
            request=request,
        )
        return await self.get(scenario_id)

    async def preview(self, scenario_id: uuid.UUID) -> dict[str, Any]:
        """Предпросмотр вопросов и правильных ответов для преподавателя (п.10 ТЗ)."""
        scenario = await self.get(scenario_id)
        cards = await self.cards.list_all(IncidentCard.scenario_id == scenario.id)
        questions = (scenario.ml_payload or {}).get("questions", [])
        return {
            "scenario": scenario,
            "cards": [
                {
                    "id": str(card.id),
                    "card_no": card.card_no,
                    "title": card.title,
                    "payload": card.payload,
                    "expected_payload": card.expected_payload,
                    "status": card.status.value,
                }
                for card in cards
            ],
            "questions": questions,
        }

    async def check_grammar(self, text: str) -> dict[str, Any]:
        response = await self.ml.check_grammar({"text": text, "rules": {}})
        await self._log_ml(MLTaskKind.GRAMMAR, "check_grammar", {"length": len(text)}, response, MLTaskStatus.OK)
        return response

    # ------------------------------------------------------------- приватное
    def _ensure_editable(self, scenario: Scenario) -> None:
        if scenario.status == ScenarioStatus.ARCHIVED:
            raise BusinessRuleError("Архивный сценарий изменять нельзя")

    async def _materialize(
        self,
        item: dict[str, Any],
        data: GenerateScenariosRequest,
        actor: User,
        *,
        category_id: uuid.UUID | None,
        response: dict[str, Any],
    ) -> Scenario:
        scenario = Scenario(
            title=item.get("title") or "Сценарий без названия",
            description=item.get("description"),
            category_id=category_id,
            difficulty=data.difficulty,
            status=ScenarioStatus.PENDING_REVIEW,
            origin=ScenarioOrigin.AI_GENERATED,
            author_id=actor.id,
            briefing=item.get("briefing") or {},
            generation_prompt=data.prompt,
            ml_model=response.get("model"),
            ml_payload={"questions": item.get("questions") or [], "raw": item},
        )
        reference = item.get("reference") or {}
        scenario.references.append(
            ScenarioReference(
                expected_fields=reference.get("expected_fields") or {},
                expected_actions=reference.get("expected_actions") or [],
                expected_text=reference.get("expected_text") or {},
            )
        )
        self.session.add(scenario)
        await self.session.flush()
        return scenario

    async def _draft_card(self, scenario: Scenario, item: dict[str, Any]) -> IncidentCard:
        """Карточка создаётся сразу, но в статусе DRAFT — до утверждения эталона."""
        template = await self.templates.default_template()
        reference = item.get("reference") or {}
        expected = reference.get("expected_fields") or {}
        notification_list = await CardService(self.session).notification_list(
            scenario.category_id, expected
        )
        card = IncidentCard(
            card_no=await self.cards.next_card_no(),
            title=scenario.title,
            template_id=template.id if template else None,
            scenario_id=scenario.id,
            category_id=scenario.category_id,
            origin=CardOrigin.GENERATED,
            status=CardStatus.DRAFT,
            difficulty=scenario.difficulty,
            caller_profile=(item.get("briefing") or {}).get("caller") or {},
            payload={},
            expected_payload=expected,
            notification_list=notification_list,
            time_limit_seconds=scenario.time_limit_seconds,
        )
        self.session.add(card)
        await self.session.flush()
        if scenario.references:
            scenario.references[0].card_id = card.id
        return card

    async def _publish_cards(self, scenario: Scenario) -> None:
        """После утверждения эталона черновые карточки сценария становятся READY."""
        cards = await self.cards.list_all(
            IncidentCard.scenario_id == scenario.id, IncidentCard.status == CardStatus.DRAFT
        )
        for card in cards:
            card.status = CardStatus.READY
        await self.session.flush()

    async def _log_ml(
        self,
        kind: MLTaskKind,
        endpoint: str,
        request_payload: dict[str, Any],
        response_payload: dict[str, Any],
        status: MLTaskStatus,
        error: str | None = None,
        latency_ms: int | None = None,
    ) -> None:
        self.session.add(
            MLResult(
                kind=kind,
                endpoint=endpoint,
                status=status,
                request_payload=request_payload,
                response_payload=response_payload,
                model=response_payload.get("model"),
                version=response_payload.get("version"),
                latency_ms=latency_ms or response_payload.get("latency_ms"),
                error=error,
            )
        )
        await self.session.flush()


class MaterialService:
    """Методические материалы и передача их в базу знаний ML (п.3.3 ТЗ)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.materials = MaterialRepository(session)
        self.audit = AuditService(session)
        self.ml = get_ml_client()

    async def list_materials(
        self, params: PageParams, *, kind: MaterialKind | None = None
    ) -> tuple[Sequence[TrainingMaterial], int]:
        conditions = [TrainingMaterial.is_active.is_(True)]
        if kind:
            conditions.append(TrainingMaterial.kind == kind)
        return await self.materials.paginate(params, *conditions)

    async def register(
        self,
        *,
        title: str,
        kind: MaterialKind,
        file_path: str | None,
        mime_type: str | None,
        size_bytes: int | None,
        checksum: str | None,
        category_id: uuid.UUID | None,
        description: str | None,
        actor: User,
        request: Request | None = None,
    ) -> TrainingMaterial:
        material = await self.materials.create(
            title=title,
            kind=kind,
            file_path=file_path,
            mime_type=mime_type,
            size_bytes=size_bytes,
            checksum=checksum,
            category_id=category_id,
            description=description,
            uploaded_by_id=actor.id,
        )
        await self.audit.log(
            AuditAction.CREATE,
            actor=actor,
            object_type="training_material",
            object_id=material.id,
            summary=f"Загружен материал «{title}»",
            request=request,
        )
        return material

    async def send_to_knowledge_base(self, material_id: uuid.UUID) -> dict[str, Any]:
        material = await self.materials.get_or_fail(material_id, "Материал не найден")
        response = await self.ml.index_material(
            {
                "material_id": str(material.id),
                "title": material.title,
                "kind": material.kind.value,
                "path": material.file_path,
            }
        )
        if response.get("indexed"):
            material.indexed_by_ml = True
            material.indexed_at = utcnow()
            await self.session.flush()
        return response

    async def delete(self, material_id: uuid.UUID, actor: User, request: Request | None = None) -> None:
        material = await self.materials.get_or_fail(material_id, "Материал не найден")
        await self.materials.soft_delete(material)
        await self.audit.log(
            AuditAction.DELETE,
            actor=actor,
            object_type="training_material",
            object_id=material_id,
            summary=f"Материал «{material.title}» удалён из активных",
            request=request,
        )
