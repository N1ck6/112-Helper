from __future__ import annotations

from httpx import AsyncClient


async def test_draft_survives_page_reload(
    client: AsyncClient, teacher_headers, student_headers, student_id, categories
) -> None:
    created = await client.post(
        "/api/v1/lessons",
        headers=teacher_headers,
        json={
            "title": "Черновик карточки",
            "mode": "card_fill",
            "student_ids": [student_id],
            "category_ids": [categories["fire_apartment"]],
            "card_source": "generated",
            "time_limit_seconds": 120,
            "max_cards": 1,
        },
    )
    lesson_id = created.json()["id"]
    await client.post(f"/api/v1/lessons/{lesson_id}/start", headers=teacher_headers)
    await client.post(f"/api/v1/training/lessons/{lesson_id}/join", headers=student_headers)
    issued = await client.post(f"/api/v1/training/lessons/{lesson_id}/next-card", headers=student_headers)
    attempt_id = issued.json()["attempt"]["id"]

    draft = {
        "address_street": "ул. Тверская",
        "description": "Дым из окна",
        "_ui": {"addressLine": "Тверская 6", "caller": "Иванова", "fillSeconds": 42},
    }
    saved = await client.put(
        f"/api/v1/training/attempts/{attempt_id}/draft", headers=student_headers, json={"payload": draft}
    )
    assert saved.status_code == 200, saved.text

    #: Перезагрузка страницы: интерфейс заново входит в занятие и получает открытую карточку.
    rejoined = await client.post(f"/api/v1/training/lessons/{lesson_id}/join", headers=student_headers)
    active = rejoined.json()["active_attempt"]
    assert active["attempt"]["id"] == attempt_id
    assert active["attempt"]["draft_payload"] == draft
