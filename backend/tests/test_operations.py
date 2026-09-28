from __future__ import annotations

import uuid
from datetime import timedelta

import sqlalchemy as sa
from httpx import AsyncClient

from app.core.security import utcnow
from app.db.session import SessionFactory
from app.models.audit import AuditLog, SystemLog
from app.models.enums import AuditAction, CardLifecycleStatus, LogLevel, ResponseStatus
from app.models.training import CardAttempt
from app.services.audit import AuditService
from app.services.training import TrainingService


async def test_backup_creates_file_and_journal_entry(client: AsyncClient, admin_headers) -> None:
    """Копия снимается pg_dump'ом, попадает в журнал и в аудит."""
    response = await client.post(
        "/api/v1/admin/backups", headers=admin_headers, params={"kind": "schema"}
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["status"] == "success", body.get("error")
    assert body["size_bytes"] and body["size_bytes"] > 0
    assert body["restore_command"].startswith("pg_restore")

    journal = await client.get("/api/v1/admin/backups", headers=admin_headers)
    assert journal.status_code == 200
    assert journal.json()["total"] >= 1

    audit = await client.get(
        "/api/v1/admin/audit", headers=admin_headers, params={"action": "backup"}
    )
    assert audit.json()["items"], "Резервное копирование обязано попасть в журнал аудита"


async def test_expired_logs_are_purged_but_security_ones_remain() -> None:
    """Журнал безопасности хранится не менее полугода, остальное вычищается."""
    async with SessionFactory() as session:
        old = utcnow() - timedelta(days=400)
        session.add_all(
            [
                AuditLog(action=AuditAction.EXPORT, summary="старая выгрузка", at=old, is_security=False),
                AuditLog(action=AuditAction.LOGIN, summary="старый вход", at=old, is_security=True),
                SystemLog(message="старое техническое сообщение", level=LogLevel.INFO, at=old),
            ]
        )
        await session.commit()

        removed = await AuditService(session).purge_expired()
        await session.commit()
        assert removed >= 2

        remaining = (
            await session.execute(
                sa.select(sa.func.count()).select_from(AuditLog).where(AuditLog.at < utcnow() - timedelta(days=365))
            )
        ).scalar_one()
        assert remaining == 1, "Запись журнала безопасности удалять нельзя"


async def test_card_without_completion_becomes_unfinished(
    client: AsyncClient, teacher_headers, student_headers, student_id, categories
) -> None:
    """Через 48 часов без «Работы завершены» карточка получает статус «Не завершено»."""
    created = await client.post(
        "/api/v1/lessons",
        headers=teacher_headers,
        json={
            "title": "Занятие: незавершённые работы",
            "mode": "card_action",
            "student_ids": [student_id],
            "category_ids": [categories["fire_apartment"]],
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

    for status, comment in (
        ("accepted", None),
        ("response_started", "Наряд направлен"),
        ("arrived", "Прибытие подразделения"),
    ):
        response = await client.post(
            f"/api/v1/training/attempts/{attempt_id}/response-status",
            headers=student_headers,
            json={"status": status, "comment": comment},
        )
        assert response.status_code == 201, response.text

    #: Отматываем время выдачи карточки назад — имитируем прошедшие двое суток.
    async with SessionFactory() as session:
        await session.execute(
            sa.update(CardAttempt)
            .where(CardAttempt.id == uuid.UUID(attempt_id))
            .values(issued_at=utcnow() - timedelta(hours=72))
        )
        await session.commit()

        marked = await TrainingService(session).mark_unfinished_cards()
        await session.commit()
        assert marked >= 1

        attempt = await session.get(CardAttempt, uuid.UUID(attempt_id))
        assert attempt.lifecycle_status is CardLifecycleStatus.NOT_FINISHED
        assert attempt.last_response_status is ResponseStatus.ARRIVED
