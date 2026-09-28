from __future__ import annotations

from httpx import AsyncClient


async def _start_action_lesson(client: AsyncClient, teacher_headers, student_id: str, **overrides) -> str:
    payload = {
        "title": "Практическое занятие: действия с карточками",
        "mode": "card_action",
        "student_ids": [student_id],
        "card_source": "generated",
        "time_limit_seconds": 30,
        "max_cards": 3,
        **overrides,
    }
    created = await client.post("/api/v1/lessons", headers=teacher_headers, json=payload)
    assert created.status_code == 201, created.text
    lesson_id = created.json()["id"]
    started = await client.post(f"/api/v1/lessons/{lesson_id}/start", headers=teacher_headers)
    assert started.status_code == 200, started.text
    return lesson_id


async def _issue_card(client: AsyncClient, student_headers, lesson_id: str) -> dict:
    await client.post(f"/api/v1/training/lessons/{lesson_id}/join", headers=student_headers)
    issued = await client.post(
        f"/api/v1/training/lessons/{lesson_id}/next-card", headers=student_headers
    )
    assert issued.status_code == 200, issued.text
    return issued.json()


async def test_response_block_is_opened_on_issue(
    client: AsyncClient, teacher_headers, student_headers, student_id, categories
) -> None:
    """При выдаче карточки система сама ставит «Добавлена» и «Получена службой»."""
    lesson_id = await _start_action_lesson(
        client, teacher_headers, student_id, category_ids=[categories["traffic_injured"]]
    )
    view = await _issue_card(client, student_headers, lesson_id)

    attempt = view["attempt"]
    assert attempt["response_deadline_at"], "Должен быть установлен срок первичного статуса"
    assert attempt["lifecycle_status"] == "registered"
    assert attempt["last_response_status"] == "received"
    assert view["response_seconds_left"] is not None
    assert view["response_seconds_left"] <= 30

    system_statuses = [s["status"] for s in attempt["response_statuses"]]
    assert system_statuses == ["added", "received"]
    assert all(s["set_by_system"] for s in attempt["response_statuses"])

    options = await client.get(
        f"/api/v1/training/attempts/{attempt['id']}/response-options", headers=student_headers
    )
    assert options.status_code == 200, options.text
    available = {item["status"] for item in options.json()["available"]}
    assert available == {"accepted", "not_accepted"}
    assert options.json()["primary_status_set"] is False


async def test_sequence_is_enforced(
    client: AsyncClient, teacher_headers, student_headers, student_id, categories
) -> None:
    """Нельзя перескочить через приём карточки и вернуться из «Принята» назад."""
    lesson_id = await _start_action_lesson(
        client, teacher_headers, student_id, category_ids=[categories["traffic_injured"]]
    )
    attempt_id = (await _issue_card(client, student_headers, lesson_id))["attempt"]["id"]

    skipped = await client.post(
        f"/api/v1/training/attempts/{attempt_id}/response-status",
        headers=student_headers,
        json={"status": "arrived"},
    )
    assert skipped.status_code == 422
    assert skipped.json()["error"]["code"] == "response_status_transition_denied"

    system_status = await client.post(
        f"/api/v1/training/attempts/{attempt_id}/response-status",
        headers=student_headers,
        json={"status": "received"},
    )
    assert system_status.status_code == 422, "Технические статусы ставит только система"

    accepted = await client.post(
        f"/api/v1/training/attempts/{attempt_id}/response-status",
        headers=student_headers,
        json={"status": "accepted"},
    )
    assert accepted.status_code == 201, accepted.text
    body = accepted.json()
    assert body["entry"]["is_primary"] is True
    assert body["entry"]["is_late"] is False
    assert body["entry"]["title"] == "Принята"
    assert body["attempt"]["first_response_status"] == "accepted"
    assert body["attempt"]["first_response_seconds"] is not None
    assert body["attempt"]["first_response_seconds"] < 30, "Норматив должен быть соблюдён"
    assert body["card_closed"] is False

    back = await client.post(
        f"/api/v1/training/attempts/{attempt_id}/response-status",
        headers=student_headers,
        json={"status": "not_accepted", "comment": "передумал"},
    )
    assert back.status_code == 422, "Из «Принята» нельзя вернуться в «Не принята»"


