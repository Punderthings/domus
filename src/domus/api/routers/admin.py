"""Members and access rules. Admin only; every change is written to the audit log."""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from domus.api.common import apply_update, audit, bad_request
from domus.api.deps import CurrentPrincipal, DbSession, PropertyContext, not_found, property_context
from domus.api.routers.auth import normalize_email
from domus.api.schemas import (
    AccessRuleIn,
    AccessRuleOut,
    MemberIn,
    MemberOut,
    MemberUpdate,
    Page,
)
from domus.api.security import hash_password
from domus.models import AccessRule, Area, Asset, Building, Membership, Tag, User
from domus.models.enums import Role, ScopeType, SubjectType

router = APIRouter(tags=["admin"])

SCOPE_MODELS: dict[str, type[Building | Area | Tag | Asset]] = {
    ScopeType.BUILDING.value: Building,
    ScopeType.AREA.value: Area,
    ScopeType.TAG.value: Tag,
    ScopeType.ASSET.value: Asset,
}


def _admin(db: DbSession, principal: CurrentPrincipal, property_id: str) -> PropertyContext:
    ctx = property_context(db, principal, property_id)
    ctx.require_role(Role.ADMIN)
    return ctx


def _member_out(m: Membership, user: User) -> MemberOut:
    return MemberOut(
        id=m.id,
        property_id=m.property_id,
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=m.role,
        expires_at=m.expires_at,
    )


@router.get("/properties/{property_id}/members")
def list_members(property_id: str, db: DbSession, principal: CurrentPrincipal) -> Page[MemberOut]:
    _admin(db, principal, property_id)
    rows = db.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.property_id == property_id, Membership.deleted_at.is_(None))
        .order_by(Membership.id)
    )
    return Page(items=[_member_out(m, u) for m, u in rows])


@router.post("/properties/{property_id}/members", status_code=status.HTTP_201_CREATED)
def add_member(
    property_id: str, body: MemberIn, db: DbSession, principal: CurrentPrincipal
) -> MemberOut:
    """Add a member, creating a local account if the email is new."""
    ctx = _admin(db, principal, property_id)
    if body.role == Role.ADMIN.value and body.expires_at is not None:
        raise bad_request("admin memberships cannot expire")
    email = normalize_email(body.email)
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(
            email=email,
            display_name=body.display_name,
            password_hash=hash_password(body.password),
            created_by=ctx.user_id,
        )
        db.add(user)
        db.flush()
    existing = db.scalar(
        select(Membership).where(
            Membership.user_id == user.id, Membership.property_id == property_id
        )
    )
    if existing is not None and existing.deleted_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Already a member")
    if existing is not None:  # re-adding someone who was removed
        m = existing
        m.deleted_at = None
        m.role = body.role
        m.expires_at = body.expires_at
        m.updated_by = ctx.user_id
    else:
        m = Membership(
            user_id=user.id,
            property_id=property_id,
            role=body.role,
            expires_at=body.expires_at,
            created_by=ctx.user_id,
        )
        db.add(m)
    db.flush()
    audit(ctx, "create", "membership", m.id, {"role": m.role, "user_id": user.id})
    return _member_out(m, user)


def _get_membership(db: DbSession, property_id: str, membership_id: str) -> Membership:
    m = db.get(Membership, membership_id)
    if m is None or m.property_id != property_id or m.deleted_at is not None:
        raise not_found()
    return m


def _would_remove_last_admin(db: DbSession, m: Membership) -> bool:
    if m.role != Role.ADMIN.value:
        return False
    admins = db.scalars(
        select(Membership.id).where(
            Membership.property_id == m.property_id,
            Membership.role == Role.ADMIN.value,
            Membership.deleted_at.is_(None),
        )
    ).all()
    return len(admins) <= 1


@router.patch("/properties/{property_id}/members/{membership_id}")
def update_member(
    property_id: str,
    membership_id: str,
    body: MemberUpdate,
    db: DbSession,
    principal: CurrentPrincipal,
) -> MemberOut:
    ctx = _admin(db, principal, property_id)
    m = _get_membership(db, property_id, membership_id)
    if (
        "role" in body.model_fields_set
        and body.role != Role.ADMIN.value
        and _would_remove_last_admin(db, m)
    ):
        raise bad_request("a property needs at least one admin")
    diff = apply_update(m, body, user_id=ctx.user_id)
    if m.role == Role.ADMIN.value and m.expires_at is not None:
        raise bad_request("admin memberships cannot expire")
    if diff:
        audit(ctx, "update", "membership", m.id, diff)
    user = db.get(User, m.user_id)
    assert user is not None  # noqa: S101 - foreign key
    return _member_out(m, user)


@router.delete(
    "/properties/{property_id}/members/{membership_id}", status_code=status.HTTP_204_NO_CONTENT
)
def remove_member(
    property_id: str, membership_id: str, db: DbSession, principal: CurrentPrincipal
) -> None:
    ctx = _admin(db, principal, property_id)
    m = _get_membership(db, property_id, membership_id)
    if _would_remove_last_admin(db, m):
        raise bad_request("a property needs at least one admin")
    m.deleted_at = datetime.now(UTC)
    audit(ctx, "delete", "membership", m.id)


# --- Access rules -----------------------------------------------------------


def _validate_rule(ctx: PropertyContext, body: AccessRuleIn) -> None:
    model = SCOPE_MODELS[body.scope_type]
    target = ctx.db.get(model, body.scope_id)
    if target is None or target.property_id != ctx.property_id:
        raise bad_request(f"{body.scope_type} {body.scope_id} not found in this property")
    if body.subject_type == SubjectType.ROLE.value:
        if body.subject not in {r.value for r in Role} or body.subject == Role.ADMIN.value:
            raise bad_request("subject must be maintainer, resident, or guest")
    else:
        m = ctx.db.get(Membership, body.subject)
        if m is None or m.property_id != ctx.property_id:
            raise bad_request("subject membership not found in this property")


@router.get("/properties/{property_id}/access-rules")
def list_rules(property_id: str, db: DbSession, principal: CurrentPrincipal) -> Page[AccessRuleOut]:
    _admin(db, principal, property_id)
    rows = db.scalars(
        select(AccessRule)
        .where(AccessRule.property_id == property_id, AccessRule.deleted_at.is_(None))
        .order_by(AccessRule.id)
    )
    return Page(items=[AccessRuleOut.model_validate(r) for r in rows])


@router.post("/properties/{property_id}/access-rules", status_code=status.HTTP_201_CREATED)
def create_rule(
    property_id: str, body: AccessRuleIn, db: DbSession, principal: CurrentPrincipal
) -> AccessRuleOut:
    ctx = _admin(db, principal, property_id)
    _validate_rule(ctx, body)
    rule = AccessRule(
        property_id=property_id, **body.model_dump(), created_by=ctx.user_id, updated_by=ctx.user_id
    )
    db.add(rule)
    db.flush()
    audit(ctx, "create", "access_rule", rule.id, body.model_dump(mode="json"))
    return AccessRuleOut.model_validate(rule)


@router.delete(
    "/properties/{property_id}/access-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_rule(property_id: str, rule_id: str, db: DbSession, principal: CurrentPrincipal) -> None:
    ctx = _admin(db, principal, property_id)
    rule = db.get(AccessRule, rule_id)
    if rule is None or rule.property_id != property_id or rule.deleted_at is not None:
        raise not_found()
    rule.deleted_at = datetime.now(UTC)
    audit(ctx, "delete", "access_rule", rule.id)
