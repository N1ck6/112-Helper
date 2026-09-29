"""Аутентификация: вход, второй фактор, обновление токенов, смена пароля (п.2.3)."""

from __future__ import annotations

from datetime import timedelta

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AuthenticationError, IntegrationError, PermissionDeniedError
from app.core.security import (
    create_access_token,
    create_mfa_token,
    create_refresh_token,
    decode_token,
    hash_password,
    new_totp_secret,
    totp_provisioning_uri,
    utcnow,
    validate_password_strength,
    verify_password,
    verify_totp,
)
from app.db.session import session_scope
from app.integrations.directory import get_directory_client
from app.models.enums import AuditAction, UserStatus
from app.models.user import User
from app.repositories.users import UserRepository
from app.schemas.auth import MFAChallenge, MFASetupResponse, TokenPair
from app.services.audit import AuditService


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.audit = AuditService(session)

    # ------------------------------------------------------------------- вход
    async def login(
        self, username: str, password: str, request: Request | None = None
    ) -> TokenPair | MFAChallenge:
        user = await self.users.by_username(username)

        if user is not None and user.auth_source == "directory":
            return await self._login_via_directory(user, password, request)

        if user is None or not verify_password(password, user.password_hash):
            await self._reject_login(username, "Неверный логин или пароль", request)
            raise AuthenticationError("Неверный логин или пароль", code="invalid_credentials")

        self._ensure_can_login(user)

        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = utcnow()

        return await self._after_first_factor(user, "Вход выполнен", request)

    async def _after_first_factor(
        self, user: User, summary: str, request: Request | None
    ) -> TokenPair | MFAChallenge:
        if user.mfa_enabled and user.mfa_secret:
            await self.audit.log(
                AuditAction.LOGIN,
                actor=user,
                summary="Первый фактор пройден, требуется код подтверждения",
                request=request,
            )
            return MFAChallenge(mfa_token=create_mfa_token(user.id))

        if self._mfa_required_by_role(user):
            raise PermissionDeniedError(
                "Для этой роли обязателен второй фактор. Настройте его через /auth/mfa/setup",
                code="mfa_setup_required",
            )

        await self.audit.log(AuditAction.LOGIN, actor=user, summary=summary, request=request)
        return self._issue(user, mfa_passed=False)

    async def _login_via_directory(
        self, user: User, password: str, request: Request | None = None
    ) -> TokenPair | MFAChallenge:
        """Вход пользователя, заведённого в локальной системе управления доступом."""
        client = get_directory_client()
        try:
            profile = await client.authenticate(user.username, password)
        except IntegrationError as exc:
            await self._reject_login(
                user.username, f"Каталог доступа недоступен: {exc}", request, count_failure=False
            )
            raise AuthenticationError(
                "Система управления доступом недоступна, повторите попытку позже",
                code="directory_unavailable",
            ) from exc

        if profile is None:
            await self._reject_login(
                user.username, "Каталог доступа отклонил учётные данные", request
            )
            raise AuthenticationError("Неверный логин или пароль", code="invalid_credentials")

        self._ensure_can_login(user)
        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = utcnow()
        return await self._after_first_factor(
            user, f"Вход через каталог доступа ({client.name})", request
        )

    async def verify_mfa(self, mfa_token: str, code: str, request: Request | None = None) -> TokenPair:
        payload = decode_token(mfa_token, expected_type="mfa")
        user = await self.users.get_with_roles(_as_uuid(payload.sub))
        if user is None:
            raise AuthenticationError("Пользователь не найден", code="user_not_found")
        self._ensure_can_login(user)

        if not verify_totp(user.mfa_secret or "", code):
            await self._reject_login(user.username, "Неверный код второго фактора", request)
            raise AuthenticationError("Неверный код подтверждения", code="invalid_mfa_code")

        user.failed_login_count = 0
        user.last_login_at = utcnow()
        await self.audit.log(
            AuditAction.LOGIN, actor=user, summary="Вход выполнен (два фактора)", request=request
        )
        return self._issue(user, mfa_passed=True)

    async def refresh(self, refresh_token: str) -> TokenPair:
        payload = decode_token(refresh_token, expected_type="refresh")
        user = await self.users.get_with_roles(_as_uuid(payload.sub))
        if user is None:
            raise AuthenticationError("Пользователь не найден", code="user_not_found")
        self._ensure_can_login(user)
        return self._issue(user, mfa_passed=user.mfa_enabled)

    async def logout(self, user: User, request: Request | None = None) -> None:
        await self.audit.log(AuditAction.LOGOUT, actor=user, summary="Выход из системы", request=request)

    # --------------------------------------------------------------- пароль/MFA
    async def change_password(
        self, user: User, current_password: str, new_password: str, request: Request | None = None
    ) -> None:
        if not verify_password(current_password, user.password_hash):
            raise AuthenticationError("Текущий пароль указан неверно", code="invalid_credentials")
        validate_password_strength(new_password)
        user.password_hash = hash_password(new_password)
        user.password_changed_at = utcnow()
        await self.audit.log(
            AuditAction.UPDATE,
            actor=user,
            object_type="user",
            object_id=user.id,
            summary="Смена пароля",
            request=request,
            is_security=True,
        )

    async def setup_mfa(self, user: User) -> MFASetupResponse:
        secret = new_totp_secret()
        user.mfa_secret = secret
        user.mfa_enabled = False  # включается только после подтверждения кода
        await self.session.flush()
        return MFASetupResponse(secret=secret, provisioning_uri=totp_provisioning_uri(secret, user.username))

    async def confirm_mfa(self, user: User, code: str, request: Request | None = None) -> None:
        if not user.mfa_secret:
            raise AuthenticationError("Второй фактор не инициализирован", code="mfa_not_initialized")
        if not verify_totp(user.mfa_secret, code):
            raise AuthenticationError("Неверный код подтверждения", code="invalid_mfa_code")
        user.mfa_enabled = True
        await self.audit.log(
            AuditAction.UPDATE,
            actor=user,
            object_type="user",
            object_id=user.id,
            summary="Включён второй фактор аутентификации",
            request=request,
            is_security=True,
        )

    # ------------------------------------------------------------------ helpers
    def _issue(self, user: User, *, mfa_passed: bool) -> TokenPair:
        return TokenPair(
            access_token=create_access_token(
                user.id, user.role_codes, sorted(user.permission_codes), mfa_passed=mfa_passed
            ),
            refresh_token=create_refresh_token(user.id),
            expires_in=settings.ACCESS_TOKEN_TTL_MINUTES * 60,
        )

    def _ensure_can_login(self, user: User) -> None:
        if user.status == UserStatus.BLOCKED or not user.is_active:
            raise PermissionDeniedError("Учётная запись заблокирована", code="account_blocked")
        if user.locked_until and user.locked_until > utcnow():
            raise PermissionDeniedError(
                f"Вход временно заблокирован до {user.locked_until:%H:%M:%S} (UTC)",
                code="account_locked",
            )

    def _mfa_required_by_role(self, user: User) -> bool:
        required = {code.lower() for code in settings.MFA_REQUIRED_ROLES}
        return bool(required & {code.lower() for code in user.role_codes})

    async def _reject_login(
        self,
        username: str,
        summary: str,
        request: Request | None,
        *,
        count_failure: bool = True,
    ) -> None:
        async with session_scope() as session:
            users = UserRepository(session)
            target = await users.by_username(username)
            if target is not None and count_failure:
                target.failed_login_count += 1
                if target.failed_login_count >= settings.MAX_FAILED_LOGINS:
                    target.locked_until = utcnow() + timedelta(minutes=settings.LOCKOUT_MINUTES)
                    target.failed_login_count = 0
            await AuditService(session).log(
                AuditAction.LOGIN_FAILED,
                actor=target,
                actor_username=username,
                summary=summary,
                request=request,
                result="failure",
            )


def _as_uuid(value: str):
    import uuid as _uuid

    try:
        return _uuid.UUID(value)
    except ValueError as exc:
        raise AuthenticationError("Некорректный идентификатор в токене", code="invalid_token") from exc
