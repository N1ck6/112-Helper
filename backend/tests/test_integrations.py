"""Интеграции: каталог доступа и пакетный импорт материалов (п.2.9 ТЗ)."""

from __future__ import annotations

import io
import zipfile

from httpx import AsyncClient


async def test_directory_sync_without_directory_is_refused(client: AsyncClient, admin_headers) -> None:
    """Каталог не подключён — никаких выдуманных учётных записей, понятный отказ."""
    response = await client.post("/api/v1/users/sync-directory", headers=admin_headers)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "directory_not_configured"


async def test_directory_sync_creates_and_updates_accounts(
    client: AsyncClient, admin_headers, directory
) -> None:
    """Учётные записи приезжают из каталога организации, а не заводятся руками."""
    preview = await client.post(
        "/api/v1/users/sync-directory", headers=admin_headers, params={"dry_run": True}
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["created"], "Пробный прогон показывает, кого создаст"

    #: Пробный прогон ничего не менял.
    users = await client.get(
        "/api/v1/users", headers=admin_headers, params={"query": "ivanov.dds"}
    )
    assert users.json()["total"] == 0

    applied = await client.post("/api/v1/users/sync-directory", headers=admin_headers)
    assert applied.status_code == 200, applied.text
    body = applied.json()
    assert body["total"] == 2
    assert set(body["created"]) == {"ivanov.dds", "petrova.dds"}
    assert body["missing_in_directory"] == []

    created = await client.get(
        "/api/v1/users", headers=admin_headers, params={"query": "ivanov.dds"}
    )
    user = created.json()["items"][0]
    assert user["auth_source"] == "directory"
    assert user["external_id"] == "DDS-1001"
    assert user["organization"] == "ДДС ЖКХ Северного округа"

    #: Повторная синхронизация идемпотентна.
    again = await client.post("/api/v1/users/sync-directory", headers=admin_headers)
    assert again.json()["created"] == []


async def test_directory_account_cannot_login_with_local_password(
    client: AsyncClient, admin_headers, directory
) -> None:
    """Пароль такой записи проверяет каталог — локально подобрать его нельзя."""
    await client.post("/api/v1/users/sync-directory", headers=admin_headers)

    response = await client.post(
        "/api/v1/auth/login", json={"username": "ivanov.dds", "password": "Student#2026"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


async def test_bulk_materials_import(client: AsyncClient, teacher_headers) -> None:
    """Методические материалы загружаются пакетом — архивом."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("Памятка АРМ-112.md", "# Работа на АРМ-112\nСтатусы реагирования…")
        archive.writestr("Классификатор.csv", "код;наименование\nfire;Пожары")
        archive.writestr("вложенная/Билеты.txt", "Билет №1")
        #: Файл недопустимого типа должен быть пропущен, а не сломать импорт.
        archive.writestr("вирус.exe", "MZ")

    response = await client.post(
        "/api/v1/materials/bulk",
        headers=teacher_headers,
        files={"file": ("materials.zip", buffer.getvalue(), "application/zip")},
        data={"kind": "memo"},
    )
    assert response.status_code == 201, response.text
    titles = {item["title"] for item in response.json()}
    assert titles == {"Памятка АРМ-112", "Классификатор", "Билеты"}

    listing = await client.get(
        "/api/v1/materials", headers=teacher_headers, params={"kind": "memo"}
    )
    assert listing.json()["total"] >= 3


async def test_bulk_materials_rejects_broken_archive(client: AsyncClient, teacher_headers) -> None:
    response = await client.post(
        "/api/v1/materials/bulk",
        headers=teacher_headers,
        files={"file": ("materials.zip", b"not an archive", "application/zip")},
    )
    assert response.status_code == 422
    assert "ZIP" in response.json()["error"]["message"]
