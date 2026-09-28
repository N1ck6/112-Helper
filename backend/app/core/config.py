from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import unquote, urlsplit

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ------------------------------------------------------------------ приложение
    APP_NAME: str = "Тренажёр оператора ДДС-112 — Backend"
    APP_VERSION: str = "0.1.0"
    APP_ENV: Literal["local", "dev", "test", "prod"] = "local"
    DEBUG: bool = True
    ENABLE_DOCS: bool = True
    API_V1_PREFIX: str = "/api/v1"
    TIMEZONE: str = "Europe/Moscow"
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    # ------------------------------------------------------------------ база данных
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "dds112"
    POSTGRES_PASSWORD: str = "dds112"
    POSTGRES_DB: str = "dds112"
    DATABASE_URL: str | None = None
    TEST_DATABASE_URL: str | None = None

    # Пул рассчитан на п.2.8: ≥20 одновременных учебных сессий и 100 пользователей.
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 30
    DB_POOL_TIMEOUT: int = 10
    DB_POOL_RECYCLE: int = 1800
    DB_ECHO: bool = False
    DB_STATEMENT_TIMEOUT_MS: int = 15_000

    # ------------------------------------------------------------------ безопасность
    SECRET_KEY: str = "dev-secret-change-me-0123456789abcdef"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_TTL_MINUTES: int = 30
    REFRESH_TOKEN_TTL_DAYS: int = 7
    MFA_CHALLENGE_TTL_MINUTES: int = 5
    MFA_REQUIRED_ROLES: list[str] = []
    PASSWORD_MIN_LENGTH: int = 8
    #: Стоимость bcrypt: выше — надёжнее и дороже по процессору (см. security.hash_password).
    PASSWORD_HASH_ROUNDS: int = 12
    MAX_FAILED_LOGINS: int = 5
    LOCKOUT_MINUTES: int = 15
    # п.9 ТЗ: журналы безопасности хранятся не менее 6 месяцев.
    SECURITY_LOG_RETENTION_DAYS: int = 200
    #: Системный журнал (технические сообщения) живёт меньше — он объёмный.
    SYSTEM_LOG_RETENTION_DAYS: int = 90
    #: Как часто выполняются регламентные задачи очистки и проверки карточек, часов.
    MAINTENANCE_INTERVAL_HOURS: int = 6

    # ------------------------------------------------------------------ учебный процесс
    DEFAULT_CARD_TIME_LIMIT_SECONDS: int = 30  # п.2.4: норматив по умолчанию — 30 сек
    DEFAULT_MAX_ERRORS: int = 3
    SESSION_RECOVERY_GRACE_SECONDS: int = 30  # п.2.8: сбой сети до 30 сек без потери данных
    MAX_CONCURRENT_SESSIONS: int = 20
    REPORT_TIMEOUT_SECONDS: int = 30  # п.2.8: аналитический отчёт ≤30 сек
    CARD_ACTION_WORK_LIMIT_SECONDS: int = 180
    CARD_STREAM_WINDOW: int = 3
    #: Пауза между появлением новых карточек в потоке, секунд.
    CARD_STREAM_INTERVAL_SECONDS: int = 20
    CARD_COMPLETION_HOURS: int = 48
    #: Порог зачёта аттестационного мероприятия, баллы из 100.
    ATTESTATION_PASS_SCORE: float = 70.0

    SCORE_WEIGHT_CORRECTNESS: float = 0.45  # правильность заполнения полей
    SCORE_WEIGHT_TIME: float = 0.20  # время реакции и исполнения
    SCORE_WEIGHT_GRAMMAR: float = 0.15  # грамматика и опечатки
    SCORE_WEIGHT_SEQUENCE: float = 0.20  # последовательность действий
    SCORE_ADDRESS_ERROR_FACTOR: float = 3.0
    #: Шкала сложности заданий: заказчик просил веса 1–10.
    DIFFICULTY_WEIGHT_MIN: int = 1
    DIFFICULTY_WEIGHT_MAX: int = 10
    ADAPTIVE_STEP: int = 1
    ADAPTIVE_RAISE_SCORE: float = 85.0
    ADAPTIVE_LOWER_SCORE: float = 55.0

    # ------------------------------------------------------------------ интеграции
    ML_SERVICE_URL: str = "http://localhost:8100"
    ML_USE_STUB: bool = True
    ML_TIMEOUT_SECONDS: float = 20.0
    TELEPHONY_SERVICE_URL: str = "http://localhost:8200"
    TELEPHONY_USE_STUB: bool = True
    TELEPHONY_WEBHOOK_TOKEN: str = "dev-telephony-token"
    DIRECTORY_URL: str | None = None  # локальная система управления доступом (LDAP-шлюз)
    MONITORING_ENABLED: bool = True
    OUTBOX_MAX_ATTEMPTS: int = 10
    OUTBOX_POLL_SECONDS: int = 5

    # ------------------------------------------------------------------ файлы
    STORAGE_DIR: Path = Field(default=Path("var"))
    MAX_UPLOAD_MB: int = 50

    BACKUP_ENABLED: bool = False
    BACKUP_INTERVAL_HOURS: int = 24  # п.9 ТЗ: не реже одного раза в сутки
    BACKUP_KEEP: int = 14  # сколько последних копий хранить
    BACKUP_PG_DUMP: str = "pg_dump"  # путь к утилите, если её нет в PATH

    # ------------------------------------------------------------------ производные
    @computed_field  # type: ignore[prop-decorator]
    @property
    def sqlalchemy_dsn(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def storage_path(self) -> Path:
        path = self.STORAGE_DIR
        if not path.is_absolute():
            path = BASE_DIR / path
        return path

    @property
    def uploads_path(self) -> Path:
        return self.storage_path / "uploads"

    @property
    def reports_path(self) -> Path:
        return self.storage_path / "reports"

    @property
    def certificates_path(self) -> Path:
        return self.storage_path / "certificates"

    @property
    def backups_path(self) -> Path:
        return self.storage_path / "backups"

    @property
    def libpq_dsn(self) -> str:
        parts = urlsplit(self.sqlalchemy_dsn)
        host = parts.hostname or self.POSTGRES_HOST
        port = parts.port or self.POSTGRES_PORT
        user = parts.username or self.POSTGRES_USER
        database = (parts.path or "").lstrip("/") or self.POSTGRES_DB
        return f"postgresql://{user}@{host}:{port}/{database}"

    @property
    def libpq_password(self) -> str:
        """Пароль для PGPASSWORD: из DATABASE_URL, если он задан, иначе из POSTGRES_PASSWORD."""
        parts = urlsplit(self.sqlalchemy_dsn)
        if parts.password:
            return unquote(parts.password)
        return self.POSTGRES_PASSWORD

    def ensure_storage(self) -> None:
        for path in (self.uploads_path, self.reports_path, self.certificates_path, self.backups_path):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
