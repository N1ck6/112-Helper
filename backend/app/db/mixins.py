"""Примеси для моделей: идентификатор и отметки времени."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.types import TimestampType


class UUIDPrimaryKey:
    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(
        TimestampType, server_default=sa.func.now(), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        TimestampType, server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False
    )


class SoftDelete:
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
