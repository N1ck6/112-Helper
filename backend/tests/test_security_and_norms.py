from __future__ import annotations

import uuid

import sqlalchemy as sa
from httpx import AsyncClient

from app.core.security import hash_password, utcnow
from app.db.session import SessionFactory
from app.models.audit import AuditLog
from app.models.enums import AuditAction, CardLifecycleStatus, ResponseStatus, UserStatus
from app.models.training import CardAttempt
from app.models.user import User


async def test_directory_login_respects_second_factor(
    client: AsyncClient, admin_headers, directory
) -> None:
    """Вход через каталог не должен обходить второй фактор (п.2.3 ТЗ)."""
    await client.post("/api/v1/users/sync-directory", headers=admin_headers)
    directory.password = "Directory#2026"
    try:
        async with SessionFactory() as session:
            user = (
                await session.execute(sa.select(User).where(User.username == "ivanov.dds"))
            ).scalars().one()
            user.mfa_enabled = True
            user.mfa_secret = "JBSWY3DPEHPK3PXP"
            await session.commit()

        response = await client.post(
            "/api/v1/auth/login",
            json={"username": "ivanov.dds", "password": "Directory#2026"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert "mfa_token" in body, "Должен запрашиваться код второго фактора"
        assert "access_token" not in body, "Токен доступа до второго фактора выдавать нельзя"
    finally:
        async with SessionFactory() as session:
            user = (
                await session.execute(sa.select(User).where(User.username == "ivanov.dds"))
            ).scalars().one()
            user.mfa_enabled = False
            user.mfa_secret = None
            await session.commit()


async def test_failed_logins_are_counted_and_logged(client: AsyncClient) -> None:
    """Счётчик попыток и запись в журнале не должны откатываться вместе с ошибкой."""
    username = f"brute_{uuid.uuid4().hex[:8]}"
    async with SessionFactory() as session:
        session.add(
            User(
                username=username,
                full_name="Проверка защиты от подбора",
                password_hash=hash_password("Correct#2026"),
                status=UserStatus.ACTIVE,
                password_changed_at=utcnow(),
            )
        )
        await session.commit()

    for _ in range(3):
        response = await client.post(
            "/api/v1/auth/login", json={"username": username, "password": "Wrong#0000"}
        )
        assert response.status_code == 401

    async with SessionFactory() as session:
        user = (
            await session.execute(sa.select(User).where(User.username == username))
        ).scalars().one()
        assert user.failed_login_count == 3, "Неудачные попытки обязаны учитываться"

        logged = (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.action == AuditAction.LOGIN_FAILED,
                    AuditLog.actor_username == username,
                )
            )
        ).scalar_one()
        assert logged == 3, "Неудачные входы обязаны попадать в журнал безопасности"


async def test_response_norm_does_not_close_card_after_30_seconds(
    client: AsyncClient, teacher_headers, student_headers, student_id, categories
) -> None:
    """Норматив 30 секунд относится к первичному статусу, а не ко всей карточке."""
    created = await client.post(
        "/api/v1/lessons",
        headers=teacher_headers,
        json={
            "title": "Проверка норматива и времени отработки",
            "mode": "card_action",
            "student_ids": [student_id],
            "category_ids": [categories["fire_apartment"]],
            "time_limit_seconds": 30,
            "max_cards": 1,
        },
    )
    lesson_id = created.json()["id"]
    await client.post(f"/api/v1/lessons/{lesson_id}/start", headers=teacher_headers)
    await client.post(f"/api/v1/training/lessons/{lesson_id}/join", headers=student_headers)
    issued = await client.post(
        f"/api/v1/training/lessons/{lesson_id}/next-card", headers=student_headers
    )
    view = issued.json()

    assert view["attempt"]["norm_seconds"] == 30
    assert view["response_seconds_left"] <= 30
    #: На отработку карточки времени должно быть больше, чем 30 секунд на первый статус.
    assert view["seconds_left"] > view["response_seconds_left"] + 60


async def test_reconsidered_refusal_returns_card_to_work(
    client: AsyncClient, teacher_headers, student_headers, student_id, categories
) -> None:
    """«Не принята» → «Принята» снимает статус «Отказ» с карточки."""
    created = await client.post(
        "/api/v1/lessons",
        headers=teacher_headers,
        json={
            "title": "Пересмотр решения по карточке",
            "mode": "card_action",
            "student_ids": [student_id],
            "category_ids": [categories["fire_apartment"]],
            "max_cards": 1,
        },
    )
    lesson_id = created.json()["id"]
    await client.post(f"/api/v1/lessons/{lesson_id}/start", headers=teacher_headers)
    await client.post(f"/api/v1/training/lessons/{lesson_id}/join", headers=student_headers)
    attempt_id = (
        await client.post(f"/api/v1/training/lessons/{lesson_id}/next-card", headers=student_headers)
    ).json()["attempt"]["id"]

    refused = await client.post(
        f"/api/v1/training/attempts/{attempt_id}/response-status",
        headers=student_headers,
        json={"status": "not_accepted", "comment": "Территория не обслуживается, в компетенции 101"},
    )
    assert refused.status_code == 201, refused.text
    assert refused.json()["attempt"]["lifecycle_status"] == "refusal"

    reconsidered = await client.post(
        f"/api/v1/training/attempts/{attempt_id}/response-status",
        headers=student_headers,
        json={"status": "accepted", "comment": "Решение пересмотрено, наряд направлен"},
    )
    assert reconsidered.status_code == 201, reconsidered.text
    assert reconsidered.json()["attempt"]["lifecycle_status"] == "registered"


