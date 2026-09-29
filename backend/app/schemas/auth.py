"""Схемы аутентификации (п.2.3 ТЗ)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class MFAChallenge(BaseModel):
    """Ответ первого шага входа, если у пользователя включён второй фактор."""

    mfa_required: bool = True
    mfa_token: str
    detail: str = "Введите код из приложения-аутентификатора"


class MFAVerifyRequest(BaseModel):
    mfa_token: str
    code: str = Field(min_length=6, max_length=8)


class MFASetupResponse(BaseModel):
    secret: str
    provisioning_uri: str
    detail: str = "Подтвердите код, чтобы включить второй фактор"


class MFAConfirmRequest(BaseModel):
    code: str = Field(min_length=6, max_length=8)


class RefreshRequest(BaseModel):
    refresh_token: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=256)


class CurrentUser(ORMModel):
    id: uuid.UUID
    username: str
    full_name: str
    email: str | None = None
    organization: str | None = None
    position: str | None = None
    status: str
    mfa_enabled: bool
    #: Роль требует второй фактор, но он ещё не привязан.
    mfa_setup_required: bool = False
    roles: list[str] = []
    permissions: list[str] = []
