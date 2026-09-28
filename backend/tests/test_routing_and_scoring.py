from __future__ import annotations

from httpx import AsyncClient


# ------------------------------------------------------------ маршрутизация
async def test_card_is_routed_to_district_and_its_okrug(
    client: AsyncClient, teacher_headers, categories
) -> None:
    """Пример заказчика: происшествие в Щукине уходит и в управу, и в округ."""
    response = await client.post(
        "/api/v1/services/routing/preview",
        headers=teacher_headers,
        json={
            "category_id": categories["fire_apartment"],
            "payload": {
                "address_region": "г. Москва",
                "address_area": "Щукино",
                "address_street": "улица Маршала Василевского",
                "address_house": "13",
                "has_victims": True,
            },
        },
    )
    assert response.status_code == 200, response.text
    services = response.json()["notification_list"]
    codes = {item["code"] for item in services}

    assert "101" in codes, "Пожар — профильная служба пожарно-спасательного гарнизона"
    assert "dds_shchukino" in codes, "ДДС района обслуживания по адресу происшествия"
    assert "dds_szao" in codes, "Округ подтягивается по подчинённости управы"
    assert "dds_uzao" not in codes, "Чужой округ в список попадать не должен"

    reasons = {item["code"]: item.get("reason") for item in services}
    assert "район" in (reasons["dds_shchukino"] or "")
    assert "подчинённость" in (reasons["dds_szao"] or "")


async def test_department_service_is_added_by_category(
    client: AsyncClient, teacher_headers, categories
) -> None:
    """Ведомственная ДДС привлекается по типу происшествия, а не по адресу."""
    response = await client.post(
        "/api/v1/services/routing/preview",
        headers=teacher_headers,
        json={
            "category_id": categories["fire_apartment"],
            "payload": {"address_district": "ЮЗАО", "address_area": "Академический"},
        },
    )
    assert response.status_code == 200, response.text
    codes = {item["code"] for item in response.json()["notification_list"]}
    assert "dds_education" in codes, "ДДС Департамента образования — по категории"
    assert "dds_akademichesky" in codes and "dds_uzao" in codes


async def test_unknown_area_does_not_pull_every_service(
    client: AsyncClient, teacher_headers, categories
) -> None:
    """Неизвестный район не должен собирать в список все ДДС города."""
    response = await client.post(
        "/api/v1/services/routing/preview",
        headers=teacher_headers,
        json={
            "category_id": categories["traffic_injured"],
            "payload": {"address_district": "ЗелАО", "address_area": "Матушкино"},
        },
    )
    assert response.status_code == 200, response.text
    codes = {item["code"] for item in response.json()["notification_list"]}
    assert not {"dds_shchukino", "dds_akademichesky"} & codes


async def test_service_directory_is_extensible(
    client: AsyncClient, teacher_headers, admin_headers
) -> None:
    """Новая ДДС добавляется записью в справочник — «универсальный алгоритм для всех»."""
    created = await client.post(
        "/api/v1/services",
        headers=teacher_headers,
        json={
            "code": "dds_test_area",
            "name": "ДДС управы тестового района",
            "level": "district",
            "okrug": "ЦАО",
            "area": "Тестовый",
            "phone_extension": "2999",
        },
    )
    assert created.status_code == 201, created.text

    duplicate = await client.post(
        "/api/v1/services",
        headers=teacher_headers,
        json={"code": "dds_test_area", "name": "Дубль", "level": "district"},
    )
    assert duplicate.status_code == 422

    listed = await client.get(
        "/api/v1/services", headers=teacher_headers, params={"level": "district"}
    )
    assert listed.status_code == 200
    assert any(item["code"] == "dds_test_area" for item in listed.json())

    removed = await client.delete("/api/v1/services/dds_test_area", headers=teacher_headers)
    assert removed.status_code == 200


