from __future__ import annotations

from httpx import AsyncClient


async def _create_and_start_lesson(
    client: AsyncClient, teacher_headers, student_id: str, category_id: str
) -> str:
    created = await client.post(
        "/api/v1/lessons",
        headers=teacher_headers,
        json={
            "title": "Практическое занятие: заполнение карточек",
            "mode": "card_fill",
            "student_ids": [student_id],
            "category_ids": [category_id],
            "card_source": "generated",
            "time_limit_seconds": 30,
            "max_cards": 2,
        },
    )
    assert created.status_code == 201, created.text
    lesson_id = created.json()["id"]

    started = await client.post(f"/api/v1/lessons/{lesson_id}/start", headers=teacher_headers)
    assert started.status_code == 200, started.text
    assert started.json()["status"] == "running"
    return lesson_id


async def test_full_lesson_cycle(
    client: AsyncClient, teacher_headers, student_headers, student_id, categories
) -> None:
    lesson_id = await _create_and_start_lesson(
        client, teacher_headers, student_id, categories["traffic_injured"]
    )

    # --- обучающийся входит в занятие и получает токен возобновления
    joined = await client.post(f"/api/v1/training/lessons/{lesson_id}/join", headers=student_headers)
    assert joined.status_code == 200, joined.text
    resume_token = joined.json()["resume_token"]
    assert resume_token

    # --- выдача карточки: есть дедлайн, таймер и схема полей
    issued = await client.post(
        f"/api/v1/training/lessons/{lesson_id}/next-card", headers=student_headers
    )
    assert issued.status_code == 200, issued.text
    payload = issued.json()
    attempt_id = payload["attempt"]["id"]
    assert payload["attempt"]["norm_seconds"] == 30
    assert payload["attempt"]["deadline_at"]
    assert payload["seconds_left"] is not None
    assert payload["template_fields"], "Должна прийти схема полей карточки АРМ-112"
    assert payload["card"]["payload"] == {}
    assert payload["card"]["caller_profile"] == {}
    assert payload["card"]["notification_list"] == []

    #: Преподаватель видит и эталон, и список оповещения по ЕКП.
    card_for_teacher = await client.get(
        f"/api/v1/cards/{payload['card']['id']}", headers=teacher_headers
    )
    assert card_for_teacher.status_code == 200, card_for_teacher.text
    expected_fields = card_for_teacher.json()["expected_payload"]
    assert expected_fields, "У сгенерированной карточки должен быть эталон"
    assert card_for_teacher.json()["notification_list"], "Список оповещения формируется по ЕКП"

    # --- повторный запрос не выдаёт вторую карточку
    again = await client.post(
        f"/api/v1/training/lessons/{lesson_id}/next-card", headers=student_headers
    )
    assert again.json()["attempt"]["id"] == attempt_id

    # --- действия оператора фиксируются по порядку
    for action in ("call_accepted", "field_filled", "classified"):
        response = await client.post(
            f"/api/v1/training/attempts/{attempt_id}/actions",
            headers=student_headers,
            json={
                "action_type": action,
                "field_code": "address_street" if action == "field_filled" else None,
                "value_text": "Ленинский проспект" if action == "field_filled" else None,
            },
        )
        assert response.status_code == 201, response.text
    assert response.json()["sequence_no"] == 3

    # --- промежуточное сохранение (защита от потери данных при обрыве связи)
    draft = await client.put(
        f"/api/v1/training/attempts/{attempt_id}/draft",
        headers=student_headers,
        json={"payload": {"address_street": "Ленинский проспект", "address_house": "45"}},
    )
    assert draft.status_code == 200
    assert draft.json()["status"] == "in_progress"

    resumed = await client.post(
        "/api/v1/training/resume", headers=student_headers, json={"resume_token": resume_token}
    )
    assert resumed.status_code == 200
    restored = resumed.json()["restored_state"]
    assert restored["within_grace_period"] is True
    assert restored["draft_payload"]["address_street"] == "Ленинский проспект"

    # --- сдача карточки: приходит оценка и следующая карточка
    submitted = await client.post(
        f"/api/v1/training/attempts/{attempt_id}/submit",
        headers=student_headers,
        json={
            "payload": {
                **expected_fields,
                "operator_message": "Сообщение принято, дежурная бригада направлена на место.",
            }
        },
    )
    assert submitted.status_code == 200, submitted.text
    result = submitted.json()
    #: Карточка заполнена по эталону — оценка должна быть высокой.
    assert result["score"] >= 80, f"Оценка за верно заполненную карточку: {result['score']}"
    assert result["attempt"]["status"] in ("evaluated", "submitted")
    assert result["attempt"]["duration_ms"] is not None
    assert result["attempt"]["time_delta_seconds"] is not None
    assert result["evaluation_id"], "Должна быть сформирована автоматическая оценка"
    assert result["score"] is not None
    assert result["next_attempt"] is not None, "Во время занятия выдаётся следующая карточка"

    evaluation_id = result["evaluation_id"]

    # --- преподаватель видит мониторинг занятия
    monitor = await client.get(f"/api/v1/lessons/{lesson_id}/monitor", headers=teacher_headers)
    assert monitor.status_code == 200, monitor.text
    rows = monitor.json()["rows"]
    assert len(rows) == 1
    assert rows[0]["cards_submitted"] == 1

    # --- экспертная корректировка оценки фиксируется в аудите
    override = await client.post(
        f"/api/v1/evaluations/{evaluation_id}/override",
        headers=teacher_headers,
        json={"score": 88.5, "reason": "Учтены уточнения обучающегося по телефону", "passed": True},
    )
    assert override.status_code == 200, override.text
    assert override.json()["score"] == 88.5
    assert override.json()["source"] == "teacher"
    assert override.json()["original_score"] is not None

    # --- отчёт о занятии формируется и укладывается в норматив 30 секунд
    finished = await client.post(
        f"/api/v1/lessons/{lesson_id}/finish", headers=teacher_headers, json={"reason": "Занятие окончено"}
    )
    assert finished.status_code == 200
    assert finished.json()["status"] == "finished"

    report = await client.post(
        "/api/v1/reports",
        headers=teacher_headers,
        json={"type": "lesson", "format": "json", "lesson_id": lesson_id},
    )
    assert report.status_code == 201, report.text
    body = report.json()
    assert body["status"] == "ready"
    assert body["generation_ms"] < 30_000
    assert body["data"]["rows"], "В отчёте должны быть строки по действиям обучающегося"
    assert body["data"]["summary"]["attempts_total"] >= 1


