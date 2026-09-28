from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import bcrypt
import jwt
import pyotp
from pydantic import BaseModel

from app.core.config import settings
from app.core.exceptions import AuthenticationError

TokenType = Literal["access", "refresh", "mfa"]
_BCRYPT_MAX_BYTES = 72


class TokenPayload(BaseModel):
    sub: str
    typ: TokenType
    jti: str
    exp: int
    iat: int
    roles: list[str] = []
    permissions: list[str] = []
    mfa_passed: bool = False


def utcnow() -> datetime:
    return datetime.now(tz=UTC)


# --------------------------------------------------------------------- пароли
def _prepare(password: str) -> bytes:
    """bcrypt работает максимум с 72 байтами — длинные пароли предварительно хешируем."""
    raw = password.encode("utf-8")
    if len(raw) > _BCRYPT_MAX_BYTES:
        raw = hashlib.sha256(raw).hexdigest().encode("ascii")
    return raw


def hash_password(password: str) -> str:
    rounds = max(10, min(15, settings.PASSWORD_HASH_ROUNDS))
    return bcrypt.hashpw(_prepare(password), bcrypt.gensalt(rounds=rounds)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_prepare(password), password_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False


def validate_password_strength(password: str) -> None:
    if len(password) < settings.PASSWORD_MIN_LENGTH:
        raise AuthenticationError(
            f"Пароль должен содержать не менее {settings.PASSWORD_MIN_LENGTH} символов",
            code="weak_password",
            status_code=422,
        )
    if password.isdigit() or password.isalpha():
        raise AuthenticationError(
            "Пароль должен содержать буквы и цифры", code="weak_password", status_code=422
        )


# ----------------------------------------------------------------------- JWT
def _encode(subject: str, typ: TokenType, ttl: timedelta, **extra: Any) -> str:
    now = utcnow()
    payload: dict[str, Any] = {
        "sub": subject,
        "typ": typ,
        "jti": uuid.uuid4().hex,
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
        **extra,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(
    user_id: uuid.UUID | str,
    roles: list[str],
    permissions: list[str],
    *,
    mfa_passed: bool = False,
) -> str:
    return _encode(
        str(user_id),
        "access",
        timedelta(minutes=settings.ACCESS_TOKEN_TTL_MINUTES),
        roles=roles,
        permissions=permissions,
        mfa_passed=mfa_passed,
    )


def create_refresh_token(user_id: uuid.UUID | str) -> str:
    return _encode(str(user_id), "refresh", timedelta(days=settings.REFRESH_TOKEN_TTL_DAYS))


def create_mfa_token(user_id: uuid.UUID | str) -> str:
    return _encode(str(user_id), "mfa", timedelta(minutes=settings.MFA_CHALLENGE_TTL_MINUTES))


def decode_token(token: str, expected_type: TokenType | None = None) -> TokenPayload:
    try:
        raw = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Срок действия токена истёк", code="token_expired") from exc
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Некорректный токен доступа", code="invalid_token") from exc

    payload = TokenPayload.model_validate(raw)
    if expected_type and payload.typ != expected_type:
        raise AuthenticationError("Неверный тип токена", code="invalid_token_type")
    return payload


# ---------------------------------------------------------------- второй фактор
def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_provisioning_uri(secret: str, username: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name="ДДС-112 Тренажёр")


def verify_totp(secret: str, code: str) -> bool:
    if not secret or not code:
        return False
    return pyotp.TOTP(secret).verify(code.strip(), valid_window=1)


# --------------------------------------------------------- прочие утилиты
def new_opaque_token(nbytes: int = 32) -> str:
    """Токен для возобновления учебной сессии после сетевого сбоя (п.2.8)."""
    return secrets.token_urlsafe(nbytes)


def constant_time_equals(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode(), right.encode())
