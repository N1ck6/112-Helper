from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Body, Depends, status

from app.api.deps import CurrentUser, SessionDep, require
from app.core.permissions import Perm
from app.schemas.common import MessageResponse
from app.schemas.grading import EvaluationRead
from app.schemas.training import (
    ActionCreate,
    ActionRead,
    AttemptRead,
    AttemptWithCard,
    DraftSaveRequest,
    IncidentListResponse,
    JoinRequest,
    LessonRead,
    ParticipantRead,
    ProcessingContact,
    ProcessingCreate,
    ProcessingRead,
    ResponseStatusCreate,
    ResponseStatusOptions,
    ResponseStatusRead,
    ResponseStatusResult,
    ResumeRequest,
    SubmitRequest,
    SubmitResponse,
)
from app.services.processings import ProcessingService
from app.services.training import TrainingService

router = APIRouter(prefix="/training", tags=["АРМ-112: работа обучающегося"])


@router.post("/lessons/{lesson_id}/join", summary="Войти в занятие")
async def join_lesson(
    lesson_id: uuid.UUID,
    session: SessionDep,
    student=Depends(require(Perm.LESSONS_PARTICIPATE)),
    data_in: JoinRequest = Body(default_factory=JoinRequest),
) -> dict[str, Any]:
    data = await TrainingService(session).join(
        lesson_id, student, workplace_number=data_in.workplace_number
    )
    return {
        "lesson": LessonRead.model_validate(data["lesson"]).model_dump(mode="json"),
        "participant": ParticipantRead.model_validate(data["participant"]).model_dump(mode="json"),
        "active_attempt": (
            AttemptWithCard.model_validate(data["active_attempt"]).model_dump(mode="json")
            if data["active_attempt"]
            else None
        ),
        "resume_token": data["resume_token"],
        "workplace": data.get("workplace"),
    }


@router.post(
    "/lessons/{lesson_id}/next-card",
    response_model=AttemptWithCard,
    summary="Получить следующую карточку",
    description=(
        "Выдаёт случайную карточку из пула занятия, ставит дедлайн по нормативу и "
        "(в режиме заполнения) запрашивает у модуля телефонии имитацию входящего вызова. "
        "Повторный вызов при открытой карточке возвращает текущую, а не выдаёт новую."
    ),
)
async def next_card(
    lesson_id: uuid.UUID,
    session: SessionDep,
    student=Depends(require(Perm.LESSONS_PARTICIPATE)),
) -> AttemptWithCard:
    data = await TrainingService(session).issue_next_card(lesson_id, student)
    return AttemptWithCard.model_validate(data)


@router.post(
    "/lessons/{lesson_id}/heartbeat",
    response_model=MessageResponse,
    summary="Отметка активности и снимок состояния клиента",
)
async def heartbeat(
    lesson_id: uuid.UUID,
    session: SessionDep,
    student=Depends(require(Perm.LESSONS_PARTICIPATE)),
    state: dict[str, Any] = Body(default_factory=dict),
) -> MessageResponse:
    await TrainingService(session).heartbeat(lesson_id, student, state)
    return MessageResponse(detail="Состояние сохранено")