async def test_grade_override_is_written_to_audit(client: AsyncClient, admin_headers) -> None:
    response = await client.get(
        "/api/v1/admin/audit", headers=admin_headers, params={"action": "grade_override"}
    )
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert items, "Изменение оценки обязано попасть в журнал аудита"
    entry = items[0]
    assert entry["is_security"] is True
    assert entry["before"]["score"] != entry["after"]["score"]
    assert entry["actor_username"] == "teacher"


async def test_student_cannot_touch_other_students_attempt(
    client: AsyncClient, teacher_headers, student_headers, seeded, categories
) -> None:
    """Обучающийся не имеет доступа к карточкам другого обучающегося."""
    other_id = str(seeded["user_ids"]["student2"])
    lesson_id = await _create_and_start_lesson(
        client, teacher_headers, other_id, categories["traffic_injured"]
    )

    token_response = await client.post(
        "/api/v1/auth/login", json={"username": "student2", "password": "Student#2026"}
    )
    other_headers = {"Authorization": f"Bearer {token_response.json()['access_token']}"}
    await client.post(f"/api/v1/training/lessons/{lesson_id}/join", headers=other_headers)
    issued = await client.post(
        f"/api/v1/training/lessons/{lesson_id}/next-card", headers=other_headers
    )
    attempt_id = issued.json()["attempt"]["id"]

    forbidden = await client.put(
        f"/api/v1/training/attempts/{attempt_id}/draft",
        headers=student_headers,
        json={"payload": {"address": "подмена"}},
    )
    assert forbidden.status_code == 403

    #: Обучающийся не участвует в этом занятии — карточку получить нельзя.
    not_participant = await client.post(
        f"/api/v1/training/lessons/{lesson_id}/next-card", headers=student_headers
    )
    assert not_participant.status_code == 403


async def test_analytics_and_forecast(client: AsyncClient, teacher_headers, student_id) -> None:
    summary = await client.get(
        "/api/v1/analytics/summary", headers=teacher_headers, params={"student_id": student_id}
    )
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["attempts_total"] >= 1
    assert body["generated_in_ms"] < 30_000

    forecast = await client.get(
        f"/api/v1/analytics/forecast/{student_id}", headers=teacher_headers
    )
    assert forecast.status_code == 200, forecast.text
    assert forecast.json()["attempts_used"] >= 1
    assert 0.0 <= forecast.json()["confidence"] <= 1.0


async def test_certificate_and_csv_export(client: AsyncClient, teacher_headers, student_id) -> None:
    """Сертификат (PDF) и выгрузка отчёта файлом (CSV) — п.2.6."""
    certificate = await client.post(
        "/api/v1/certificates",
        headers=teacher_headers,
        json={"student_id": student_id, "program_name": "Подготовка оператора ДДС города Москвы", "hours": 16},
    )
    assert certificate.status_code == 201, certificate.text
    body = certificate.json()
    assert body["serial"].startswith("ДДС-112/")
    assert body["score"] is not None

    pdf = await client.get(
        f"/api/v1/certificates/{body['id']}/download", headers=teacher_headers
    )
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF"), "Сертификат должен быть валидным PDF"

    report = await client.post(
        "/api/v1/reports",
        headers=teacher_headers,
        json={"type": "progress", "format": "csv", "student_id": student_id},
    )
    assert report.status_code == 201, report.text
    assert report.json()["status"] == "ready"
    assert report.json()["data"]["forecast"] is not None

    csv_file = await client.get(
        f"/api/v1/reports/{report.json()['id']}/download", headers=teacher_headers
    )
    assert csv_file.status_code == 200
    assert csv_file.content, "Файл отчёта не должен быть пустым"