async def test_comment_is_required_for_refusal(
    client: AsyncClient, teacher_headers, student_headers, student_id, categories
) -> None:
    """«Не принята» без комментария — нарушение, система его не пропускает."""
    lesson_id = await _start_action_lesson(
        client, teacher_headers, student_id, category_ids=[categories["traffic_injured"]]
    )
    attempt_id = (await _issue_card(client, student_headers, lesson_id))["attempt"]["id"]

    without_comment = await client.post(
        f"/api/v1/training/attempts/{attempt_id}/response-status",
        headers=student_headers,
        json={"status": "not_accepted"},
    )
    assert without_comment.status_code == 422
    assert without_comment.json()["error"]["code"] == "response_comment_required"

    with_comment = await client.post(
        f"/api/v1/training/attempts/{attempt_id}/response-status",
        headers=student_headers,
        json={
            "status": "not_accepted",
            "comment": "Не обслуживаем территорию, информация передана в ДДС района",
        },
    )
    assert with_comment.status_code == 201, with_comment.text
    assert with_comment.json()["attempt"]["lifecycle_status"] == "refusal"

    #: После «Не принята» единственный доступный вариант — «Принята».
    options = await client.get(
        f"/api/v1/training/attempts/{attempt_id}/response-options", headers=student_headers
    )
    assert [item["status"] for item in options.json()["available"]] == ["accepted"]


async def test_full_response_chain_closes_card_and_scores(
    client: AsyncClient, teacher_headers, student_headers, student_id, categories
) -> None:
    """Полная цепочка реагирования: приём → ход работ → завершение и оценка."""
    lesson_id = await _start_action_lesson(
        client, teacher_headers, student_id, category_ids=[categories["traffic_injured"]]
    )
    attempt_id = (await _issue_card(client, student_headers, lesson_id))["attempt"]["id"]

    chain = [
        {"status": "accepted", "work_order_no": "Н-1024"},
        {"status": "response_started", "comment": "Направлена аварийная бригада"},
        {"status": "arrived", "comment": "Бригада на месте"},
        {"status": "work_in_progress", "comment": "Ведутся работы"},
    ]
    for step in chain:
        response = await client.post(
            f"/api/v1/training/attempts/{attempt_id}/response-status",
            headers=student_headers,
            json=step,
        )
        assert response.status_code == 201, response.text
        assert response.json()["card_closed"] is False

    final = await client.post(
        f"/api/v1/training/attempts/{attempt_id}/response-status",
        headers=student_headers,
        json={"status": "work_completed", "comment": "Работы завершены, утечка устранена"},
    )
    assert final.status_code == 201, final.text
    result = final.json()

    assert result["card_closed"] is True, "«Работы завершены» закрывают карточку"
    assert result["attempt"]["lifecycle_status"] == "completed"
    assert result["evaluation_id"], "После закрытия карточки формируется оценка"
    assert result["score"] is not None
    assert result["passed"] is True, f"Эталонная цепочка должна быть зачтена: {result['errors']}"
    assert result["next_attempt"] is not None, "Занятие продолжается следующей карточкой"

    #: Закрытая карточка больше не принимает статусы.
    closed = await client.post(
        f"/api/v1/training/attempts/{attempt_id}/response-status",
        headers=student_headers,
        json={"status": "work_refused", "comment": "поздно"},
    )
    assert closed.status_code == 422


async def test_missing_progress_statuses_are_reported(
    client: AsyncClient, teacher_headers, student_headers, student_id, categories
) -> None:
    """Пропуск статусов хода работ фиксируется как замечание (нарушение №6 памятки)."""
    lesson_id = await _start_action_lesson(
        client, teacher_headers, student_id, category_ids=[categories["traffic_injured"]]
    )
    attempt_id = (await _issue_card(client, student_headers, lesson_id))["attempt"]["id"]

    await client.post(
        f"/api/v1/training/attempts/{attempt_id}/response-status",
        headers=student_headers,
        json={"status": "accepted"},
    )
    final = await client.post(
        f"/api/v1/training/attempts/{attempt_id}/response-status",
        headers=student_headers,
        json={"status": "work_completed", "comment": "Работы завершены"},
    )
    assert final.status_code == 201, final.text
    codes = {error["code"] for error in final.json()["errors"]}
    assert "progress_statuses_missing" in codes


