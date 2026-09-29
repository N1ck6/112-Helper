from __future__ import annotations

from httpx import AsyncClient


async def _start_lesson(
    client: AsyncClient, teacher_headers, student_id: str, **overrides
) -> str:
    payload = {
        "title": "Поток карточек в ДДС",
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


# --------------------------------------------------------------- рабочие места
async def test_workplace_is_occupied_on_join_and_shown_in_monitor(
    client: AsyncClient, teacher_headers, student_headers, student_id, categories
) -> None:
    """Обучающийся называет номер АРМ при входе, преподаватель видит его в мониторинге."""
    lesson_id = await _start_lesson(
        client, teacher_headers, student_id, category_ids=[categories["traffic_injured"]]
    )

    joined = await client.post(
        f"/api/v1/training/lessons/{lesson_id}/join",
        headers=student_headers,
        json={"workplace_number": "03"},
    )
    assert joined.status_code == 200, joined.text
    assert joined.json()["workplace"] == "03"

    monitor = await client.get(f"/api/v1/lessons/{lesson_id}/monitor", headers=teacher_headers)
    assert monitor.status_code == 200, monitor.text
    row = monitor.json()["rows"][0]
    assert row["workplace"] == "03", "Номер рабочего места обязан быть в мониторинге"


async def test_workplace_cannot_be_taken_twice(
    client: AsyncClient, student_headers, seeded
) -> None:
    """Одно место — один обучающийся, иначе задание «пятому месту» получат двое."""
    taken = await client.post("/api/v1/workplaces/07/occupy", headers=student_headers)
    assert taken.status_code == 200, taken.text

    other = await client.post(
        "/api/v1/auth/login", json={"username": "student2", "password": "Student#2026"}
    )
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    conflict = await client.post("/api/v1/workplaces/07/occupy", headers=other_headers)
    assert conflict.status_code == 422
    assert "занято" in conflict.json()["error"]["message"]

    #: Освобождённое место занимается снова — иначе класс «залипнет» после смены.
    await client.post("/api/v1/workplaces/release", headers=student_headers)
    retry = await client.post("/api/v1/workplaces/07/occupy", headers=other_headers)
    assert retry.status_code == 200, retry.text
    await client.post("/api/v1/workplaces/release", headers=other_headers)


async def test_class_map_shows_free_and_occupied_places(
    client: AsyncClient, teacher_headers
) -> None:
    """Карта класса — исходные данные экрана раздачи заданий."""
    response = await client.get("/api/v1/workplaces/class-map", headers=teacher_headers)
    assert response.status_code == 200, response.text
    rows = response.json()
    assert len(rows) >= 10, "В учебном классе заведены рабочие места"
    assert {"number", "student_id", "in_lesson"} <= set(rows[0])


# ------------------------------------------------------------ поток карточек
async def test_dds_receives_card_stream_with_parallel_timers(
    client: AsyncClient, teacher_headers, student_headers, student_id, categories
) -> None:
    """Карточки ДДС приходят потоком: таймеры ожидающих карточек тоже идут."""
    lesson_id = await _start_lesson(
        client, teacher_headers, student_id, category_ids=[categories["traffic_injured"]]
    )
    await client.post(f"/api/v1/training/lessons/{lesson_id}/join", headers=student_headers)

    issued = await client.post(
        f"/api/v1/training/lessons/{lesson_id}/next-card", headers=student_headers
    )
    assert issued.status_code == 200, issued.text

    listing = await client.get(
        f"/api/v1/training/lessons/{lesson_id}/incidents", headers=student_headers
    )
    assert listing.status_code == 200, listing.text
    body = listing.json()
    assert len(body["rows"]) > 1, "В режиме ДДС карточки приходят потоком, а не по одной"

    #: У каждой строки свой обратный отсчёт — оба норматива видны одновременно.
    for row in body["rows"]:
        assert row["response_seconds_left"] is not None, "30 секунд на первичный статус"
        assert row["work_seconds_left"] is not None, "3 минуты на отработку карточки"

    #: Первой в списке идёт самая старая карточка: она горит раньше остальных.
    issued_order = [row["issued_at"] for row in body["rows"]]
    assert issued_order == sorted(issued_order)


async def test_operator_112_gets_one_card_at_a_time(
    client: AsyncClient, teacher_headers, student_headers, student_id, categories
) -> None:
    """У оператора 112 вызовы приходят по одному — следующий после сохранения."""
    lesson_id = await _start_lesson(
        client,
        teacher_headers,
        student_id,
        mode="card_fill",
        category_ids=[categories["fire_apartment"]],
    )
    await client.post(f"/api/v1/training/lessons/{lesson_id}/join", headers=student_headers)
    await client.post(f"/api/v1/training/lessons/{lesson_id}/next-card", headers=student_headers)

    listing = await client.get(
        f"/api/v1/training/lessons/{lesson_id}/incidents", headers=student_headers
    )
    assert listing.status_code == 200, listing.text
    assert listing.json()["stream_window"] == 1
    assert len(listing.json()["rows"]) == 1, "В режиме 112 карточка всегда одна"


async def test_work_deadline_is_three_minutes_by_default(
    client: AsyncClient, teacher_headers, student_headers, student_id, categories
) -> None:
    """Норматив отработки карточки — 3 минуты, и он отдельный от 30 секунд."""
    lesson_id = await _start_lesson(
        client, teacher_headers, student_id, category_ids=[categories["medical"]]
    )
    await client.post(f"/api/v1/training/lessons/{lesson_id}/join", headers=student_headers)
    issued = await client.post(
        f"/api/v1/training/lessons/{lesson_id}/next-card", headers=student_headers
    )
    body = issued.json()

    assert body["attempt"]["norm_seconds"] == 30, "Первичный статус — 30 секунд"
    assert 150 < body["work_seconds_left"] <= 180, (
        f"На отработку карточки даётся 3 минуты, получено {body['work_seconds_left']}"
    )
    assert body["response_seconds_left"] <= 30


async def test_opening_card_is_recorded(
    client: AsyncClient, teacher_headers, student_headers, student_id, categories
) -> None:
    """Открытие строки фиксируется, но норматив от этого не сдвигается."""
    lesson_id = await _start_lesson(
        client, teacher_headers, student_id, category_ids=[categories["utilities_water"]]
    )
    await client.post(f"/api/v1/training/lessons/{lesson_id}/join", headers=student_headers)
    issued = await client.post(
        f"/api/v1/training/lessons/{lesson_id}/next-card", headers=student_headers
    )
    attempt = issued.json()["attempt"]
    assert attempt["opened_at"] is None

    opened = await client.post(
        f"/api/v1/training/attempts/{attempt['id']}/open", headers=student_headers
    )
    assert opened.status_code == 200, opened.text
    assert opened.json()["opened_at"] is not None
    assert opened.json()["response_deadline_at"] == attempt["response_deadline_at"], (
        "Норматив 30 секунд идёт от поступления карточки, а не от её открытия"
    )


# ---------------------------------------------------------------- отработки
async def test_processing_requires_who_answered_and_what_was_said(
    client: AsyncClient, teacher_headers, student_headers, student_id, categories
) -> None:
    """Строка отработки без ФИО принявшего или без сути сообщения недействительна."""
    lesson_id = await _start_lesson(
        client, teacher_headers, student_id, category_ids=[categories["fire_apartment"]]
    )
    await client.post(f"/api/v1/training/lessons/{lesson_id}/join", headers=student_headers)
    issued = await client.post(
        f"/api/v1/training/lessons/{lesson_id}/next-card", headers=student_headers
    )
    attempt_id = issued.json()["attempt"]["id"]

    no_name = await client.post(
        f"/api/v1/training/attempts/{attempt_id}/processings",
        headers=student_headers,
        json={"kind": "supervisor", "summary": "Доложено о пожаре", "service_code": "101"},
    )
    assert no_name.status_code == 422
    assert "принял" in no_name.json()["error"]["message"]

    registered = await client.post(
        f"/api/v1/training/attempts/{attempt_id}/processings",
        headers=student_headers,
        json={
            "kind": "supervisor",
            "service_code": "101",
            "answered_by": "Дежурный Соколов А.П.",
            "summary": "Передан адрес, есть заблокированные, направлены два расчёта",
        },
    )
    assert registered.status_code == 201, registered.text
    entry = registered.json()
    assert entry["sequence_no"] == 1
    assert entry["offset_ms"] is not None, "Время отработки считается от выдачи карточки"
    assert entry["phone"], "Телефон подставляется из справочника ДДС"

    listed = await client.get(
        f"/api/v1/training/attempts/{attempt_id}/processings", headers=student_headers
    )
    assert listed.status_code == 200
    assert len(listed.json()) == 1


async def test_processing_of_finished_call_is_recorded_once(
    client: AsyncClient, teacher_headers, student_headers, student_id, categories
) -> None:
    """Звонок с панели «Телефон» уже состоялся: отработка без повторного вызова, одна на звонок."""
    lesson_id = await _start_lesson(
        client, teacher_headers, student_id, category_ids=[categories["fire_apartment"]]
    )
    await client.post(f"/api/v1/training/lessons/{lesson_id}/join", headers=student_headers)
    issued = await client.post(
        f"/api/v1/training/lessons/{lesson_id}/next-card", headers=student_headers
    )
    attempt_id = issued.json()["attempt"]["id"]
    url = f"/api/v1/training/attempts/{attempt_id}/processings"
    body = {
        "kind": "service",
        "service_name": "Служба 101 (МЧС)",
        "phone": "2101",
        "answered_by": "Старший диспетчер ЦУКС Петров Андрей",
        "summary": "Пожар в квартире, улица Тверская, дом 12",
        "duration_ms": 24000,
        "sip_call_id": "6b7a05a9b1304890baec35e104c99e75",
        "recording_url": "http://localhost:8090/6b7a05a9b1304890baec35e104c99e75.wav",
    }
    first = await client.post(url, headers=student_headers, json=body)
    assert first.status_code == 201, first.text
    assert first.json()["meta"]["recording_url"].endswith(".wav")
    again = await client.post(url, headers=student_headers, json=body)
    assert again.json()["id"] == first.json()["id"], "Второе сообщение о том же звонке не дублирует строку"

    failed = await client.post(url, headers=student_headers, json={
        "kind": "service", "service_name": "Служба 102 (полиция)", "phone": "2102",
        "summary": "Не дозвонились: трубку не сняли", "sip_call_id": "web-1", "outcome": "failed",
    })
    assert failed.status_code == 201, "Недозвон записывается без ФИО принявшего"
    assert failed.json()["meta"]["outcome"] == "failed"

    listed = await client.get(url, headers=student_headers)
    assert [p["sequence_no"] for p in listed.json()] == [1, 2]

    mine = await client.get(f"/api/v1/training/lessons/{lesson_id}/my-attempts", headers=student_headers)
    assert mine.status_code == 200, mine.text
    assert attempt_id in [row["attempt_id"] for row in mine.json()], "Своя карточка видна после перезагрузки АРМ"


async def test_contacts_come_from_notification_list(
    client: AsyncClient, teacher_headers, student_headers, student_id, categories
) -> None:
    """Звонить можно тем, кому ушла карточка; своей службе диспетчер не звонит."""
    lesson_id = await _start_lesson(
        client, teacher_headers, student_id, category_ids=[categories["traffic_injured"]]
    )
    await client.post(f"/api/v1/training/lessons/{lesson_id}/join", headers=student_headers)
    issued = await client.post(
        f"/api/v1/training/lessons/{lesson_id}/next-card", headers=student_headers
    )
    attempt = issued.json()["attempt"]

    contacts = await client.get(
        f"/api/v1/training/attempts/{attempt['id']}/contacts", headers=student_headers
    )
    assert contacts.status_code == 200, contacts.text
    codes = [item["service_code"] for item in contacts.json()]
    assert codes, "Список оповещения карточки даёт кому звонить"
    assert attempt["service_code"] not in codes, "Себе диспетчер не звонит"


# ------------------------------------------- дефекты, найденные при ревью
async def test_missed_primary_status_does_not_take_the_card_away(
    client: AsyncClient, teacher_headers, student_headers, student_id, categories
) -> None:
    import asyncio

    from app.db.session import SessionFactory
    from app.services.training import TrainingService

    lesson_id = await _start_lesson(
        client,
        teacher_headers,
        student_id,
        category_ids=[categories["traffic_injured"]],
        time_limit_seconds=5,
        max_cards=2,
    )
    await client.post(f"/api/v1/training/lessons/{lesson_id}/join", headers=student_headers)
    issued = await client.post(
        f"/api/v1/training/lessons/{lesson_id}/next-card", headers=student_headers
    )
    attempt_id = issued.json()["attempt"]["id"]

    await asyncio.sleep(6)
    async with SessionFactory() as session:
        service = TrainingService(session)
        marked = await service.mark_late_primary_response()
        await service.expire_overdue()
        await session.commit()

    assert marked >= 1, "Просрочка первичного статуса должна фиксироваться"

    attempt = await client.get(
        f"/api/v1/training/attempts/{attempt_id}", headers=student_headers
    )
    assert attempt.status_code == 200, attempt.text
    body = attempt.json()
    assert body["is_response_late"] is True
    assert body["lifecycle_status"] == "not_notified"
    assert body["status"] in ("issued", "in_progress"), "Карточка остаётся в работе"

    #: И её по-прежнему можно отработать — опоздание не снимает обязанности.
    accepted = await client.post(
        f"/api/v1/training/attempts/{attempt_id}/response-status",
        headers=student_headers,
        json={"status": "accepted", "work_order_no": "Н-2048"},
    )
    assert accepted.status_code == 201, accepted.text


async def test_stream_does_not_repeat_the_same_card(
    client: AsyncClient, teacher_headers, student_headers, student_id, categories
) -> None:
    lesson_id = await _start_lesson(
        client,
        teacher_headers,
        student_id,
        category_ids=[categories["traffic_injured"], categories["medical"]],
        max_cards=3,
    )
    await client.post(f"/api/v1/training/lessons/{lesson_id}/join", headers=student_headers)
    await client.post(f"/api/v1/training/lessons/{lesson_id}/next-card", headers=student_headers)

    listing = await client.get(
        f"/api/v1/training/lessons/{lesson_id}/incidents", headers=student_headers
    )
    card_numbers = [row["card_no"] for row in listing.json()["rows"]]
    assert len(card_numbers) == len(set(card_numbers)), (
        f"Карточки в потоке повторяются: {card_numbers}"
    )


async def test_repeated_next_card_does_not_overflow_the_window(
    client: AsyncClient, teacher_headers, student_headers, student_id, categories
) -> None:
    """Повторные запросы карточки не выдают сверх окна потока."""
    lesson_id = await _start_lesson(
        client, teacher_headers, student_id, category_ids=[categories["medical"]], max_cards=5
    )
    await client.post(f"/api/v1/training/lessons/{lesson_id}/join", headers=student_headers)
    for _ in range(4):
        await client.post(
            f"/api/v1/training/lessons/{lesson_id}/next-card", headers=student_headers
        )

    listing = await client.get(
        f"/api/v1/training/lessons/{lesson_id}/incidents", headers=student_headers
    )
    body = listing.json()
    assert len(body["rows"]) == body["stream_window"], (
        "Окно потока не должно переполняться повторными запросами"
    )


async def test_workplace_is_released_when_lesson_finishes(
    client: AsyncClient, teacher_headers, student_headers, student_id, categories
) -> None:
    """После занятия место свободно — иначе следующая смена не войдёт."""
    lesson_id = await _start_lesson(
        client, teacher_headers, student_id, category_ids=[categories["medical"]]
    )
    joined = await client.post(
        f"/api/v1/training/lessons/{lesson_id}/join",
        headers=student_headers,
        json={"workplace_number": "09"},
    )
    assert joined.json()["workplace"] == "09"

    finished = await client.post(
        f"/api/v1/lessons/{lesson_id}/finish",
        headers=teacher_headers,
        json={"reason": "Занятие окончено"},
    )
    assert finished.status_code == 200, finished.text

    #: Место должно освободиться — проверяем тем, что его занимает другой.
    other = await client.post(
        "/api/v1/auth/login", json={"username": "student2", "password": "Student#2026"}
    )
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    taken = await client.post("/api/v1/workplaces/09/occupy", headers=other_headers)
    assert taken.status_code == 200, taken.text
    await client.post("/api/v1/workplaces/release", headers=other_headers)


async def test_completed_dds_card_is_not_marked_overtime(
    client: AsyncClient, teacher_headers, student_headers, student_id, categories
) -> None:
    lesson_id = await _start_lesson(
        client, teacher_headers, student_id, category_ids=[categories["utilities_water"]]
    )
    await client.post(f"/api/v1/training/lessons/{lesson_id}/join", headers=student_headers)
    issued = await client.post(
        f"/api/v1/training/lessons/{lesson_id}/next-card", headers=student_headers
    )
    attempt_id = issued.json()["attempt"]["id"]

    for step in (
        {"status": "accepted", "work_order_no": "Н-77"},
        {"status": "response_started", "comment": "Бригада направлена"},
        {"status": "arrived", "comment": "Бригада на месте"},
        {"status": "work_in_progress", "comment": "Идут работы"},
        {"status": "work_completed", "comment": "Работы завершены"},
    ):
        response = await client.post(
            f"/api/v1/training/attempts/{attempt_id}/response-status",
            headers=student_headers,
            json=step,
        )
        assert response.status_code == 201, response.text

    attempt = (
        await client.get(f"/api/v1/training/attempts/{attempt_id}", headers=student_headers)
    ).json()
    assert attempt["is_overtime"] is False, (
        f"Отработка заняла {attempt['duration_ms']} мс при нормативе 3 минуты"
    )
    assert attempt["time_delta_seconds"] < 0


async def test_applicant_is_reachable_in_dds_mode(
    client: AsyncClient, teacher_headers, student_headers, student_id, categories
) -> None:
    """Диспетчер ДДС может позвонить заявителю: номер берётся из карточки."""
    lesson_id = await _start_lesson(
        client, teacher_headers, student_id, category_ids=[categories["fire_apartment"]]
    )
    await client.post(f"/api/v1/training/lessons/{lesson_id}/join", headers=student_headers)
    issued = await client.post(
        f"/api/v1/training/lessons/{lesson_id}/next-card", headers=student_headers
    )
    attempt_id = issued.json()["attempt"]["id"]

    contacts = await client.get(
        f"/api/v1/training/attempts/{attempt_id}/contacts", headers=student_headers
    )
    assert contacts.status_code == 200, contacts.text
    applicants = [item for item in contacts.json() if item["kind"] == "applicant"]
    assert applicants, "Звонок заявителю — один из четырёх сценариев отработки"
    assert applicants[0]["phone"], "Номер заявителя есть в карточке"


# --------------------------------- раздача заданий и карточки обучающихся
async def test_teacher_assigns_cards_by_workplace_number(
    client: AsyncClient, teacher_headers, student_headers, student_id, categories
) -> None:
    lesson_id = await _start_lesson(
        client, teacher_headers, student_id, category_ids=[categories["medical"]]
    )
    joined = await client.post(
        f"/api/v1/training/lessons/{lesson_id}/join",
        headers=student_headers,
        json={"workplace_number": "02"},
    )
    assert joined.json()["workplace"] == "02"

    #: Берём конкретную карточку из пула — её и назначим.
    pool = await client.get(
        "/api/v1/cards",
        headers=teacher_headers,
        params={"category_id": categories["fire_apartment"], "size": 5},
    )
    assert pool.status_code == 200, pool.text
    target = pool.json()["items"][0]

    assigned = await client.post(
        "/api/v1/workplaces/assign",
        headers=teacher_headers,
        json={"lesson_id": lesson_id, "assignments": {"02": target["id"]}},
    )
    assert assigned.status_code == 200, assigned.text
    body = assigned.json()
    assert len(body["assigned"]) == 1
    assert body["assigned"][0]["workplace"] == "02"
    assert not body["skipped"]

    issued = await client.post(
        f"/api/v1/training/lessons/{lesson_id}/next-card", headers=student_headers
    )
    assert issued.status_code == 200, issued.text
    assert issued.json()["card"]["id"] == target["id"], (
        "Назначенная карточка должна прийти раньше случайных"
    )


async def test_assignment_to_empty_workplace_is_reported_not_silent(
    client: AsyncClient, teacher_headers, student_id, categories
) -> None:
    """Место, за которым никто не работает, попадает в skipped с причиной."""
    lesson_id = await _start_lesson(
        client, teacher_headers, student_id, category_ids=[categories["medical"]]
    )
    pool = await client.get("/api/v1/cards", headers=teacher_headers, params={"size": 1})
    card_id = pool.json()["items"][0]["id"]

    response = await client.post(
        "/api/v1/workplaces/assign",
        headers=teacher_headers,
        json={"lesson_id": lesson_id, "assignments": {"10": card_id, "99": card_id}},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert not body["assigned"]
    reasons = {item["workplace"]: item["reason"] for item in body["skipped"]}
    assert "никто не работает" in reasons["10"]
    assert "не найдено" in reasons["99"]


async def test_passed_card_joins_the_pool_as_student_card(
    client: AsyncClient, teacher_headers, student_headers, student_id, categories
) -> None:
    before = await client.get(
        "/api/v1/cards", headers=teacher_headers, params={"origin": "student", "size": 1}
    )
    was = before.json()["total"]

    created = await client.post(
        "/api/v1/lessons",
        headers=teacher_headers,
        json={
            "title": "Карточка обучающегося пополняет пул",
            "mode": "card_fill",
            "student_ids": [student_id],
            "category_ids": [categories["traffic_injured"]],
            "card_source": "generated",
            "time_limit_seconds": 120,
            "max_cards": 1,
        },
    )
    lesson_id = created.json()["id"]
    await client.post(f"/api/v1/lessons/{lesson_id}/start", headers=teacher_headers)
    await client.post(f"/api/v1/training/lessons/{lesson_id}/join", headers=student_headers)
    issued = await client.post(
        f"/api/v1/training/lessons/{lesson_id}/next-card", headers=student_headers
    )
    attempt_id = issued.json()["attempt"]["id"]
    card_id = issued.json()["card"]["id"]
    expected = (
        await client.get(f"/api/v1/cards/{card_id}", headers=teacher_headers)
    ).json()["expected_payload"]

    for action in ("call_accepted", "field_filled", "classified"):
        await client.post(
            f"/api/v1/training/attempts/{attempt_id}/actions",
            headers=student_headers,
            json={"action_type": action},
        )
    submitted = await client.post(
        f"/api/v1/training/attempts/{attempt_id}/submit",
        headers=student_headers,
        json={
            "payload": {
                **expected,
                "operator_message": "Сообщение принято, бригада направлена на место.",
            }
        },
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["passed"] is True, f"Оценка: {submitted.json()['score']}"

    after = await client.get(
        "/api/v1/cards", headers=teacher_headers, params={"origin": "student", "size": 5}
    )
    assert after.json()["total"] == was + 1, (
        "Зачтённая карточка должна пополнить пул как «сформированная обучающимся»"
    )
