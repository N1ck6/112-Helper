from __future__ import annotations

import time

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings
from app.core.logging import get_logger, new_request_id, set_request_context

logger = get_logger(__name__)

REQUEST_COUNT = Counter(
    "dds112_http_requests_total", "Количество HTTP-запросов", ["method", "path", "status"]
)
REQUEST_LATENCY = Histogram(
    "dds112_http_request_duration_seconds",
    "Длительность обработки запроса",
    ["method", "path"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0),
)
SLOW_REQUESTS = Counter(
    "dds112_http_requests_slow_total",
    "Запросы, превысившие норматив отклика 2 секунды (п.2.8 ТЗ)",
    ["method", "path"],
)
ACTIVE_LESSONS = Gauge("dds112_active_lessons", "Активные учебные занятия")
ACTIVE_ATTEMPTS = Gauge("dds112_active_attempts", "Карточки в работе у обучающихся")
ML_CALLS = Counter("dds112_ml_calls_total", "Обращения к ML-сервису", ["endpoint", "status"])
DB_WRITES = Counter("dds112_db_writes_total", "Операции записи в БД", ["entity"])

RESPONSE_TIME_LIMIT_SECONDS = 2.0


class MetricsMiddleware(BaseHTTPMiddleware):
    """Проставляет request_id, считает метрики и логирует медленные запросы."""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or new_request_id()
        set_request_context(request_id)
        request.state.request_id = request_id

        started = time.perf_counter()
        try:
            response = await call_next(request)
            status = response.status_code
        except Exception:
            REQUEST_COUNT.labels(request.method, _route(request), "500").inc()
            raise

        elapsed = time.perf_counter() - started
        path = _route(request)
        REQUEST_COUNT.labels(request.method, path, str(status)).inc()
        REQUEST_LATENCY.labels(request.method, path).observe(elapsed)
        if elapsed > RESPONSE_TIME_LIMIT_SECONDS:
            SLOW_REQUESTS.labels(request.method, path).inc()
            logger.warning(
                "slow_request",
                extra={"path": path, "method": request.method, "elapsed_ms": int(elapsed * 1000)},
            )

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-ms"] = str(int(elapsed * 1000))
        return response


def _route(request: Request) -> str:
    """Шаблон маршрута вместо конкретного URL — иначе метрики «разрастаются» по id."""
    route = request.scope.get("route")
    return getattr(route, "path", request.url.path)


def metrics_response() -> Response:
    if not settings.MONITORING_ENABLED:
        return Response("monitoring disabled", status_code=404)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
