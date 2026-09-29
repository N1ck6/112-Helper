"""Аутентификация и базовая защита эндпоинтов (п.2.3)."""

from __future__ import annotations

from httpx import AsyncClient


async def test_login_returns_token_pair(client: AsyncClient, seeded) -> None:
    response = await client.post(
        "/api/v1/auth/login", json={"username": "teacher", "password": "Teacher#2026"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"] and body["refresh_token"]
    assert body["expires_in"] > 0


async def test_login_with_wrong_password_is_rejected(client: AsyncClient, seeded) -> None:
    response = await client.post(
        "/api/v1/auth/login", json={"username": "teacher", "password": "wrong-password"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


async def test_protected_endpoint_requires_token(client: AsyncClient) -> None:
    response = await client.get("/api/v1/users")
    assert response.status_code == 401


async def test_me_returns_roles_and_permissions(client: AsyncClient, teacher_headers) -> None:
    response = await client.get("/api/v1/auth/me", headers=teacher_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["roles"] == ["teacher"]
    assert "lessons:manage" in body["permissions"]
    assert "system:config" not in body["permissions"]


async def test_refresh_issues_new_access_token(client: AsyncClient, seeded) -> None:
    login = await client.post(
        "/api/v1/auth/login", json={"username": "student", "password": "Student#2026"}
    )
    refresh_token = login.json()["refresh_token"]
    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert response.status_code == 200
    assert response.json()["access_token"]


async def test_health_ready_reports_database(client: AsyncClient) -> None:
    response = await client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["database"] == "ok"