# ------------------------------------------------------------------- оценка
async def test_address_typo_is_a_critical_error(
    client: AsyncClient, teacher_headers, student_headers, student_id, categories
) -> None:
    created = await client.post(
        "/api/v1/lessons",
        headers=teacher_headers,
        json={
            "title": "Проверка ошибок в адресе",
            "mode": "card_fill",
            "student_ids": [student_id],
            "category_ids": [categories["fire_apartment"]],
            "card_source": "generated",
            "time_limit_seconds": 60,
            "max_cards": 1,
        },
    )
    assert created.status_code == 201, created.text
    lesson_id = created.json()["id"]
    await client.post(f"/api/v1/lessons/{lesson_id}/start", headers=teacher_headers)
    await client.post(f"/api/v1/training/lessons/{lesson_id}/join", headers=student_headers)

    issued = await client.post(
        f"/api/v1/training/lessons/{lesson_id}/next-card", headers=student_headers
    )
    attempt_id = issued.json()["attempt"]["id"]
    card_id = issued.json()["card"]["id"]

    reference = await client.get(f"/api/v1/cards/{card_id}", headers=teacher_headers)
    expected = reference.json()["expected_payload"]

    #: Заполняем карточку по эталону, но с опечаткой в улице.
    payload = dict(expected)
    payload["address_street"] = str(expected.get("address_street", "улица")) + "ъ"
    submitted = await client.post(
        f"/api/v1/training/attempts/{attempt_id}/submit",
        headers=student_headers,
        json={"payload": payload},
    )
    assert submitted.status_code == 200, submitted.text
    errors = submitted.json()["errors"]

    address_errors = [item for item in errors if item.get("field_code") == "address_street"]
    assert address_errors, "Расхождение в адресе обязано попасть в замечания"
    assert address_errors[0]["severity"] == "critical", (
        "Ошибка в адресе — критическая: бригада уедет не туда"
    )
    assert submitted.json()["passed"] is False, "С критической ошибкой карточка не зачитывается"


async def test_score_weights_are_configurable(
    client: AsyncClient, teacher_headers, student_headers, student_id, categories
) -> None:
    """Веса критериев задаёт преподаватель: утверждённой методики у заказчика нет."""
    created = await client.post(
        "/api/v1/lessons",
        headers=teacher_headers,
        json={
            "title": "Занятие со своими весами оценки",
            "mode": "card_fill",
            "student_ids": [student_id],
            "category_ids": [categories["medical"]],
            "card_source": "generated",
            "time_limit_seconds": 60,
            "max_cards": 1,
            #: Преподаватель пишет «время 1, правильность 9» — доли считаем сами.
            "success_criteria": {"weights": {"accuracy": 9, "timing": 1, "grammar": 0, "procedure": 0}},
        },
    )
    assert created.status_code == 201, created.text
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

    submitted = await client.post(
        f"/api/v1/training/attempts/{attempt_id}/submit",
        headers=student_headers,
        json={"payload": expected},
    )
    assert submitted.status_code == 200, submitted.text

    evaluation = await client.get(
        f"/api/v1/evaluations/by-attempt/{attempt_id}", headers=teacher_headers
    )
    assert evaluation.status_code == 200, evaluation.text
    weights = evaluation.json()["details"]["weights"]
    assert abs(sum(weights.values()) - 1.0) < 0.001, "Веса приводятся к сумме 1.0"
    assert weights["accuracy"] == 0.9, "Правильность заполнения — 9 из 10"
    assert weights["grammar"] == 0.0


# ------------------------------------------------------- адаптивная сложность
async def test_adaptive_difficulty_follows_the_student(
    client: AsyncClient, teacher_headers, student_headers, student_id, categories
) -> None:
    """Высокий результат поднимает уровень заданий, как шахматный движок."""
    created = await client.post(
        "/api/v1/lessons",
        headers=teacher_headers,
        json={
            "title": "Занятие с адаптивной сложностью",
            "mode": "card_fill",
            "student_ids": [student_id],
            "category_ids": [categories["utilities_water"]],
            "card_source": "generated",
            "time_limit_seconds": 120,
            "max_cards": 2,
            "difficulty_weight": 4,
            "adaptive_difficulty": True,
        },
    )
    assert created.status_code == 201, created.text
    lesson = created.json()
    lesson_id = lesson["id"]
    assert lesson["difficulty_weight"] == 4
    assert lesson["difficulty"] == "medium", "Вес 4 соответствует среднему уровню"

    await client.post(f"/api/v1/lessons/{lesson_id}/start", headers=teacher_headers)
    await client.post(f"/api/v1/training/lessons/{lesson_id}/join", headers=student_headers)
    issued = await client.post(
        f"/api/v1/training/lessons/{lesson_id}/next-card", headers=student_headers
    )
    assert issued.status_code == 200, issued.text
    attempt_id = issued.json()["attempt"]["id"]
    assert issued.json()["attempt"]["difficulty_weight"] == 4

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
                "operator_message": "Сообщение принято, аварийная бригада направлена на место.",
            }
        },
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["score"] >= 85, (
        f"Карточка заполнена по эталону, получено {submitted.json()['score']}"
    )

    monitor = await client.get(f"/api/v1/lessons/{lesson_id}/monitor", headers=teacher_headers)
    lesson_state = await client.get(f"/api/v1/lessons/{lesson_id}", headers=teacher_headers)
    participant = lesson_state.json()["participants"][0]
    assert participant["difficulty_weight"] == 5, (
        "После высокого балла сложность поднимается на шаг"
    )
    assert monitor.status_code == 200


