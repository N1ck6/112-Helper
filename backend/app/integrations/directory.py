from __future__ import annotations

from typing import Any, Protocol

import httpx

from app.core.config import settings
from app.core.exceptions import IntegrationError
from app.core.logging import get_logger

logger = get_logger(__name__)


class DirectoryClient(Protocol):
    """Границы ответственности: каталог отдаёт учётные записи и проверяет пароль."""

    name: str

    async def fetch_users(self) -> list[dict[str, Any]]: ...

    async def authenticate(self, username: str, password: str) -> dict[str, Any] | None: ...

    async def close(self) -> None: ...


class HttpDirectoryClient:
    """Клиент HTTP-шлюза каталога в локальном контуре."""

    name = "directory"

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._client: httpx.AsyncClient | None = None

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=10.0)
        return self._client

    async def fetch_users(self) -> list[dict[str, Any]]:
        client = await self._http()
        try:
            response = await client.get("/users")
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise IntegrationError(f"Каталог доступа недоступен: {exc}") from exc
        payload = response.json()
        users = payload.get("users") if isinstance(payload, dict) else payload
        return list(users or [])

    async def authenticate(self, username: str, password: str) -> dict[str, Any] | None:
        client = await self._http()
        try:
            response = await client.post(
                "/authenticate", json={"username": username, "password": password}
            )
        except httpx.HTTPError as exc:
            raise IntegrationError(f"Каталог доступа недоступен: {exc}") from exc
        if response.status_code in (401, 403):
            return None
        response.raise_for_status()
        payload = response.json()
        if not payload.get("authenticated"):
            return None
        return payload.get("user") or {"username": username}

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


_client: DirectoryClient | None = None


def get_directory_client() -> DirectoryClient | None:
    """Каталог организации (LDAP-шлюз). None — каталог не подключён (DIRECTORY_URL пуст):
    учётные записи ведёт администратор в самом тренажёре."""
    global _client
    if _client is None and settings.DIRECTORY_URL:
        _client = HttpDirectoryClient(settings.DIRECTORY_URL)
    return _client


def set_directory_client(client: DirectoryClient | None) -> None:
    """Подмена клиента в тестах и при переключении контура."""
    global _client
    _client = client


async def close_directory_client() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None