async def test_accepted_card_without_completion_becomes_unfinished(
    client: AsyncClient, teacher_headers, student_headers, student_id, categories
) -> None:
    """Принятая и брошенная карточка — основной случай статуса «Не завершено»."""
    from datetime import timedelta

    from app.services.training import TrainingService

    created = await client.post(
        "/api/v1/lessons",
        headers=teacher_headers,
        json={
            "title": "Принята и не закрыта",
            "mode": "card_action",
            "student_ids": [student_id],
            "category_ids": [categories["fire_apartment"]],
            "max_cards": 1,
        },
    )
    lesson_id = created.json()["id"]
    await client.post(f"/api/v1/lessons/{lesson_id}/start", headers=teacher_headers)
    await client.post(f"/api/v1/training/lessons/{lesson_id}/join", headers=student_headers)
    attempt_id = (
        await client.post(f"/api/v1/training/lessons/{lesson_id}/next-card", headers=student_headers)
    ).json()["attempt"]["id"]
    accepted = await client.post(
        f"/api/v1/training/attempts/{attempt_id}/response-status",
        headers=student_headers,
        json={"status": "accepted"},
    )
    assert accepted.status_code == 201, accepted.text

    async with SessionFactory() as session:
        await session.execute(
            sa.update(CardAttempt)
            .where(CardAttempt.id == uuid.UUID(attempt_id))
            .values(issued_at=utcnow() - timedelta(hours=72))
        )
        await session.commit()
        assert await TrainingService(session).mark_unfinished_cards() >= 1
        await session.commit()

        attempt = await session.get(CardAttempt, uuid.UUID(attempt_id))
        assert attempt.last_response_status is ResponseStatus.ACCEPTED
        assert attempt.lifecycle_status is CardLifecycleStatus.NOT_FINISHED


async def test_directory_dry_run_changes_nothing(client: AsyncClient, admin_headers, directory) -> None:
    """Пробный прогон синхронизации не должен менять данные."""
    await client.post("/api/v1/users/sync-directory", headers=admin_headers)

    async with SessionFactory() as session:
        user = (
            await session.execute(sa.select(User).where(User.username == "petrova.dds"))
        ).scalars().one()
        user.full_name = "Изменено вручную преподавателем"
        await session.commit()

    preview = await client.post(
        "/api/v1/users/sync-directory", headers=admin_headers, params={"dry_run": True}
    )
    assert preview.status_code == 200, preview.text
    assert "petrova.dds" in preview.json()["updated"], "Расхождение должно быть показано"

    async with SessionFactory() as session:
        user = (
            await session.execute(sa.select(User).where(User.username == "petrova.dds"))
        ).scalars().one()
        assert user.full_name == "Изменено вручную преподавателем", "dry_run не должен писать в БД"


async def test_response_options_are_empty_in_card_fill_mode(
    client: AsyncClient, teacher_headers, student_headers, student_id
) -> None:
    """В режиме заполнения карточки статусы реагирования не предлагаются."""
    created = await client.post(
        "/api/v1/lessons",
        headers=teacher_headers,
        json={
            "title": "Заполнение карточки",
            "mode": "card_fill",
            "student_ids": [student_id],
            "max_cards": 1,
        },
    )
    lesson_id = created.json()["id"]
    await client.post(f"/api/v1/lessons/{lesson_id}/start", headers=teacher_headers)
    await client.post(f"/api/v1/training/lessons/{lesson_id}/join", headers=student_headers)
    attempt_id = (
        await client.post(f"/api/v1/training/lessons/{lesson_id}/next-card", headers=student_headers)
    ).json()["attempt"]["id"]

    options = await client.get(
        f"/api/v1/training/attempts/{attempt_id}/response-options", headers=student_headers
    )
    assert options.status_code == 200
    assert options.json()["available"] == []


async def test_student_cannot_browse_the_card_pool(
    client: AsyncClient, student_headers, teacher_headers
) -> None:
    forbidden = await client.get("/api/v1/cards", headers=student_headers)
    assert forbidden.status_code == 403, forbidden.text
    assert forbidden.json()["error"]["code"] == "permission_denied"

    #: Преподавателю пул по-прежнему доступен.
    allowed = await client.get("/api/v1/cards", headers=teacher_headers)
    assert allowed.status_code == 200, allowed.text

    #: Эталоны и сценарии — тоже нет: иначе оператор 112 прочитал бы то, что должен выяснить у заявителя.
    for path in ("/api/v1/cards/export?with_expected=true", "/api/v1/scenarios"):
        leak = await client.get(path, headers=student_headers)
        assert leak.status_code == 403, f"{path}: {leak.status_code}"

    #: А состав полей карточки обучающемуся нужен — форму по чему-то рисовать.
    template = await client.get("/api/v1/card-templates", headers=student_headers)
    assert template.status_code == 200, template.text
