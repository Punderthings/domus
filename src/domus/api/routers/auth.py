"""First-run setup, login, logout, current user, and personal access tokens."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from domus.api.deps import CurrentPrincipal, DbSession, active_memberships, get_settings
from domus.api.schemas import (
    LoginIn,
    MembershipOut,
    MeOut,
    SetupIn,
    SetupStatus,
    TokenCreated,
    TokenIn,
    TokenOut,
)
from domus.api.security import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    TOKEN_PREFIX,
    LoginRateLimiter,
    hash_password,
    hash_token,
    new_token,
    verify_password,
)
from domus.config import Settings
from domus.models import ApiToken, AuditLog, AuthSession, Building, Membership, Property, User
from domus.models.enums import Role

router = APIRouter(prefix="/auth", tags=["auth"])

SettingsDep = Annotated[Settings, Depends(get_settings)]


def _start_session(response: Response, db: DbSession, user: User, settings: Settings) -> None:
    raw = new_token()
    now = datetime.now(UTC)
    expires = now + timedelta(days=settings.session_days)
    db.add(AuthSession(user_id=user.id, token_hash=hash_token(raw), expires_at=expires))
    user.last_login_at = now
    max_age = settings.session_days * 86400
    response.set_cookie(
        SESSION_COOKIE,
        raw,
        max_age=max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        new_token(),
        max_age=max_age,
        httponly=False,  # the SPA reads it and echoes it in X-CSRF-Token
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def _me(db: DbSession, user: User) -> MeOut:
    return MeOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        memberships=[MembershipOut.model_validate(m) for m in active_memberships(db, user.id)],
    )


def normalize_email(email: str) -> str:
    return email.strip().lower()


@router.get("/setup")
def setup_status(db: DbSession) -> SetupStatus:
    """Whether the first-run setup (creating the first Admin) is still needed."""
    count = db.scalar(select(func.count()).select_from(User)) or 0
    return SetupStatus(needs_setup=count == 0)


@router.post("/setup", status_code=status.HTTP_201_CREATED)
def setup(body: SetupIn, response: Response, db: DbSession, settings: SettingsDep) -> MeOut:
    """Create the first Admin, plus a property and its primary building on an empty install.

    If properties were imported before setup, the Admin is added to all of them
    and ``property_name`` is not used. Works only once.
    """
    if (db.scalar(select(func.count()).select_from(User)) or 0) > 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "Setup is already complete")
    user = User(
        email=normalize_email(body.email),
        display_name=body.display_name,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    # Data imported before setup (for example the sample home) has no members
    # yet, so the first Admin gets every existing property. Only an empty
    # install gets a new property with its primary building.
    existing = list(db.scalars(select(Property).where(Property.deleted_at.is_(None))))
    if not existing:
        prop = Property(name=body.property_name, timezone=body.timezone)
        db.add(prop)
        db.flush()
        db.add(Building(property_id=prop.id, name="House", kind="house", is_primary=True))
        existing = [prop]
    db.flush()
    for prop in existing:
        db.add_all(
            [
                Membership(user_id=user.id, property_id=prop.id, role=Role.ADMIN.value),
                AuditLog(
                    user_id=user.id,
                    property_id=prop.id,
                    action="setup",
                    target_type="property",
                    target_id=prop.id,
                ),
            ]
        )
    try:
        db.flush()
    except IntegrityError as exc:  # a concurrent setup won the race
        raise HTTPException(status.HTTP_409_CONFLICT, "Setup is already complete") from exc
    _start_session(response, db, user, settings)
    return _me(db, user)


def _limiter(request: Request) -> LoginRateLimiter:
    limiter: LoginRateLimiter = request.app.state.login_limiter
    return limiter


@router.post("/login")
def login(
    body: LoginIn, request: Request, response: Response, db: DbSession, settings: SettingsDep
) -> MeOut:
    email = normalize_email(body.email)
    client = request.client.host if request.client else "?"
    limiter = _limiter(request)
    keys = (f"email:{email}", f"ip:{client}")
    if any(limiter.blocked(k) for k in keys):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed logins; wait")
    user = db.scalar(select(User).where(User.email == email))
    ok = verify_password(user.password_hash if user else None, body.password)
    if user is None or not ok or not user.is_active or user.deleted_at is not None:
        for k in keys:
            limiter.fail(k)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong email or password")
    limiter.reset(f"email:{email}")
    _start_session(response, db, user, settings)
    return _me(db, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: DbSession, _: CurrentPrincipal) -> None:
    raw = request.cookies.get(SESSION_COOKIE)
    if raw:
        row = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(raw)))
        if row is not None:
            db.delete(row)
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


@router.get("/me")
def me(db: DbSession, principal: CurrentPrincipal) -> MeOut:
    return _me(db, principal.user)


@router.get("/tokens")
def list_tokens(db: DbSession, principal: CurrentPrincipal) -> list[TokenOut]:
    rows = db.scalars(
        select(ApiToken)
        .where(ApiToken.user_id == principal.user.id, ApiToken.deleted_at.is_(None))
        .order_by(ApiToken.id)
    )
    return [TokenOut.model_validate(r) for r in rows]


@router.post("/tokens", status_code=status.HTTP_201_CREATED)
def create_token(body: TokenIn, db: DbSession, principal: CurrentPrincipal) -> TokenCreated:
    """Create a personal access token. It inherits the owner's roles."""
    if principal.via != "session":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tokens can only be created from a login")
    raw = new_token(TOKEN_PREFIX)
    row = ApiToken(
        user_id=principal.user.id,
        name=body.name,
        token_hash=hash_token(raw),
        scopes=" ".join(sorted(set(body.scopes))),
        expires_at=body.expires_at,
        created_by=principal.user.id,
    )
    db.add(row)
    db.flush()
    return TokenCreated(**TokenOut.model_validate(row).model_dump(), token=raw)


@router.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_token(token_id: str, db: DbSession, principal: CurrentPrincipal) -> None:
    row = db.get(ApiToken, token_id)
    if row is None or row.user_id != principal.user.id or row.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    row.deleted_at = datetime.now(UTC)
