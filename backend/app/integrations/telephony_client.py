from __future__ import annotations

import uuid
from typing import Any, Protocol

import httpx

from app.core.config import settings
from app.core.exceptions import IntegrationError
from app.core.logging import get_logger

logger = get_logger(__name__)


class TelephonyClient(Protocol):
    name: str

    async def originate_call(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    async def hangup(self, sip_call_id: str) -> dict[str, Any]: ...

    async def health(self) -> dict[str, Any]: ...


class HttpTelephonyClient:
    name = "http"

    def __init__(self, base_url: str | None = None) -> None:
        self._base_url = (base_url or settings.TELEPHONY_SERVICE_URL).rstrip("/")
        self._client: httpx.AsyncClient | None = None

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self._base_url, timeout=10.0)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def originate_call(self, payload: dict[str, Any]) -> dict[str, Any]:
        client = await self._http()
        try:
            response = await client.post("/api/v1/calls/originate", json=payload)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise IntegrationError(f"Модуль телефонии недоступен: {exc}") from exc
        return response.json()

    async def hangup(self, sip_call_id: str) -> dict[str, Any]:
        client = await self._http()
        try:
            response = await client.post("/api/v1/calls/hangup", json={"sip_call_id": sip_call_id})
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise IntegrationError(f"Модуль телефонии недоступен: {exc}") from exc
        return response.json()

    async def health(self) -> dict[str, Any]:
        client = await self._http()
        try:
            response = await client.get("/health")
            return {"status": "ok" if response.is_success else "degraded", "code": response.status_code}
        except httpx.HTTPError as exc:
            return {"status": "down", "error": str(exc)}


class StubTelephonyClient:
    name = "stub"

    async def originate_call(self, payload: dict[str, Any]) -> dict[str, Any]:
        call_id = f"stub-{uuid.uuid4().hex[:16]}"
        logger.info("telephony_stub_originate", extra={"sip_call_id": call_id})
        return {
            "sip_call_id": call_id,
            "status": "ringing",
            "caller_number": payload.get("caller_number") or "112",
            "callee_number": payload.get("callee_number") or "1001",
            "latency_ms": 35,
            "stub": True,
        }

    async def hangup(self, sip_call_id: str) -> dict[str, Any]:
        return {"sip_call_id": sip_call_id, "status": "ended", "stub": True}

    async def health(self) -> dict[str, Any]:
        return {"status": "ok", "mode": "stub"}

    async def close(self) -> None:
        return None


_client: TelephonyClient | None = None


def get_telephony_client() -> TelephonyClient:
    global _client
    if _client is None:
        _client = StubTelephonyClient() if settings.TELEPHONY_USE_STUB else HttpTelephonyClient()
    return _client


async def close_telephony_client() -> None:
    global _client
    if _client is not None and hasattr(_client, "close"):
        await _client.close()  # type: ignore[attr-defined]
    _client = None
