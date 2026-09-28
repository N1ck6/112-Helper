"""Схемы пользователей, ролей, прав и учебных групп."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import UserStatus
from app.schemas.common import ORMModel


class PermissionRead(ORMModel):
    id: uuid.UUID
    code: str
    name: str
    category: str


class RoleRead(ORMModel):
    id: uuid.UUID
    code: str
    name: str
    description: str | None = None
    is_system: bool
    permissions: list[PermissionRead] = []


class RoleCreate(BaseModel):
    code: str = Field(min_length=2, max_length=32, pattern=r"^[a-z0-9_]+$")
    name: str = Field(min_length=2, max_length=128)
    description: str | None = None
    permission_codes: list[str] = []


class RoleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    permission_codes: list[str] | None = None


class UserBrief(ORMModel):
    id: uuid.UUID
    username: str
    full_name: str
    status: UserStatus


class UserRead(ORMModel):
    id: uuid.UUID
    username: str
    email: str | None = None
    full_name: str
    status: UserStatus
    organization: str | None = None
    position: str | None = None
    mfa_enabled: bool
    is_active: bool
    #: local — пароль проверяется в тренажёре, directory — в каталоге организации.
    auth_source: str = "local"
    external_id: str | None = None
    last_login_at: datetime | None = None
    created_at: datetime
    roles: list[RoleRead] = []


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    full_name: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=256)
    email: str | None = None
    organization: str | None = None
    position: str | None = None
    role_codes: list[str] = Field(default_factory=list, description="admin / teacher / student")


class UserUpdate(BaseModel):
    full_name: str | None = None
    email: str | None = None
    organization: str | None = None
    position: str | None = None
    role_codes: list[str] | None = None


class UserPasswordReset(BaseModel):
    new_password: str = Field(min_length=8, max_length=256)


class UserBlockRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=512)


class GroupRead(ORMModel):
    id: uuid.UUID
    code: str
    name: str
    description: str | None = None
    dds_profile: str | None = None
    curator_id: uuid.UUID | None = None
    is_active: bool
    students: list[UserBrief] = []


class GroupCreate(BaseModel):
    code: str = Field(min_length=2, max_length=32)
    name: str = Field(min_length=2, max_length=255)
    description: str | None = None
    dds_profile: str | None = None
    curator_id: uuid.UUID | None = None


class GroupUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    dds_profile: str | None = None
    curator_id: uuid.UUID | None = None


class GroupMembersRequest(BaseModel):
    student_ids: list[uuid.UUID] = Field(min_length=1)


class DirectorySyncResult(BaseModel):
    """Итог синхронизации с локальной системой управления доступом (п.2.9 ТЗ)."""

    source: str
    dry_run: bool
    total: int
    created: list[str] = []
    updated: list[str] = []
    missing_in_directory: list[str] = []
    #: Логин из каталога занят локальной учётной записью — синхронизация её не трогает.
    conflicts: list[str] = []
