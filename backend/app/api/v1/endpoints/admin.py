"""Кабинет администратора: конфигурация, сервисы, журналы, копии, статистика (п.1.3, 2.7)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import PageDep, SessionDep, require
from app.core.pagination import Page, build_page
from app.core.permissions import Perm
from app.schemas.system import (
    AuditLogRead,
    BackupRead,
    BackupRegister,
    ServiceControlRequest,
    ServiceStateRead,
    SettingRead,
    SettingUpsert,
    SystemLogRead,
    SystemStats,
)
from app.services.admin import AdminService
from app.services.backup import BackupService

router = APIRouter(prefix="/admin", tags=["Администрирование"])


# ------------------------------------------------------------------ состояние
@router.get("/stats", response_model=SystemStats, summary="Сводная статистика системы")
async def stats(session: SessionDep, _=Depends(require(Perm.SYSTEM_MONITOR))) -> SystemStats:
    return SystemStats.model_validate(await AdminService(session).stats())


@router.get("/services", response_model=list[ServiceStateRead], summary="Состояние компонентов")
async def services(
    session: SessionDep, _=Depends(require(Perm.SYSTEM_MONITOR))
) -> list[ServiceStateRead]:
    items = await AdminService(session).list_services()
    return [ServiceStateRead.model_validate(item) for item in items]


@router.post(
    "/services/{name}/control",
    response_model=ServiceStateRead,
    summary="Запустить / остановить / перезапустить сервис",
    description=(
        "Регистрирует команду и передаёт её оркестратору через состояние сервиса. "
        "Во время активных занятий остановка запрещена — администратор не вмешивается "
        "в учебный процесс (ограничение из ТЗ)."
    ),
)
async def control_service(
    name: str,
    data: ServiceControlRequest,
    session: SessionDep,
    request: Request,
    actor=Depends(require(Perm.SYSTEM_SERVICES)),
) -> ServiceStateRead:
    state = await AdminService(session).control_service(name, data, actor, request)
    return ServiceStateRead.model_validate(state)


# --------------------------------------------------------------- конфигурация
@router.get("/settings", response_model=list[SettingRead], summary="Параметры системы")
async def list_settings(
    session: SessionDep, _=Depends(require(Perm.SYSTEM_CONFIG))
) -> list[SettingRead]:
    items = await AdminService(session).list_settings()
    return [SettingRead.model_validate(item) for item in items]


@router.put("/settings", response_model=SettingRead, summary="Изменить параметр системы")
async def upsert_setting(
    data: SettingUpsert,
    session: SessionDep,
    request: Request,
    actor=Depends(require(Perm.SYSTEM_CONFIG)),
) -> SettingRead:
    setting = await AdminService(session).upsert_setting(data, actor, request)
    return SettingRead.model_validate(setting)


# ------------------------------------------------------------ резервные копии
@router.post(
    "/backups",
    response_model=BackupRead,
    summary="Снять резервную копию",
    description=(
        "Выполняет pg_dump в формате custom и возвращает запись журнала. "
        "Восстановление делается администратором вручную командой из поля restore_command: "
        "автоматический откат базы из веб-интерфейса недопустим."
    ),
)
async def run_backup(
    session: SessionDep,
    request: Request,
    kind: str = Query("full", pattern="^(full|schema|data)$"),
    actor=Depends(require(Perm.SYSTEM_BACKUP)),
) -> BackupRead:
    service = BackupService(session)
    record = await service.create_backup(kind=kind, actor=actor, request=request)
    return BackupRead.model_validate(record).model_copy(
        update={"restore_command": service.restore_command(record)}
    )


@router.post(
    "/backups/register",
    response_model=BackupRead,
    summary="Зарегистрировать копию, снятую внешним планировщиком",
)
async def register_backup(
    data: BackupRegister,
    session: SessionDep,
    actor=Depends(require(Perm.SYSTEM_BACKUP)),
) -> BackupRead:
    record = await BackupService(session).register_external(
        path=data.path, size_bytes=data.size_bytes, actor=actor
    )
    return BackupRead.model_validate(record)


@router.get("/backups", response_model=Page[BackupRead], summary="Журнал резервных копий")
async def list_backups(
    session: SessionDep, page: PageDep, _=Depends(require(Perm.SYSTEM_BACKUP))
) -> Page[BackupRead]:
    items, total = await BackupService(session).list_backups(page)
    return build_page([BackupRead.model_validate(item) for item in items], total, page)


# ------------------------------------------------------------------- журналы
@router.get("/audit", response_model=Page[AuditLogRead], summary="Журнал аудита действий")
async def audit_log(
    session: SessionDep,
    page: PageDep,
    action: str | None = Query(None, description="Фильтр по типу действия"),
    actor_id: uuid.UUID | None = None,
    object_type: str | None = None,
    security_only: bool = Query(False, description="Только события безопасности"),
    _=Depends(require(Perm.AUDIT_READ)),
) -> Page[AuditLogRead]:
    items, total = await AdminService(session).list_audit(
        page, action=action, actor_id=actor_id, object_type=object_type, security_only=security_only
    )
    return build_page([AuditLogRead.model_validate(item) for item in items], total, page)


@router.get("/logs", response_model=Page[SystemLogRead], summary="Системный журнал и журнал ошибок")
async def system_logs(
    session: SessionDep,
    page: PageDep,
    level: str | None = Query(None, description="debug / info / warning / error / critical"),
    component: str | None = None,
    _=Depends(require(Perm.SYSTEM_LOGS)),
) -> Page[SystemLogRead]:
    items, total = await AdminService(session).list_logs(page, level=level, component=component)
    return build_page([SystemLogRead.model_validate(item) for item in items], total, page)
