"""Классификатор происшествий и нормативы времени (п.2.2, п.2.4 ТЗ)."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import SoftDelete, Timestamped, UUIDPrimaryKey
from app.db.types import JSONType, enum_column
from app.models.enums import ActionType, DifficultyLevel, LessonMode, ServiceLevel


class IncidentCategory(UUIDPrimaryKey, Timestamped, SoftDelete, Base):
    """Иерархический классификатор: ДТП, пожары, медицина, ЖКХ, газ и т.д."""

    __tablename__ = "incident_categories"

    code: Mapped[str] = mapped_column(sa.String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("incident_categories.id", ondelete="SET NULL"), nullable=True
    )
    #: Профильная служба, в чью ленту попадают события категории.
    dds_profile: Mapped[str | None] = mapped_column(sa.String(128), nullable=True, index=True)
    default_difficulty: Mapped[DifficultyLevel] = mapped_column(
        enum_column(DifficultyLevel), default=DifficultyLevel.BASIC, nullable=False
    )
    #: Обязательные поля карточки для данной категории (используется при оценке полноты).
    required_fields: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    notify_services: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)

    children: Mapped[list[IncidentCategory]] = relationship(lazy="noload")


class IncidentType(UUIDPrimaryKey, Timestamped, SoftDelete, Base):
    __tablename__ = "incident_types"
    __table_args__ = (
        sa.Index("ix_incident_types_category_type", "category_name", "name"),
    )

    #: Код происшествия в классификаторе заказчика (например, 2021103).
    code: Mapped[str] = mapped_column(sa.String(64), unique=True, nullable=False)
    #: Итоговый тип: «ДТП с пострадавшими — наезд на светофор».
    name: Mapped[str] = mapped_column(sa.String(512), nullable=False)
    #: Категория в терминах исходной таблицы: «ДТП пострадавшие».
    category_name: Mapped[str | None] = mapped_column(sa.String(255), nullable=True, index=True)
    #: Привязка к учебному классификатору — по ней подбираются сценарии и нормативы.
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("incident_categories.id", ondelete="SET NULL"), nullable=True
    )
    #: Признаки: [{"type": "object", "value": "Наезд на препятствие"}, ...]
    features: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    #: Главная служба реагирования по классификатору.
    main_service: Mapped[str | None] = mapped_column(sa.String(128), nullable=True, index=True)
    #: Службы списка оповещения в нашем формате: [{"code": …, "is_primary": …}, …].
    services: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    #: Соответствия ведомственным классификаторам: {"mchs": "...", "mvd": "..."}.
    agency_classifiers: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    #: Исходная строка таблицы — для сверки при разборе спорных случаев.
    raw: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)


class DutyService(UUIDPrimaryKey, Timestamped, SoftDelete, Base):
    __tablename__ = "duty_services"
    __table_args__ = (
        sa.Index("ix_duty_services_level_area", "level", "area"),
    )

    #: Код службы: «101», «dds_szao», «dds_upravа_shchukino».
    code: Mapped[str] = mapped_column(sa.String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    short_name: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    level: Mapped[ServiceLevel] = mapped_column(
        enum_column(ServiceLevel), default=ServiceLevel.OTHER, nullable=False, index=True
    )
    #: Административный округ (СЗАО, ЦАО …). Пусто — служба городского уровня.
    okrug: Mapped[str | None] = mapped_column(sa.String(64), nullable=True, index=True)
    #: Район обслуживания (Щукино, Тверской …). Пусто — вся территория округа.
    area: Mapped[str | None] = mapped_column(sa.String(128), nullable=True, index=True)
    #: Кому подчинена: код вышестоящей службы (ДДС управы → ДДС округа).
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("duty_services.id", ondelete="SET NULL"), nullable=True
    )
    #: Внутренний номер для симулятора IP-телефона: заказчик назвал 3–4 цифры.
    phone_extension: Mapped[str | None] = mapped_column(sa.String(16), nullable=True)
    phone: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    #: Должностное лицо, которому докладывает диспетчер: ФИО, должность, номер.
    supervisor: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    #: Категории происшествий, по которым служба привлекается всегда.
    categories: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    #: Профильная ли служба: реагирует сама или только принимает к сведению.
    is_primary: Mapped[bool] = mapped_column(
        sa.Boolean, default=False, server_default=sa.false(), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        sa.Boolean, default=True, server_default=sa.true(), nullable=False
    )
    meta: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)

    parent: Mapped[DutyService | None] = relationship(remote_side="DutyService.id", lazy="noload")


class TimeNorm(UUIDPrimaryKey, Timestamped, Base):
    """Нормативы времени. Значение по умолчанию — 30 секунд (п.2.4 ТЗ)."""

    __tablename__ = "time_norms"
    __table_args__ = (
        sa.UniqueConstraint("category_id", "mode", "action_type", name="time_norms_scope"),
    )

    category_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("incident_categories.id", ondelete="CASCADE"), nullable=True
    )
    mode: Mapped[LessonMode | None] = mapped_column(enum_column(LessonMode), nullable=True)
    action_type: Mapped[ActionType | None] = mapped_column(enum_column(ActionType), nullable=True)
    seconds: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=30)
    comment: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
