"""Пользователи, роли, права, учебные группы (п.2.2, п.2.3 ТЗ)."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import SoftDelete, Timestamped, UUIDPrimaryKey
from app.db.types import JSONType, TimestampType, enum_column
from app.models.enums import UserStatus

role_permissions = sa.Table(
    "role_permissions",
    Base.metadata,
    sa.Column("role_id", sa.Uuid(as_uuid=True), sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    sa.Column(
        "permission_id",
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("permissions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

user_roles = sa.Table(
    "user_roles",
    Base.metadata,
    sa.Column("user_id", sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    sa.Column("role_id", sa.Uuid(as_uuid=True), sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    sa.Column("assigned_at", TimestampType, server_default=sa.func.now(), nullable=False),
)

group_members = sa.Table(
    "group_members",
    Base.metadata,
    sa.Column(
        "group_id", sa.Uuid(as_uuid=True), sa.ForeignKey("study_groups.id", ondelete="CASCADE"), primary_key=True
    ),
    sa.Column("user_id", sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    sa.Column("joined_at", TimestampType, server_default=sa.func.now(), nullable=False),
)


class Permission(UUIDPrimaryKey, Base):
    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(sa.String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    category: Mapped[str] = mapped_column(sa.String(64), nullable=False, default="Прочее")
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)


class Role(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "roles"

    code: Mapped[str] = mapped_column(sa.String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    #: Системные роли (admin/teacher/student) нельзя удалить — только расширить права.
    is_system: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)

    permissions: Mapped[list[Permission]] = relationship(
        secondary=role_permissions, lazy="selectin", order_by=Permission.code
    )


class User(UUIDPrimaryKey, Timestamped, SoftDelete, Base):
    __tablename__ = "users"
    __table_args__ = (sa.Index("ix_users_status_active", "status", "is_active"),)

    username: Mapped[str] = mapped_column(sa.String(64), unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    full_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    status: Mapped[UserStatus] = mapped_column(
        enum_column(UserStatus), default=UserStatus.ACTIVE, nullable=False
    )

    #: Служба/организация обучающегося — нужна для профильной выдачи событий (п.10 ТЗ).
    organization: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    position: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)

    # --- второй фактор (многоуровневая аутентификация, п.2.3)
    mfa_enabled: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    mfa_secret: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)

    # --- защита от подбора пароля
    failed_login_count: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    password_changed_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)

    external_id: Mapped[str | None] = mapped_column(sa.String(128), nullable=True, index=True)
    #: Где проверяется пароль: local — в нашей БД, directory — в каталоге организации.
    auth_source: Mapped[str] = mapped_column(sa.String(16), default="local", nullable=False)
    directory_synced_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)

    #: Настройки интерфейса/АРМ конкретного пользователя (XML/JSON-конфигурация рабочего места).
    preferences: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)

    roles: Mapped[list[Role]] = relationship(secondary=user_roles, lazy="selectin")
    groups: Mapped[list[StudyGroup]] = relationship(
        secondary=group_members, back_populates="students", lazy="noload"
    )

    # ------------------------------------------------------------------ helpers
    @property
    def role_codes(self) -> list[str]:
        return [role.code for role in self.roles]

    @property
    def permission_codes(self) -> set[str]:
        return {perm.code for role in self.roles for perm in role.permissions}

    def has_permission(self, code: str) -> bool:
        return code in self.permission_codes

    def has_role(self, code: str) -> bool:
        return code in self.role_codes


class StudyGroup(UUIDPrimaryKey, Timestamped, SoftDelete, Base):
    __tablename__ = "study_groups"

    code: Mapped[str] = mapped_column(sa.String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    curator_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    dds_profile: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)

    students: Mapped[list[User]] = relationship(
        secondary=group_members, back_populates="groups", lazy="selectin"
    )
