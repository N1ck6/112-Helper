from __future__ import annotations

import asyncio
import os
import subprocess
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BusinessRuleError, IntegrationError
from app.core.logging import get_logger
from app.core.pagination import PageParams
from app.core.security import utcnow
from app.models.enums import AuditAction, BackupStatus
from app.models.system import BackupRecord
from app.models.user import User
from app.repositories.system import BackupRepository
from app.services.audit import AuditService

logger = get_logger(__name__)

#: Сколько ждём pg_dump: учебная база небольшая, но на медленном диске бывает долго.
DUMP_TIMEOUT_SECONDS = 900


class BackupService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.backups = BackupRepository(session)
        self.audit = AuditService(session)

    async def create_backup(
        self,
        *,
        kind: str = "full",
        reason: str = "manual",
        actor: User | None = None,
        request: Request | None = None,
    ) -> BackupRecord:
        """Снимает копию и возвращает запись журнала (в т.ч. при неудаче)."""
        settings.ensure_storage()
        stamp = utcnow().strftime("%Y%m%d-%H%M%S")
        path = settings.backups_path / f"dds112-{stamp}-{kind}.dump"

        record = await self.backups.create(
            kind=kind,
            status=BackupStatus.STARTED,
            created_by_id=actor.id if actor else None,
            path=str(path),
        )
        try:
            await self._run_pg_dump(path, kind)
            record.status = BackupStatus.SUCCESS
            record.size_bytes = path.stat().st_size
        except Exception as exc:  # noqa: BLE001 — причина уходит в журнал и в ответ API
            record.status = BackupStatus.FAILED
            record.error = str(exc)[:2000]
            logger.warning("backup_failed", extra={"error": str(exc)})
            if path.exists():
                path.unlink(missing_ok=True)
        finally:
            record.finished_at = utcnow()
            await self.session.flush()

        await self.audit.log(
            AuditAction.BACKUP,
            actor=actor,
            actor_username=None if actor else "система",
            object_type="backup",
            object_id=record.id,
            summary=(
                f"Резервное копирование ({kind}, {reason}): "
                + ("успешно" if record.status is BackupStatus.SUCCESS else "ошибка")
            ),
            after={"status": record.status.value, "bytes": record.size_bytes},
            request=request,
            result="success" if record.status is BackupStatus.SUCCESS else "failure",
        )

        await self._rotate()
        return record

    async def list_backups(self, params: PageParams) -> tuple[Sequence[BackupRecord], int]:
        return await self.backups.paginate(params)

    def restore_command(self, record: BackupRecord) -> str:
        return (
            f"pg_restore --clean --if-exists --dbname={settings.libpq_dsn} "
            f"{record.path or '<файл копии удалён ротацией>'}"
        )

    async def register_external(
        self, *, path: str, size_bytes: int | None, actor: User | None = None
    ) -> BackupRecord:
        if not Path(path).exists():
            raise BusinessRuleError(f"Файл копии не найден: {path}")
        record = await self.backups.create(
            kind="external",
            status=BackupStatus.SUCCESS,
            path=path,
            size_bytes=size_bytes or Path(path).stat().st_size,
            created_by_id=actor.id if actor else None,
            finished_at=utcnow(),
        )
        await self.session.flush()
        return record

    # ------------------------------------------------------------------ приватное
    async def _run_pg_dump(self, path: Path, kind: str) -> None:
        args = [
            settings.BACKUP_PG_DUMP,
            "--format=custom",
            "--no-owner",
            f"--file={path}",
        ]
        if kind == "schema":
            args.append("--schema-only")
        elif kind == "data":
            args.append("--data-only")
        args.append(settings.libpq_dsn)

        #: Пароль — только через окружение дочернего процесса.
        env = {**os.environ, "PGPASSWORD": settings.libpq_password}

        def run() -> subprocess.CompletedProcess[bytes]:
            return subprocess.run(  # noqa: S603 — аргументы формируются здесь, не из запроса
                args,
                capture_output=True,
                env=env,
                timeout=DUMP_TIMEOUT_SECONDS,
            )

        try:
            process = await asyncio.to_thread(run)
        except FileNotFoundError as exc:
            raise IntegrationError(
                "Утилита pg_dump не найдена. Укажите путь к ней в параметре BACKUP_PG_DUMP "
                "или снимайте копии внешним планировщиком (POST /admin/backups/register)."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise IntegrationError("pg_dump не завершился за отведённое время") from exc

        if process.returncode != 0:
            message = (process.stderr or b"").decode("utf-8", errors="replace").strip()
            raise IntegrationError(f"pg_dump завершился с ошибкой: {message[:500]}")

    async def _rotate(self) -> None:
        keep = max(1, settings.BACKUP_KEEP)
        files = sorted(
            settings.backups_path.glob("dds112-*.dump"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        removed = []
        for stale in files[keep:]:
            stale.unlink(missing_ok=True)
            removed.append(str(stale))
            logger.info("backup_rotated", extra={"file": str(stale)})
        if removed:
            await self.session.execute(
                sa.update(BackupRecord).where(BackupRecord.path.in_(removed)).values(path=None)
            )
            await self.session.flush()
