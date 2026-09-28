"""Репозитории журналов, конфигурации, отчётов и телефонии."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from app.models.audit import AuditLog, SystemLog
from app.models.enums import OutboxStatus
from app.models.report import Certificate, Report
from app.models.system import (
    BackupRecord,
    CallRecord,
    OutboxMessage,
    ServiceState,
    SystemSetting,
    TelephonyConfig,
)
from app.repositories.base import BaseRepository


class AuditRepository(BaseRepository[AuditLog]):
    model = AuditLog
    default_order = AuditLog.at.desc()


class SystemLogRepository(BaseRepository[SystemLog]):
    model = SystemLog
    default_order = SystemLog.at.desc()


class SettingRepository(BaseRepository[SystemSetting]):
    model = SystemSetting
    default_order = SystemSetting.key

    async def by_key(self, key: str) -> SystemSetting | None:
        return await self.find_one(SystemSetting.key == key)


class ServiceStateRepository(BaseRepository[ServiceState]):
    model = ServiceState
    default_order = ServiceState.name

    async def by_name(self, name: str) -> ServiceState | None:
        return await self.find_one(ServiceState.name == name)

    async def upsert(self, name: str, **values) -> ServiceState:
        state = await self.by_name(name)
        if state is None:
            return await self.create(name=name, **values)
        for key, value in values.items():
            setattr(state, key, value)
        await self.session.flush()
        return state


class BackupRepository(BaseRepository[BackupRecord]):
    model = BackupRecord
    default_order = BackupRecord.started_at.desc()


class ReportRepository(BaseRepository[Report]):
    model = Report
    default_order = Report.created_at.desc()


class CertificateRepository(BaseRepository[Certificate]):
    model = Certificate
    default_order = Certificate.issued_at.desc()

    async def next_serial(self) -> str:
        total = await self.count()
        return f"ДДС-112/{total + 1:05d}"


class TelephonyConfigRepository(BaseRepository[TelephonyConfig]):
    model = TelephonyConfig
    default_order = TelephonyConfig.name

    async def active(self) -> TelephonyConfig | None:
        return await self.find_one(TelephonyConfig.is_active.is_(True))


class CallRepository(BaseRepository[CallRecord]):
    model = CallRecord
    default_order = CallRecord.started_at.desc()

    async def by_sip_id(self, sip_call_id: str) -> CallRecord | None:
        return await self.find_one(CallRecord.sip_call_id == sip_call_id)

    async def for_attempt(self, attempt_id: uuid.UUID) -> Sequence[CallRecord]:
        return await self.list_all(CallRecord.attempt_id == attempt_id)


class OutboxRepository(BaseRepository[OutboxMessage]):
    model = OutboxMessage
    default_order = OutboxMessage.created_at.desc()

    async def pending_count(self) -> int:
        return await self.count(OutboxMessage.status == OutboxStatus.PENDING)
