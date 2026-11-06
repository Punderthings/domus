"""Request dependencies: database session, authentication, CSRF, and property access.

Every endpoint that touches property data goes through ``PropertyContext``, so
role and access-rule checks live in one place (master plan section 2).
"""

from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from domus.api.security import (
    CSRF_COOKIE,
    CSRF_HEADER,
    SESSION_COOKIE,
    TOKEN_PREFIX,
    hash_token,
    tokens_equal,
)
from domus.config import Settings
from domus.models import ApiToken, AuthSession, Membership, User
from domus.models.enums import AccessLevel, Role
from domus.services.access import ROLE_RANK, PropertyAccess, Subject, at_least

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_db(request: Request) -> Generator[Session]:
    """One session per request; commits if the endpoint returns normally."""
    factory: sessionmaker[Session] = request.app.state.session_factory
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


DbSession = Annotated[Session, Depends(get_db)]


@dataclass
class Principal:
    """The authenticated caller."""

    user: User
    via: str  # "session" or "token"
    scopes: frozenset[str] = frozenset({"read", "write"})


def _unauthorized() -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _from_session_cookie(request: Request, db: Session, now: datetime) -> Principal | None:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    row = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(raw)))
    if row is None or row.expires_at <= now:
        return None
    user = db.get(User, row.user_id)
    if user is None or not user.is_active or user.deleted_at is not None:
        return None
    if request.method in UNSAFE_METHODS:
        cookie = request.cookies.get(CSRF_COOKIE, "")
        header = request.headers.get(CSRF_HEADER, "")
        if not cookie or not header or not tokens_equal(cookie, header):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF token missing or invalid")
    return Principal(user=user, via="session")


def token_principal(db: Session, raw: str, now: datetime) -> Principal | None:
    if not raw.startswith(TOKEN_PREFIX):
        return None
    row = db.scalar(select(ApiToken).where(ApiToken.token_hash == hash_token(raw)))
    if row is None or row.deleted_at is not None:
        return None
    if row.expires_at is not None and row.expires_at <= now:
        return None
    user = db.get(User, row.user_id)
    if user is None or not user.is_active or user.deleted_at is not None:
        return None
    row.last_used_at = now
    return Principal(user=user, via="token", scopes=frozenset(row.scopes.split()))


def _from_bearer(request: Request, db: Session, now: datetime) -> Principal | None:
    header = request.headers.get("authorization", "")
    scheme, _, raw = header.partition(" ")
    if scheme.lower() != "bearer" or not raw:
        return None
    principal = token_principal(db, raw.strip(), now)
    if principal is None:
        raise _unauthorized()
    needed = "write" if request.method in UNSAFE_METHODS else "read"
    if needed not in principal.scopes:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Token lacks the {needed!r} scope")
    return principal


def optional_principal(request: Request, db: DbSession) -> Principal | None:
    now = datetime.now(UTC)
    return _from_bearer(request, db, now) or _from_session_cookie(request, db, now)


def current_principal(
    principal: Annotated[Principal | None, Depends(optional_principal)],
) -> Principal:
    if principal is None:
        raise _unauthorized()
    return principal


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


def active_membership(db: Session, user_id: str, property_id: str) -> Membership | None:
    row = db.scalar(
        select(Membership).where(
            Membership.user_id == user_id,
            Membership.property_id == property_id,
            Membership.deleted_at.is_(None),
        )
    )
    if row is None:
        return None
    if row.expires_at is not None and row.expires_at <= datetime.now(UTC):
        return None
    return row


def active_memberships(db: Session, user_id: str) -> list[Membership]:
    now = datetime.now(UTC)
    rows = db.scalars(
        select(Membership).where(Membership.user_id == user_id, Membership.deleted_at.is_(None))
    ).all()
    return [m for m in rows if m.expires_at is None or m.expires_at > now]


class PropertyContext:
    """The caller's role and access checks inside one property."""

    def __init__(self, db: Session, principal: Principal, membership: Membership) -> None:
        self.db = db
        self.principal = principal
        self.membership = membership
        self.role = Role(membership.role)
        self.property_id = membership.property_id
        self.access = PropertyAccess(db, self.property_id, Subject(self.role, membership.id))

    def refresh_access(self) -> None:
        """Drop cached lookups after a write that moves or re-tags items."""
        self.access = PropertyAccess(self.db, self.property_id, self.access.subject)

    @property
    def user_id(self) -> str:
        return self.principal.user.id

    @property
    def is_guest(self) -> bool:
        return self.role is Role.GUEST

    @property
    def is_admin(self) -> bool:
        return self.role is Role.ADMIN

    def has_role(self, minimum: Role) -> bool:
        return ROLE_RANK[self.role] >= ROLE_RANK[minimum]

    def require_role(self, minimum: Role) -> None:
        if not self.has_role(minimum):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires the {minimum.value} role")

    def require_level(self, level: AccessLevel, minimum: AccessLevel) -> None:
        """Raise 404 for hidden items (don't reveal they exist), 403 otherwise."""
        if level is AccessLevel.HIDDEN:
            raise not_found()
        if not at_least(level, minimum):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires {minimum.value} access")


def not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


def property_context(db: Session, principal: Principal, property_id: str | None) -> PropertyContext:
    """Resolve the property for a request.

    With no ``property_id``, a user with exactly one membership gets that property.
    A property the caller is not a member of looks the same as one that doesn't exist.
    """
    if property_id is None:
        memberships = active_memberships(db, principal.user.id)
        if len(memberships) != 1:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "property_id is required for this account"
            )
        return PropertyContext(db, principal, memberships[0])
    membership = active_membership(db, principal.user.id, property_id)
    if membership is None:
        raise not_found()
    return PropertyContext(db, principal, membership)
