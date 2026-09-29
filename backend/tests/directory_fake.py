"""Каталог организации для тестов: в приложении каталога нет, пока не задан DIRECTORY_URL."""

from __future__ import annotations

from typing import Any


class FakeDirectory:
    name = "test-directory"

    USERS: list[dict[str, Any]] = [
        {
            "external_id": "DDS-1001",
            "username": "ivanov.dds",
            "full_name": "Иванов Алексей Викторович",
            "email": "ivanov.dds@dds112.local",
            "organization": "ДДС ЖКХ Северного округа",
            "position": "Диспетчер",
            "role": "student",
        },
        {
            "external_id": "DDS-1002",
            "username": "petrova.dds",
            "full_name": "Петрова Наталья Сергеевна",
            "email": "petrova.dds@dds112.local",
            "organization": "ДДС ЖКХ Северного округа",
            "position": "Старший диспетчер",
            "role": "student",
        },
    ]

    def __init__(self, password: str | None = None) -> None:
        #: пароль, который каталог принимает; None — отклоняет всё
        self.password = password

    async def fetch_users(self) -> list[dict[str, Any]]:
        return [dict(user) for user in self.USERS]

    async def authenticate(self, username: str, password: str) -> dict[str, Any] | None:
        return {"username": username} if self.password and password == self.password else None

    async def close(self) -> None:
        return None