@router.post(
    "/attempts/{attempt_id}/dialogue",
    summary="Реплика заявителя для звонка в браузере",
    description=(
        "Разговор с виртуальным заявителем без софтфона. Тело: `turn`, `history` "
        "([{role: caller|operator, text}]), `operator_text`. Содержание карточки в ML "
        "подставляет сервер — эталон в браузер не попадает."
    ),
)
async def dialogue_turn(
    attempt_id: uuid.UUID,
    session: SessionDep,
    student=Depends(require(Perm.LESSONS_PARTICIPATE)),
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    return await TrainingService(session).dialogue_turn(attempt_id, data, student)


@router.get("/attempts/{attempt_id}", response_model=AttemptRead, summary="Данные попытки")
async def get_attempt(attempt_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> AttemptRead:
    attempt = await TrainingService(session).get_attempt(attempt_id, user)
    return AttemptRead.model_validate(attempt)


@router.put(
    "/attempts/{attempt_id}/draft",
    response_model=AttemptRead,
    summary="Промежуточное сохранение карточки",
)
async def save_draft(
    attempt_id: uuid.UUID,
    data: DraftSaveRequest,
    session: SessionDep,
    student=Depends(require(Perm.LESSONS_PARTICIPATE)),
) -> AttemptRead:
    attempt = await TrainingService(session).save_draft(attempt_id, data.payload, student)
    return AttemptRead.model_validate(attempt)


@router.post(
    "/attempts/{attempt_id}/actions",
    response_model=ActionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Зафиксировать действие оператора",
    description=(
        "Каждое действие (приём вызова, заполнение поля, классификация, передача в ДДС) "
        "сохраняется с отметкой времени — на этой последовательности строится оценка регламента."
    ),
)
async def record_action(
    attempt_id: uuid.UUID,
    data: ActionCreate,
    session: SessionDep,
    student=Depends(require(Perm.LESSONS_PARTICIPATE)),
) -> ActionRead:
    action = await TrainingService(session).record_action(attempt_id, data, student)
    return ActionRead.model_validate(action)


@router.get(
    "/attempts/{attempt_id}/response-options",
    response_model=ResponseStatusOptions,
    summary="Доступные статусы реагирования",
    description=(
        "Возвращает статусы, в которые можно перейти из текущего, признак обязательного "
        "комментария и остаток времени до норматива 30 секунд. Frontend строит по этому "
        "ответу выпадающий список, как в ПОВ-112."
    ),
)
async def response_options(
    attempt_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
) -> ResponseStatusOptions:
    data = await TrainingService(session).response_options(attempt_id, user)
    return ResponseStatusOptions.model_validate(data)


@router.post(
    "/attempts/{attempt_id}/response-status",
    response_model=ResponseStatusResult,
    status_code=status.HTTP_201_CREATED,
    summary="Проставить статус реагирования (АРМ-112)",
    description=(
        "Основное действие диспетчера ДДС в режиме «действия с карточками». "
        "Переходы строго последовательные: Получена службой → Принята / Не принята → "
        "Начало реагирования → Прибытие → Проведение работ → Работы завершены / Отказ. "
        "Для «Не принята» и «Отказа от выполнения работ» комментарий обязателен. "
        "Первичный статус должен быть проставлен за 30 секунд после направления карточки "
        "в службу, иначе карточка уходит в состояние «Не оповещено». "
        "«Работы завершены» и «Отказ» закрывают карточку и запускают оценку."
    ),
)
async def set_response_status(
    attempt_id: uuid.UUID,
    data: ResponseStatusCreate,
    session: SessionDep,
    student=Depends(require(Perm.LESSONS_PARTICIPATE)),
) -> ResponseStatusResult:
    result = await TrainingService(session).set_response_status(attempt_id, data, student)
    evaluation = result["evaluation"]
    evaluation_read = EvaluationRead.model_validate(evaluation) if evaluation else None
    return ResponseStatusResult(
        entry=ResponseStatusRead.model_validate(result["entry"]),
        attempt=AttemptRead.model_validate(result["attempt"]),
        card_closed=bool(result["card_closed"]),
        evaluation_id=evaluation_read.id if evaluation_read else None,
        score=evaluation_read.score if evaluation_read else None,
        passed=evaluation_read.passed if evaluation_read else None,
        errors=(
            [error.model_dump(mode="json") for error in evaluation_read.errors] if evaluation_read else []
        ),
        next_attempt=(
            AttemptWithCard.model_validate(result["next_attempt"]) if result["next_attempt"] else None
        ),
    )


@router.post(
    "/attempts/{attempt_id}/submit",
    response_model=SubmitResponse,
    summary="Сдать карточку и получить оценку",
)
async def submit_attempt(
    attempt_id: uuid.UUID,
    data: SubmitRequest,
    session: SessionDep,
    student=Depends(require(Perm.LESSONS_PARTICIPATE)),
) -> SubmitResponse:
    result = await TrainingService(session).submit(attempt_id, data, student)
    evaluation = result["evaluation"]
    evaluation_read = EvaluationRead.model_validate(evaluation) if evaluation else None
    return SubmitResponse(
        attempt=AttemptRead.model_validate(result["attempt"]),
        evaluation_id=evaluation_read.id if evaluation_read else None,
        score=evaluation_read.score if evaluation_read else None,
        passed=evaluation_read.passed if evaluation_read else None,
        errors=(
            [error.model_dump(mode="json") for error in evaluation_read.errors] if evaluation_read else []
        ),
        next_attempt=(
            AttemptWithCard.model_validate(result["next_attempt"]) if result["next_attempt"] else None
        ),
        lesson_finished=bool(result["lesson_finished"]),
    )


@router.post("/attempts/{attempt_id}/skip", response_model=AttemptRead, summary="Пропустить карточку")
async def skip_attempt(
    attempt_id: uuid.UUID,
    session: SessionDep,
    student=Depends(require(Perm.LESSONS_PARTICIPATE)),
) -> AttemptRead:
    attempt = await TrainingService(session).skip(attempt_id, student)
    return AttemptRead.model_validate(attempt)


@router.post(
    "/resume",
    summary="Восстановить учебную сессию после обрыва связи",
    description=(
        "Возвращает занятие, открытую карточку и сохранённый черновик. "
        "Поле `within_grace_period` показывает, укладывается ли пауза в норматив 30 секунд."
    ),
)
async def resume(
    data: ResumeRequest,
    session: SessionDep,
    student=Depends(require(Perm.LESSONS_PARTICIPATE)),
) -> dict[str, Any]:
    result = await TrainingService(session).resume(data.resume_token)
    return {
        "lesson": LessonRead.model_validate(result["lesson"]).model_dump(mode="json"),
        "active_attempt": (
            AttemptWithCard.model_validate(result["active_attempt"]).model_dump(mode="json")
            if result["active_attempt"]
            else None
        ),
        "restored_state": result["restored_state"],
    }


@router.get(
    "/lessons/{lesson_id}/incidents",
    response_model=IncidentListResponse,
    summary="Список происшествий: поток карточек с таймерами",
    description=(
        "Рабочий экран диспетчера ДДС. Карточки приходят потоком, и таймеры "
        "ожидающих карточек идут параллельно: по каждой строке видно, сколько "
        "осталось на первичный статус (30 секунд) и на отработку целиком (3 минуты). "
        "В режиме оператора 112 в списке всегда одна карточка: следующий вызов "
        "приходит только после сохранения текущей."
    ),
)
async def incident_list(
    lesson_id: uuid.UUID,
    session: SessionDep,
    student=Depends(require(Perm.LESSONS_PARTICIPATE)),
) -> IncidentListResponse:
    data = await TrainingService(session).incident_list(lesson_id, student)
    return IncidentListResponse.model_validate(data)


@router.post(
    "/attempts/{attempt_id}/open",
    response_model=AttemptRead,
    summary="Открыть карточку из списка происшествий",
    description=(
        "Отмечает, что диспетчер взял строку в работу. Норматив 30 секунд считается "
        "от поступления карточки, а не от открытия, поэтому отметка ничего не "
        "сдвигает — она показывает преподавателю, сколько обучающийся думал перед тем, "
        "как открыть карточку."
    ),
)
async def open_card(
    attempt_id: uuid.UUID,
    session: SessionDep,
    student=Depends(require(Perm.LESSONS_PARTICIPATE)),
) -> AttemptRead:
    attempt = await TrainingService(session).open_card(attempt_id, student)
    return AttemptRead.model_validate(attempt)


@router.get(
    "/attempts/{attempt_id}/contacts",
    response_model=list[ProcessingContact],
    summary="Кому можно позвонить по карточке",
    description=(
        "Список оповещения карточки с телефонами: руководители служб, куда ушла "
        "карточка, и заявитель по номеру из карточки. Своя служба исключена — "
        "себе диспетчер не звонит. Это исходные данные для панели телефона."
    ),
)
async def processing_contacts(
    attempt_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> list[ProcessingContact]:
    contacts = await ProcessingService(session).contacts_for(attempt_id, user)
    return [ProcessingContact.model_validate(item) for item in contacts]


@router.get(
    "/attempts/{attempt_id}/processings",
    response_model=list[ProcessingRead],
    summary="Строки отработки по карточке",
)
async def list_processings(
    attempt_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> list[ProcessingRead]:
    items = await ProcessingService(session).for_attempt(attempt_id, user)
    return [ProcessingRead.model_validate(item) for item in items]


@router.post(
    "/attempts/{attempt_id}/processings",
    response_model=ProcessingRead,
    status_code=status.HTTP_201_CREATED,
    summary="Зафиксировать отработку (звонок по карточке)",
    description=(
        "Строка отработки по памятке АРМ-112: куда звонили, по какому номеру, кто "
        "принял сообщение и что передали. Backend одновременно просит модуль "
        "телефонии поднять вызов и привязывает запись разговора к карточке, "
        "рабочему месту и сессии. Если телефония недоступна, отработка всё равно "
        "фиксируется: работа обучающегося не теряется из-за чужого модуля."
    ),
)
async def register_processing(
    attempt_id: uuid.UUID,
    data: ProcessingCreate,
    session: SessionDep,
    student=Depends(require(Perm.LESSONS_PARTICIPATE)),
) -> ProcessingRead:
    processing = await ProcessingService(session).register(
        attempt_id, data.model_dump(), student
    )
    return ProcessingRead.model_validate(processing)
