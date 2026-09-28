from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import NullPool
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.runtime import configure_event_loop

configure_event_loop()


def build_engine(dsn: str | None = None, **kwargs) -> AsyncEngine:
    url = dsn or settings.sqlalchemy_dsn
    options: dict = {
        "echo": settings.DB_ECHO,
        "pool_pre_ping": True,  # переживает кратковременные сбои сети (п.2.8)
        "pool_recycle": settings.DB_POOL_RECYCLE,
        "future": True,
    }
    if settings.APP_ENV == "test":
        options["poolclass"] = NullPool
    elif not url.startswith("sqlite"):
        # SQLite (служебные утилиты) не поддерживает параметры пула.
        options.update(
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
            pool_timeout=settings.DB_POOL_TIMEOUT,
        )
    options.update(kwargs)
    return create_async_engine(url, **options)


engine: AsyncEngine = build_engine()

SessionFactory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI-зависимость: одна транзакция на один HTTP-запрос."""
    async with SessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Та же семантика для фоновых задач, seed-скриптов и WebSocket-обработчиков."""
    async with SessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    await engine.dispose()
