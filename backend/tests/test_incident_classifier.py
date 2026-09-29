from __future__ import annotations

import io

from httpx import AsyncClient

NORMALIZED_BATCH = {
    "items": [
        {
            "code": "2021103",
            "name": "ДТП с пострадавшими — наезд на светофор",
            "category_name": "ДТП пострадавшие",
            "category_code": "traffic_injured",
            "features": [
                {"type": "object", "value": "Наезд на препятствие"},
                {"type": "detail", "value": "Светофор"},
            ],
            "main_service": "Police",
            "services": ["Скорая"],
            "agency_classifiers": {
                "Классификатор МЧС": "ДТП легкового транспорта",
                "Классификатор СМП": "ДТП с пострадавшими",
            },
            "raw": {"Код": "2021103"},
        },
        {
            "code": "3050201",
            "name": "Взрыв метро (поезд)",
            "category_name": "Взрыв транспорт",
            "features": [
                {"type": "object", "value": "Метро"},
                {"type": "detail", "value": "Вагон/поезд"},
            ],
            "main_service": "МЧС",
        },
    ]
}


async def test_import_normalized_classifier(client: AsyncClient, teacher_headers) -> None:
    """Нормализованные записи сохраняются и привязываются к учебной категории."""
    response = await client.post(
        "/api/v1/incidents/import", headers=teacher_headers, json=NORMALIZED_BATCH
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["imported"] == 2
    assert body["warnings"] == []

    #: Повторный импорт обновляет, а не задваивает записи.
    again = await client.post(
        "/api/v1/incidents/import", headers=teacher_headers, json=NORMALIZED_BATCH
    )
    assert again.json()["updated"] == 2
    assert again.json()["imported"] == 0

    listing = await client.get("/api/v1/incidents/types", headers=teacher_headers)
    assert listing.status_code == 200
    assert listing.json()["total"] == 2


async def test_type_features_and_services(client: AsyncClient, teacher_headers) -> None:
    """Тип отдаётся по коду классификатора, службы приведены к кодам оповещения."""
    await client.post("/api/v1/incidents/import", headers=teacher_headers, json=NORMALIZED_BATCH)

    item = await client.get("/api/v1/incidents/2021103", headers=teacher_headers)
    assert item.status_code == 200, item.text
    body = item.json()
    assert body["name"].startswith("ДТП с пострадавшими")
    assert body["category_id"], "Тип должен быть привязан к учебной категории"
    assert body["agency_classifiers"]["Классификатор МЧС"] == "ДТП легкового транспорта"

    services = {service["code"]: service["is_primary"] for service in body["services"]}
    assert services["102"] is True, "Главная служба — полиция"
    assert services["103"] is False, "Скорая привлекается дополнительно"

    features = await client.get("/api/v1/incidents/2021103/features", headers=teacher_headers)
    assert [feature["value"] for feature in features.json()] == [
        "Наезд на препятствие",
        "Светофор",
    ]

    categories = await client.get("/api/v1/incidents/categories", headers=teacher_headers)
    summary = {row["category_name"]: row for row in categories.json()}
    assert summary["ДТП пострадавшие"]["types_total"] == 1
    assert summary["ДТП пострадавшие"]["category_code"] == "traffic_injured"


async def test_card_takes_services_from_classifier(client: AsyncClient, teacher_headers, categories) -> None:
    """Карточка с кодом типа берёт список оповещения из классификатора заказчика."""
    await client.post("/api/v1/incidents/import", headers=teacher_headers, json=NORMALIZED_BATCH)

    created = await client.post(
        "/api/v1/cards",
        headers=teacher_headers,
        json={
            "title": "Наезд на светофор",
            "category_id": categories["fire"],  # категория намеренно другая
            "incident_type_code": "2021103",
            "payload": {"incident_class": "ДТП с пострадавшими"},
        },
    )
    assert created.status_code == 201, created.text
    services = [item["code"] for item in created.json()["notification_list"]]
    #: Службы классификатора идут первыми, службы категории добавляются следом.
    assert services[0] == "102"
    assert "103" in services
    assert "101" in services, "Службу из категории удалять нельзя"


async def test_import_xlsx_table(client: AsyncClient, teacher_headers) -> None:
    """Таблица заказчика разбирается: колонки по заголовкам, Unnamed — в raw."""
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Классификатор происшествий города Москвы", None, None, None, None, None])
    sheet.append(
        [
            "Код",
            "Категория",
            "Объект",
            "Уточнение",
            "Тип происшествия",
            "Главная служба",
            "Классификатор МЧС",
            None,
        ]
    )
    sheet.append(
        [
            "2021103",
            "ДТП пострадавшие",
            "Наезд на препятствие",
            "Светофор",
            "ДТП с пострадавшими - наезд на светофор",
            "Полиция",
            "ДТП легкового транспорта",
            "служебное значение",
        ]
    )
    sheet.append([None, None, None, None, None, None, None, None])  # строка-разделитель
    sheet.append(
        [
            "1010101",
            "Пожар",
            "Квартира",
            "Открытое пламя",
            "Пожар в жилом помещении",
            "МЧС",
            "Пожар в здании",
            None,
        ]
    )
    buffer = io.BytesIO()
    workbook.save(buffer)

    response = await client.post(
        "/api/v1/incidents/import/xlsx",
        headers=teacher_headers,
        files={
            "file": (
                "classifier.xlsx",
                buffer.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["imported"] + body["updated"] == 2

    item = await client.get("/api/v1/incidents/1010101", headers=teacher_headers)
    body = item.json()
    assert body["name"] == "Пожар в жилом помещении"
    assert body["category_name"] == "Пожар"
    assert [feature["value"] for feature in body["features"]] == ["Квартира", "Открытое пламя"]
    assert body["services"][0]["code"] == "101"
    assert body["agency_classifiers"]["Классификатор МЧС"] == "Пожар в здании"
    assert body["raw"]["Код"] == "1010101", "Исходная строка сохраняется для сверки"


async def test_import_requires_write_permission(client: AsyncClient, student_headers) -> None:
    """Обучающийся классификатор не правит."""
    response = await client.post(
        "/api/v1/incidents/import", headers=student_headers, json=NORMALIZED_BATCH
    )
    assert response.status_code == 403
