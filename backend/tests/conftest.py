from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

ROOT = Path(__file__).resolve().parents[1]

# Переменные окружения задаются ДО импорта приложения: движок создаётся при импорте.
TEST_DSN = os.getenv("TEST_DATABASE_URL", "postgresql+asyncpg://dds112:dds112@localhost:5432/dds112_test")
os.environ["DATABASE_URL"] = TEST_DSN
os.environ["APP_ENV"] = "test"
os.environ["ML_USE_STUB"] = "true"
os.environ["TELEPHONY_USE_STUB"] = "true"
os.environ["STORAGE_DIR"] = str(ROOT / "var" / "test")

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.db.session import SessionFactory, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402
from scripts.seed import (  # noqa: E402
    seed_catalog,
    seed_duty_services,
    seed_group,
    seed_permissions_and_roles,
    seed_scenarios,
    seed_users,
    seed_workplaces,
)


@pytest.fixture(scope="session", autouse=True)
async def prepare_database():
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture(scope="session", autouse=True)
async def seeded(prepare_database):
    """Стартовые данные: роли, пользователи, классификатор, группа, сценарии."""
    async with SessionFactory() as session:
        roles = await seed_permissions_and_roles(session)
        users = await seed_users(session, roles)
        categories = await seed_catalog(session)
        await seed_workplaces(session)
        await seed_duty_services(session)
        await seed_group(session, users)
        await seed_scenarios(session, users, categories)
        await session.commit()
        return {"user_ids": {name: user.id for name, user in users.items()}}


@pytest.fixture
def directory():
    """Подключённый каталог организации (в приложении по умолчанию его нет)."""
    from app.integrations.directory import set_directory_client
    from tests.directory_fake import FakeDirectory

    fake = FakeDirectory()
    set_directory_client(fake)
    yield fake
    set_directory_client(None)


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client


async def _login(client: AsyncClient, username: str, password: str) -> str:
    response = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.fixture
async def teacher_headers(client: AsyncClient, seeded) -> dict[str, str]:
    token = await _login(client, "teacher", "Teacher#2026")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def student_headers(client: AsyncClient, seeded) -> dict[str, str]:
    token = await _login(client, "student", "Student#2026")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def admin_headers(client: AsyncClient, seeded) -> dict[str, str]:
    token = await _login(client, "admin", "Admin#2026")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def student_id(seeded) -> str:
    return str(seeded["user_ids"]["student"])


@pytest.fixture
async def categories(client: AsyncClient, teacher_headers) -> dict[str, str]:
    response = await client.get(
        "/api/v1/categories", headers=teacher_headers, params={"size": 100}
    )
    assert response.status_code == 200, response.text
    return {item["code"]: item["id"] for item in response.json()["items"]}


@pytest.fixture(autouse=True)
async def close_running_lessons():
    yield
    import sqlalchemy as sa

    from app.models.enums import LessonStatus
    from app.models.training import Lesson

    async with SessionFactory() as session:
        await session.execute(
            sa.update(Lesson)
            .where(Lesson.status == LessonStatus.RUNNING)
            .values(status=LessonStatus.FINISHED, finished_at=sa.func.now())
        )
        await session.commit()
