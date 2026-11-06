"""Users, memberships, access rules, tokens, sessions, and the audit log."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from domus.models.base import Base, EntityMixin, IdMixin, IdStr, utcnow


class User(EntityMixin, Base):
    __tablename__ = "user"

    email: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str | None] = mapped_column(String(256), default=None)
    is_active: Mapped[bool] = mapped_column(default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(default=None)


class Membership(EntityMixin, Base):
    """A user's role in one property. Non-admin memberships may expire."""

    __tablename__ = "membership"

    user_id: Mapped[str] = mapped_column(IdStr, ForeignKey("user.id"), index=True)
    property_id: Mapped[str] = mapped_column(IdStr, ForeignKey("property.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    expires_at: Mapped[datetime | None] = mapped_column(default=None)

    __table_args__ = (
        UniqueConstraint("user_id", "property_id"),
        CheckConstraint("role IN ('admin', 'maintainer', 'resident', 'guest')", name="role"),
    )


class AccessRule(EntityMixin, Base):
    """Raises or lowers one role's or one member's access to a building, area, tag, or asset.

    See data-storage-backup.md 2.3.1 and ``domus.services.access``.
    """

    __tablename__ = "access_rule"

    property_id: Mapped[str] = mapped_column(IdStr, ForeignKey("property.id"), index=True)
    scope_type: Mapped[str] = mapped_column(String(16))
    scope_id: Mapped[str] = mapped_column(IdStr)
    subject_type: Mapped[str] = mapped_column(String(16))
    # A role name when subject_type is "role", otherwise a membership id.
    subject: Mapped[str] = mapped_column(String(36))
    level: Mapped[str] = mapped_column(String(16))
    expires_at: Mapped[datetime | None] = mapped_column(default=None)
    note: Mapped[str | None] = mapped_column(Text, default=None)

    __table_args__ = (
        CheckConstraint("scope_type IN ('building', 'area', 'tag', 'asset')", name="scope_type"),
        CheckConstraint("subject_type IN ('role', 'membership')", name="subject_type"),
        CheckConstraint("level IN ('hidden', 'view', 'control', 'manage')", name="level"),
        Index("ix_access_rule_scope", "scope_type", "scope_id"),
    )


class ApiToken(EntityMixin, Base):
    """A personal access token. Only the SHA-256 of the token is stored."""

    __tablename__ = "api_token"

    user_id: Mapped[str] = mapped_column(IdStr, ForeignKey("user.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    # Space-separated scopes: "read", "write", "calendar".
    scopes: Mapped[str] = mapped_column(String(200), default="read")
    expires_at: Mapped[datetime | None] = mapped_column(default=None)
    last_used_at: Mapped[datetime | None] = mapped_column(default=None)


class AuthSession(IdMixin, Base):
    """A browser login session. Never included in backups or exports."""

    __tablename__ = "auth_session"

    user_id: Mapped[str] = mapped_column(IdStr, ForeignKey("user.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime]


class AuditLog(IdMixin, Base):
    """Who changed what. Included in full backups, excluded from partial exports."""

    __tablename__ = "audit_log"

    at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    user_id: Mapped[str | None] = mapped_column(IdStr, default=None)
    property_id: Mapped[str | None] = mapped_column(IdStr, default=None)
    action: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[str | None] = mapped_column(String(32), default=None)
    target_id: Mapped[str | None] = mapped_column(IdStr, default=None)
    diff: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
