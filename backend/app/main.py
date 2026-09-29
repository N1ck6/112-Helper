from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import RedirectResponse

from app.api.v1.endpoints import health
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import get_logger, setup_logging
from app.db.session import dispose_engine
from app.integrations.directory import close_directory_client
from app.integrations.ml_client import close_ml_client
from app.integrations.monitoring import MetricsMiddleware
from app.integrations.outbox import OutboxWorker
from app.integrations.telephony_client import close_telephony_client
from app.workers.maintenance import build_tasks

logger = get_logger(__name__)

DESCRIPTION = """
Backend учебного программного обеспечения для подготовки операторов ДДС города Москвы
(эмулятор АРМ-112, ГБУ «Система 112»).

**Зона ответственности сервиса:** REST API, PostgreSQL, пользователи и RBAC, учебные
сценарии и эталоны, занятия, карточки происшествий, оценки, отчётность, журналы и аудит,
а также контракты интеграции с ML-модулем и модулем IP-телефонии.

**Роли:** администратор системы, преподаватель, обучающийся. Права выдаются по модели RBAC;
ограничения ролей из ТЗ реализованы отсутствием соответствующих прав.

**Работа без готовых модулей команды:** при `ML_USE_STUB=true` и `TELEPHONY_USE_STUB=true`
сервис работает автономно на детерминированных заглушках, что позволяет разрабатывать
frontend и демонстрировать сквозной сценарий занятия.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    settings.ensure_storage()
    logger.info(
        "service_starting",
        extra={
            "env": settings.APP_ENV,
            "ml_stub": settings.ML_USE_STUB,
            "telephony_stub": settings.TELEPHONY_USE_STUB,
        },
    )

    outbox_worker = OutboxWorker()
    outbox_worker.start()
    tasks = build_tasks()
    for task in tasks:
        task.start()

    try:
        yield
    finally:
        for task in tasks:
            await task.stop()
        await outbox_worker.stop()
        await close_ml_client()
        await close_telephony_client()
        await close_directory_client()
        await dispose_engine()
        logger.info("service_stopped")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=DESCRIPTION,
    docs_url="/docs" if settings.ENABLE_DOCS else None,
    redoc_url="/redoc" if settings.ENABLE_DOCS else None,
    openapi_url="/openapi.json" if settings.ENABLE_DOCS else None,
    lifespan=lifespan,
    contact={"name": "Команда разработки тренажёра ДДС-112"},
)

# Порядок middleware важен: метрики должны видеть итоговый статус ответа.
app.add_middleware(MetricsMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-Response-Time-ms"],
)

register_exception_handlers(app)

app.include_router(health.router)
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse(url="/docs" if settings.ENABLE_DOCS else "/health/live")
