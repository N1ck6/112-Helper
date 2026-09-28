"""Зависимости FastAPI: сессия БД, текущий пользователь, проверка прав (RBAC)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.core.logging import set_request_context
from app.core.pagination import PageParams
from app.core.permissions import Perm, RoleCode
from app.core.security import decode_token
from app.db.session import get_session
from app.models.enums import UserStatus
from app.models.user import User
from app.repositories.users import UserRepository

bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token")

SessionDep = Annotated[AsyncSession, Depends(get_session)]
PageDep = Annotated[PageParams, Depends()]


async def get_current_user(
    request: Request,
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> User:
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("Не передан токен доступа")

    payload = decode_token(credentials.credentials, expected_type="access")
    try:
        user_id = uuid.UUID(payload.sub)
    except ValueError as exc:
        raise AuthenticationError("Некорректный токен", code="invalid_token") from exc

    user = await UserRepository(session).get_with_roles(user_id)
    if user is None:
        raise AuthenticationError("Пользователь не найден", code="user_not_found")
    if user.status is UserStatus.BLOCKED or not user.is_active:
        raise PermissionDeniedError("Учётная запись заблокирована", code="account_blocked")

    request.state.user = user
    set_request_context(getattr(request.state, "request_id", None), str(user.id))
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require(*permissions: Perm | str, any_of: bool = False):
    codes = [str(p) for p in permissions]

    async def _dependency(user: CurrentUser) -> User:
        granted = user.permission_codes
        ok = bool(granted & set(codes)) if any_of else all(code in granted for code in codes)
        if not ok:
            missing = ", ".join(sorted(set(codes) - granted))
            raise PermissionDeniedError(
                f"Недостаточно прав. Требуется: {missing}", details={"required": codes}
            )
        return user

    return _dependency


def require_role(*roles: RoleCode | str):
    codes = [str(r) for r in roles]

    async def _dependency(user: CurrentUser) -> User:
        if not set(codes) & set(user.role_codes):
            raise PermissionDeniedError(f"Операция доступна только для ролей: {', '.join(codes)}")
        return user

    return _dependency


AdminUser = Annotated[User, Depends(require_role(RoleCode.ADMIN))]
TeacherUser = Annotated[User, Depends(require(Perm.LESSONS_MANAGE))]
StudentUser = Annotated[User, Depends(require(Perm.LESSONS_PARTICIPATE))]