async def test_attestation_ignores_adaptive_difficulty(
    client: AsyncClient, teacher_headers, student_id, categories
) -> None:
    """В аттестации сложность не подстраивается: условия должны быть равными."""
    created = await client.post(
        "/api/v1/lessons",
        headers=teacher_headers,
        json={
            "title": "Аттестация с попыткой включить адаптивность",
            "mode": "card_fill",
            "purpose": "attestation",
            "student_ids": [student_id],
            "category_ids": [categories["medical"]],
            "card_source": "generated",
            "max_cards": 1,
            "adaptive_difficulty": True,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["adaptive_difficulty"] is False


async def test_partial_weights_do_not_zero_out_other_criteria(
    client: AsyncClient, teacher_headers, student_headers, student_id, categories
) -> None:
    created = await client.post(
        "/api/v1/lessons",
        headers=teacher_headers,
        json={
            "title": "Частично заданные веса",
            "mode": "card_fill",
            "student_ids": [student_id],
            "category_ids": [categories["traffic_injured"]],
            "card_source": "generated",
            "time_limit_seconds": 60,
            "max_cards": 1,
            "success_criteria": {"weights": {"correctness": 5, "время": 3}},
        },
    )
    assert created.status_code == 201, created.text
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
    await client.post(
        f"/api/v1/training/attempts/{attempt_id}/submit",
        headers=student_headers,
        json={"payload": expected},
    )

    evaluation = await client.get(
        f"/api/v1/evaluations/by-attempt/{attempt_id}", headers=teacher_headers
    )
    weights = evaluation.json()["details"]["weights"]
    assert abs(sum(weights.values()) - 1.0) < 0.001
    assert weights["accuracy"] > weights["timing"] > 0, "Заданные веса соблюдают пропорцию 5:3"
    assert weights["grammar"] > 0.05, "Неназванный критерий не должен обнуляться"
    assert weights["procedure"] > 0.05


async def test_empty_address_field_is_reported(
    client: AsyncClient, teacher_headers, student_headers, student_id, categories
) -> None:
    created = await client.post(
        "/api/v1/lessons",
        headers=teacher_headers,
        json={
            "title": "Неполный адрес",
            "mode": "card_fill",
            "student_ids": [student_id],
            "category_ids": [categories["fire_apartment"]],
            "card_source": "generated",
            "time_limit_seconds": 60,
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

    #: Оставляем незаполненным необязательное адресное поле.
    blank_field = next(
        (
            field
            for field in ("address_entrance", "address_floor", "address_area")
            if expected.get(field)
        ),
        None,
    )
    assert blank_field, "В эталоне должно быть хотя бы одно необязательное поле адреса"

    payload = {key: value for key, value in expected.items() if key != blank_field}
    submitted = await client.post(
        f"/api/v1/training/attempts/{attempt_id}/submit",
        headers=student_headers,
        json={"payload": payload},
    )
    assert submitted.status_code == 200, submitted.text
    codes = {
        item["code"]
        for item in submitted.json()["errors"]
        if item.get("field_code") == blank_field
    }
    assert codes, f"Пропуск поля «{blank_field}» должен попасть в замечания"
    assert "address_incomplete" in codes or "field_empty" in codes