async def test_response_statuses_are_blocked_in_card_fill_mode(
    client: AsyncClient, teacher_headers, student_headers, student_id, categories
) -> None:
    """В режиме заполнения карточки обучающийся работает как специалист-112."""
    created = await client.post(
        "/api/v1/lessons",
        headers=teacher_headers,
        json={
            "title": "Занятие: заполнение карточек",
            "mode": "card_fill",
            "student_ids": [student_id],
            "max_cards": 1,
        },
    )
    lesson_id = created.json()["id"]
    await client.post(f"/api/v1/lessons/{lesson_id}/start", headers=teacher_headers)
    attempt_id = (await _issue_card(client, student_headers, lesson_id))["attempt"]["id"]

    response = await client.post(
        f"/api/v1/training/attempts/{attempt_id}/response-status",
        headers=student_headers,
        json={"status": "accepted"},
    )
    assert response.status_code == 422
    assert "действия с карточками" in response.json()["error"]["message"]


async def test_notification_list_defines_service_of_student(
    client: AsyncClient, teacher_headers, student_headers, student_id, categories
) -> None:
    """Список оповещения формируется по ЕКП, обучающийся работает за профильную службу."""
    lesson_id = await _start_action_lesson(
        client, teacher_headers, student_id, category_ids=[categories["traffic_injured"]]
    )
    view = await _issue_card(client, student_headers, lesson_id)
    attempt = view["attempt"]

    services = {item["code"] for item in attempt["notification_list"]}
    assert {"dps", "103", "101"} <= services
    assert attempt["service_code"] == "dps"

    options = await client.get(
        f"/api/v1/training/attempts/{attempt['id']}/response-options", headers=student_headers
    )
    body = options.json()
    assert body["is_primary_service"] is True
    assert body["service_name"].startswith("ДПС")
    assert body["comment_examples"], "Подсказки по формулировкам комментариев из памятки"

    foreign = await client.post(
        f"/api/v1/training/attempts/{attempt['id']}/response-status",
        headers=student_headers,
        json={"status": "accepted", "service_code": "moek"},
    )
    assert foreign.status_code == 422
    assert foreign.json()["error"]["code"] == "service_not_in_notification_list"


async def test_service_103_cannot_refuse(
    client: AsyncClient, teacher_headers, student_headers, student_id, categories
) -> None:
    """Служба 103 не проставляет «Не принята» — вместо неё «Работы завершены» (памятка)."""
    lesson_id = await _start_action_lesson(
        client, teacher_headers, student_id, category_ids=[categories["medical"]]
    )
    attempt = (await _issue_card(client, student_headers, lesson_id))["attempt"]
    assert attempt["service_code"] == "103"

    options = await client.get(
        f"/api/v1/training/attempts/{attempt['id']}/response-options", headers=student_headers
    )
    available = {item["status"] for item in options.json()["available"]}
    assert available == {"accepted"}, "«Не принята» для 103 недоступна"

    refused = await client.post(
        f"/api/v1/training/attempts/{attempt['id']}/response-status",
        headers=student_headers,
        json={"status": "not_accepted", "comment": "Не наш профиль, передано в 102"},
    )
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "response_status_not_allowed_for_service"


async def test_primary_service_refusal_is_a_violation(
    client: AsyncClient, teacher_headers, student_headers, student_id, categories
) -> None:
    """Отказ профильной службы от реагирования — нарушение из каталога памятки."""
    lesson_id = await _start_action_lesson(
        client, teacher_headers, student_id, category_ids=[categories["fire_apartment"]], max_cards=1
    )
    attempt_id = (await _issue_card(client, student_headers, lesson_id))["attempt"]["id"]

    accepted = await client.post(
        f"/api/v1/training/attempts/{attempt_id}/response-status",
        headers=student_headers,
        json={"status": "accepted"},
    )
    assert accepted.status_code == 201, accepted.text
    refused = await client.post(
        f"/api/v1/training/attempts/{attempt_id}/response-status",
        headers=student_headers,
        json={
            "status": "work_refused",
            "comment": "Отказ от выполнения работ, информация передана в диспетчерскую ЖКХ",
        },
    )
    assert refused.status_code == 201, refused.text
    codes = {error["code"] for error in refused.json()["errors"]}
    assert "primary_service_refused" in codes
    assert refused.json()["attempt"]["lifecycle_status"] == "refusal"
