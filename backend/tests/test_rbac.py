"""Разграничение доступа по ролям — ограничения из ТЗ (п.2.3)."""

from __future__ import annotations

from httpx import AsyncClient


async def test_student_cannot_manage_users(client: AsyncClient, student_headers) -> None:
    response = await client.get("/api/v1/users", headers=student_headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"


async def test_student_cannot_create_lesson(client: AsyncClient, student_headers) -> None:
    response = await client.post(
        "/api/v1/lessons",
        headers=student_headers,
        json={"title": "Попытка обучающегося", "student_ids": []},
    )
    assert response.status_code == 403


async def test_admin_cannot_write_scenarios(client: AsyncClient, admin_headers) -> None:
    """ТЗ: администратор не изменяет учебные сценарии."""
    response = await client.post(
        "/api/v1/scenarios",
        headers=admin_headers,
        json={"title": "Сценарий от администратора", "difficulty": "basic"},
    )
    assert response.status_code == 403


async def test_admin_has_no_grade_override_permission(client: AsyncClient, admin_headers) -> None:
    """ТЗ: администратор не может менять оценки."""
    me = await client.get("/api/v1/auth/me", headers=admin_headers)
    permissions = me.json()["permissions"]
    assert "evaluations:override" not in permissions
    assert "audit:read" in permissions


async def test_teacher_cannot_read_system_logs(client: AsyncClient, teacher_headers) -> None:
    response = await client.get("/api/v1/admin/logs", headers=teacher_headers)
    assert response.status_code == 403


async def test_teacher_can_read_catalog(client: AsyncClient, teacher_headers) -> None:
    response = await client.get("/api/v1/categories", headers=teacher_headers)
    assert response.status_code == 200
    assert response.json()["total"] >= 1
