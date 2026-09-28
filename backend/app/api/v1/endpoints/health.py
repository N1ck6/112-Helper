"""Проверки работоспособности и метрики (п.2.9)."""

from __future__ import annotations

import sqlalchemy as sa
from fastapi import APIRouter, Response

from app.api.deps import SessionDep
from app.core.config import settings
from app.core.security import utcnow
from app.integrations.ml_client import get_ml_client
from app.integrations.monitoring import metrics_response
from app.integrations.telephony_client import get_telephony_client
from app.schemas.common import HealthResponse

router = APIRouter(tags=["Служебные"])


@router.get("/health/live", summary="Живость процесса")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready", response_model=HealthResponse, summary="Готовность к работе")
async def ready(session: SessionDep) -> HealthResponse:
    """Проверяет БД и внешние компоненты комплекса (ML, телефония)."""
    try:
        await session.execute(sa.text("SELECT 1"))
        database = "ok"
    except Exception as exc:  # noqa: BLE001
        database = f"error: {exc}"

    components: dict[str, object] = {}
    try:
        components["ml"] = await get_ml_client().health()
    except Exception as exc:  # noqa: BLE001
        components["ml"] = {"status": "down", "error": str(exc)}
    try:
        components["telephony"] = await get_telephony_client().health()
    except Exception as exc:  # noqa: BLE001
        components["telephony"] = {"status": "down", "error": str(exc)}

    return HealthResponse(
        status="ok" if database == "ok" else "degraded",
        app=settings.APP_NAME,
        version=settings.APP_VERSION,
        environment=settings.APP_ENV,
        database=database,
        components=components,
        server_time=utcnow(),
    )


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return metrics_response()
