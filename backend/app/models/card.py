from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import SoftDelete, Timestamped, UUIDPrimaryKey
from app.db.types import JSONType, enum_column
from app.models.enums import CardOrigin, CardStatus, DifficultyLevel


class CardTemplate(UUIDPrimaryKey, Timestamped, SoftDelete, Base):
    """Описание формы карточки: поля, типы, обязательность, порядок, подсказки."""

    __tablename__ = "card_templates"

    code: Mapped[str] = mapped_column(sa.String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    version: Mapped[int] = mapped_column(sa.Integer, default=1, nullable=False)
    is_default: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    #: [{"code":"address","label":"Адрес","type":"string","required":true,"max_length":255}, ...]
    fields_schema: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)


class IncidentCard(UUIDPrimaryKey, Timestamped, SoftDelete, Base):
    __tablename__ = "incident_cards"
    __table_args__ = (
        sa.Index("ix_incident_cards_origin_status", "origin", "status"),
        sa.Index("ix_incident_cards_category_origin", "category_id", "origin"),
    )

    #: Учебный номер карточки, имитирующий нумерацию системы-112.
    card_no: Mapped[str] = mapped_column(sa.String(32), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("card_templates.id", ondelete="SET NULL"), nullable=True
    )
    scenario_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("scenarios.id", ondelete="SET NULL"), nullable=True, index=True
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("incident_categories.id", ondelete="SET NULL"), nullable=True
    )
    origin: Mapped[CardOrigin] = mapped_column(
        enum_column(CardOrigin), default=CardOrigin.GENERATED, nullable=False
    )
    status: Mapped[CardStatus] = mapped_column(
        enum_column(CardStatus), default=CardStatus.READY, nullable=False
    )
    difficulty: Mapped[DifficultyLevel] = mapped_column(
        enum_column(DifficultyLevel), default=DifficultyLevel.BASIC, nullable=False
    )
    difficulty_weight: Mapped[int] = mapped_column(
        sa.SmallInteger, default=2, server_default="2", nullable=False, index=True
    )

    #: Кто «звонит»: имя, эмоциональное состояние, легенда — используется телефонией и ML.
    caller_profile: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    #: Содержимое карточки, видимое обучающемуся (во втором режиме — заполненная карточка).
    payload: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    #: Эталонное содержимое (для режима заполнения) — заполняется из ScenarioReference.
    expected_payload: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)

    #: Автор карточки: преподаватель или обучающийся (карточки обучающихся, п.2.5).
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    source_attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("card_attempts.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )
    incident_type_code: Mapped[str | None] = mapped_column(sa.String(64), nullable=True, index=True)
    notification_list: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    #: Аудиозапись учебного вызова (MP3/WAV), готовит модуль телефонии.
    audio_path: Mapped[str | None] = mapped_column(sa.String(512), nullable=True)
    time_limit_seconds: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
