from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessRuleError, NotFoundError
from app.core.security import utcnow
from app.models.enums import AuditAction
from app.models.training import LessonParticipant, Workplace
from app.models.user import User
from app.services.audit import AuditService


class WorkplaceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditService(session)

    # ------------------------------------------------------------------ чтение
    async def list_all(self, *, only_active: bool = False) -> Sequence[Workplace]:
        query = sa.select(Workplace).where(Workplace.deleted_at.is_(None))
        if only_active:
            query = query.where(Workplace.is_active.is_(True))
        result = await self.session.execute(query.order_by(Workplace.number))
        return result.scalars().all()

    async def get(self, workplace_id: uuid.UUID) -> Workplace:
        workplace = await self.session.get(Workplace, workplace_id)
        if workplace is None or workplace.deleted_at is not None:
            raise NotFoundError("Рабочее место не найдено")
        return workplace

    async def by_number(
        self, number: str, *, include_deleted: bool = False, lock: bool = False
    ) -> Workplace | None:
        query = sa.select(Workplace).where(Workplace.number == str(number).strip())
        if not include_deleted:
            query = query.where(Workplace.deleted_at.is_(None))
        if lock:
            query = query.with_for_update()
        result = await self.session.execute(query)
        return result.scalars().first()

    # ------------------------------------------------------------------ запись
    async def create(
        self, data: dict[str, Any], actor: User, request: Request | None = None
    ) -> Workplace:
        number = str(data.get("number") or "").strip()
        if not number:
            raise BusinessRuleError("Номер рабочего места обязателен")
        existing = await self.by_number(number, include_deleted=True)
        if existing is not None and existing.deleted_at is None:
            raise BusinessRuleError(f"Рабочее место с номером «{number}» уже есть")
        if existing is not None:
            existing.deleted_at = None
            existing.is_active = bool(data.get("is_active", True))
            for field in ("title", "room", "host", "phone_extension"):
                if data.get(field) is not None:
                    setattr(existing, field, data[field])
            existing.occupied_by_id = None
            existing.occupied_at = None
            await self.session.flush()
            await self.audit.log(
                AuditAction.CREATE,
                actor=actor,
                object_type="workplace",
                object_id=existing.id,
                summary=f"Восстановлено рабочее место {number}",
                request=request,
            )
            return existing

        workplace = Workplace(
            number=number,
            title=data.get("title"),
            room=data.get("room"),
            host=data.get("host"),
            phone_extension=data.get("phone_extension"),
            is_active=bool(data.get("is_active", True)),
            meta=data.get("meta") or {},
        )
        self.session.add(workplace)
        await self.session.flush()
        await self.audit.log(
            AuditAction.CREATE,
            actor=actor,
            object_type="workplace",
            object_id=workplace.id,
            summary=f"Создано рабочее место {number}",
            request=request,
        )
        return workplace

    async def update(
        self,
        workplace_id: uuid.UUID,
        data: dict[str, Any],
        actor: User,
        request: Request | None = None,
    ) -> Workplace:
        workplace = await self.get(workplace_id)
        for field in ("title", "room", "host", "phone_extension", "is_active"):
            if field in data and data[field] is not None:
                setattr(workplace, field, data[field])
        if data.get("number"):
            number = str(data["number"]).strip()
            existing = await self.by_number(number)
            if existing is not None and existing.id != workplace.id:
                raise BusinessRuleError(f"Рабочее место с номером «{number}» уже есть")
            workplace.number = number
        await self.session.flush()
        await self.audit.log(
            AuditAction.UPDATE,
            actor=actor,
            object_type="workplace",
            object_id=workplace.id,
            summary=f"Изменено рабочее место {workplace.number}",
            request=request,
        )
        return workplace

    async def delete(
        self, workplace_id: uuid.UUID, actor: User, request: Request | None = None
    ) -> None:
        workplace = await self.get(workplace_id)
        workplace.deleted_at = utcnow()
        workplace.is_active = False
        await self.session.flush()
        await self.audit.log(
            AuditAction.DELETE,
            actor=actor,
            object_type="workplace",
            object_id=workplace.id,
            summary=f"Удалено рабочее место {workplace.number}",
            request=request,
        )

    # ------------------------------------------------------- занятие места
    async def occupy(self, number: str, student: User) -> Workplace:
        workplace = await self.by_number(number, lock=True)
        if workplace is None:
            raise NotFoundError(f"Рабочее место «{number}» не найдено")
        if not workplace.is_active:
            raise BusinessRuleError(f"Рабочее место «{number}» выведено из эксплуатации")
        if workplace.occupied_by_id is not None and workplace.occupied_by_id != student.id:
            raise BusinessRuleError(f"Рабочее место «{number}» уже занято")

        workplace.occupied_by_id = student.id
        workplace.occupied_at = utcnow()
        #: Обучающийся мог перейти на другое место — старое освобождаем.
        await self.session.execute(
            sa.update(Workplace)
            .where(Workplace.occupied_by_id == student.id, Workplace.id != workplace.id)
            .values(occupied_by_id=None, occupied_at=None)
        )
        await self.session.flush()
        return workplace

    async def release(self, student_id: uuid.UUID) -> None:
        result = await self.session.execute(
            sa.select(Workplace.id).where(Workplace.occupied_by_id == student_id)
        )
        workplace_ids = [row[0] for row in result]
        if not workplace_ids:
            return
        await self.session.execute(
            sa.update(Workplace)
            .where(Workplace.occupied_by_id == student_id)
            .values(occupied_by_id=None, occupied_at=None)
        )
        await self.session.execute(
            sa.update(LessonParticipant)
            .where(
                LessonParticipant.student_id == student_id,
                LessonParticipant.workplace_id.in_(workplace_ids),
            )
            .values(workplace_id=None)
        )

    async def current_for(self, student_id: uuid.UUID) -> Workplace | None:
        result = await self.session.execute(
            sa.select(Workplace).where(
                Workplace.occupied_by_id == student_id, Workplace.deleted_at.is_(None)
            )
        )
        return result.scalar_one_or_none()

    # --------------------------------------------------- раздача по местам
    async def class_map(self, lesson_id: uuid.UUID | None = None) -> list[dict[str, Any]]:
        workplaces = await self.list_all()
        occupied_ids = [w.occupied_by_id for w in workplaces if w.occupied_by_id]
        names: dict[uuid.UUID, str] = {}
        if occupied_ids:
            result = await self.session.execute(
                sa.select(User.id, User.full_name).where(User.id.in_(occupied_ids))
            )
            names = {row.id: row.full_name for row in result}

        participants: dict[uuid.UUID, LessonParticipant] = {}
        if lesson_id is not None:
            result = await self.session.execute(
                sa.select(LessonParticipant).where(LessonParticipant.lesson_id == lesson_id)
            )
            participants = {p.student_id: p for p in result.scalars().all()}

        rows: list[dict[str, Any]] = []
        for workplace in workplaces:
            participant = (
                participants.get(workplace.occupied_by_id) if workplace.occupied_by_id else None
            )
            rows.append(
                {
                    "id": str(workplace.id),
                    "number": workplace.number,
                    "title": workplace.title,
                    "room": workplace.room,
                    "phone_extension": workplace.phone_extension,
                    "is_active": workplace.is_active,
                    "student_id": (
                        str(workplace.occupied_by_id) if workplace.occupied_by_id else None
                    ),
                    "student_name": names.get(workplace.occupied_by_id) if workplace.occupied_by_id else None,
                    "in_lesson": participant is not None,
                    "cards_issued": participant.cards_issued if participant else 0,
                    "cards_submitted": participant.cards_submitted if participant else 0,
                    "difficulty_weight": participant.difficulty_weight if participant else None,
                }
            )
        return rows

    async def bind_participant(
        self, participant: LessonParticipant, student_id: uuid.UUID
    ) -> Workplace | None:
        """Привязать к участнику занятия место, за которым он сейчас сидит."""
        workplace = await self.current_for(student_id)
        if workplace is not None:
            participant.workplace_id = workplace.id
        return workplace
