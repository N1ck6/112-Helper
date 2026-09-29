from __future__ import annotations

from enum import Enum

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

#: dict/list-поля карточек, конфигураций, payload'ов ML.
JSONType = sa.JSON().with_variant(JSONB, "postgresql")

#: Timestamp с таймзоной — все времена храним в UTC.
TimestampType = sa.DateTime(timezone=True)


def enum_column(enum_cls: type[Enum], length: int = 40) -> sa.Enum:
    return sa.Enum(
        enum_cls,
        native_enum=False,
        length=length,
        validate_strings=True,
        values_callable=lambda cls: [member.value for member in cls],
    )
