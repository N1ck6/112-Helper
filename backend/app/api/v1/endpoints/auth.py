"""Аутентификация и профиль (п.2.3)."""

from __future__ import annotations

from fastapi import APIRouter, Request, status

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.schemas.auth import (
    CurrentUser as CurrentUserSchema,
)
from app.schemas.auth import (
    LoginRequest,
    MFAChallenge,
    MFAConfirmRequest,
    MFASetupResponse,
    MFAVerifyRequest,
    PasswordChangeRequest,
    RefreshRequest,
    TokenPair,
)
from app.schemas.common import MessageResponse
from app.services.auth import AuthService

router = APIRouter(prefix="/auth", tags=["Аутентификация"])


@router.post(
    "/login",
    response_model=TokenPair | MFAChallenge,
    summary="Вход в систему",
    description=(
        "Первый шаг входа. Если у пользователя включён второй фактор, возвращается "
        "`mfa_token`, который нужно подтвердить на `/auth/mfa/verify`."
    ),
)
async def login(data: LoginRequest, session: SessionDep, request: Request):
    return await AuthService(session).login(data.username, data.password, request)


@router.post("/mfa/verify", response_model=TokenPair, summary="Подтверждение второго фактора")
async def verify_mfa(data: MFAVerifyRequest, session: SessionDep, request: Request) -> TokenPair:
    return await AuthService(session).verify_mfa(data.mfa_token, data.code, request)


@router.post("/refresh", response_model=TokenPair, summary="Обновление access-токена")
async def refresh(data: RefreshRequest, session: SessionDep) -> TokenPair:
    return await AuthService(session).refresh(data.refresh_token)


@router.post("/logout", response_model=MessageResponse, summary="Выход из системы")
async def logout(user: CurrentUser, session: SessionDep, request: Request) -> MessageResponse:
    await AuthService(session).logout(user, request)
    return MessageResponse(detail="Выход выполнен")


@router.get("/me", response_model=CurrentUserSchema, summary="Текущий пользователь и его права")
async def me(user: CurrentUser) -> CurrentUserSchema:
    required_roles = {role.lower() for role in settings.MFA_REQUIRED_ROLES}
    return CurrentUserSchema(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        email=user.email,
        organization=user.organization,
        position=user.position,
        status=user.status.value,
        mfa_enabled=user.mfa_enabled,
        mfa_setup_required=(
            bool(required_roles & {code.lower() for code in user.role_codes}) and not user.mfa_enabled
        ),
        roles=user.role_codes,
        permissions=sorted(user.permission_codes),
    )


@router.post(
    "/password",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Смена собственного пароля",
)
async def change_password(
    data: PasswordChangeRequest, user: CurrentUser, session: SessionDep, request: Request
) -> MessageResponse:
    await AuthService(session).change_password(user, data.current_password, data.new_password, request)
    return MessageResponse(detail="Пароль изменён")


@router.post("/mfa/setup", response_model=MFASetupResponse, summary="Инициализация второго фактора")
async def setup_mfa(user: CurrentUser, session: SessionDep) -> MFASetupResponse:
    return await AuthService(session).setup_mfa(user)


@router.post("/mfa/confirm", response_model=MessageResponse, summary="Включение второго фактора")
async def confirm_mfa(
    data: MFAConfirmRequest, user: CurrentUser, session: SessionDep, request: Request
) -> MessageResponse:
    await AuthService(session).confirm_mfa(user, data.code, request)
    return MessageResponse(detail="Второй фактор включён")
