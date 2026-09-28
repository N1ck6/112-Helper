"""Базовые схемы и общие структуры ответов."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    """Схема чтения из ORM-объекта."""

    model_config = ConfigDict(from_attributes=True)


class MessageResponse(BaseModel):
    detail: str


class HealthResponse(BaseModel):
    status: str
    app: str
    version: str
    environment: str
    database: str
    components: dict[str, Any] = {}
    server_time: datetime
