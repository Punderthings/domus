"""Assets (devices, appliances, equipment), their identifiers, products, and tags."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import delete, or_, select

from domus.api.common import DEFAULT_LIMIT, apply_update, audit, bad_request, paginate, to_out
from domus.api.deps import (
    CurrentPrincipal,
    DbSession,
    PropertyContext,
    active_memberships,
    not_found,
    property_context,
)
from domus.api.schemas import (
    RESIDENT_EDITABLE_ASSET_FIELDS,
    AssetDetailOut,
    AssetGuestDetailOut,
    AssetGuestOut,
    AssetIn,
    AssetOut,
    AssetUpdate,
    IdentifierIn,
    IdentifierOut,
    LocationOut,
    Page,
    ProductIn,
    ProductOut,
    TagIn,
    TagOut,
    TagRef,
)
from domus.models import Area, Asset, AssetIdentifier, AssetTag, Location, Product, Tag
from domus.models.enums import UNIQUE_IDENTIFIER_KINDS, AccessLevel, Role

router = APIRouter(tags=["assets"])

Limit = Annotated[int, Query(ge=1, le=200)]


# --- Helpers ----------------------------------------------------------------


def _get_asset(db: DbSession, asset_id: str) -> Asset:
    a = db.get(Asset, asset_id)
    if a is None or a.deleted_at is not None:
        raise not_found()
    return a


def _area_id(db: DbSession, asset: Asset) -> str | None:
    if asset.location_id is None:
        return None
    loc = db.get(Location, asset.location_id)
    return loc.area_id if loc else None


def _tags(db: DbSession, asset_id: str) -> list[TagRef]:
    rows = db.scalars(
        select(Tag)
        .join(AssetTag, AssetTag.tag_id == Tag.id)
        .where(AssetTag.asset_id == asset_id, Tag.deleted_at.is_(None))
        .order_by(Tag.name)
    )
    return [TagRef.model_validate(t) for t in rows]


def asset_summary(
    ctx: PropertyContext, asset: Asset, level: AccessLevel
) -> AssetOut | AssetGuestOut:
    schema = AssetGuestOut if ctx.is_guest else AssetOut
    return to_out(
        schema,
        asset,
        area_id=_area_id(ctx.db, asset),
        tags=_tags(ctx.db, asset.id),
        access=level.value,
    )


def _asset_detail(
    ctx: PropertyContext, asset: Asset, level: AccessLevel
) -> AssetDetailOut | AssetGuestDetailOut:
    db = ctx.db
    product = db.get(Product, asset.product_id) if asset.product_id else None
    location = db.get(Location, asset.location_id) if asset.location_id else None
    common = {
        "area_id": location.area_id if location else None,
        "tags": _tags(db, asset.id),
        "access": level.value,
        "product": ProductOut.model_validate(product) if product else None,
        "location": to_out(LocationOut, location, access=ctx.access.location_level(location).value)
        if location
        else None,
    }
    if ctx.is_guest:
        return to_out(AssetGuestDetailOut, asset, **common)
    identifiers = db.scalars(
        select(AssetIdentifier)
        .where(AssetIdentifier.asset_id == asset.id, AssetIdentifier.deleted_at.is_(None))
        .order_by(AssetIdentifier.id)
    )
    return to_out(
        AssetDetailOut,
        asset,
        identifiers=[IdentifierOut.model_validate(i) for i in identifiers],
        **common,
    )


def _check_location(ctx: PropertyContext, location_id: str | None) -> None:
    """A new or moved asset must go somewhere in this property the caller can manage."""
    if location_id is None:
        return
    loc = ctx.db.get(Location, location_id)
    area = ctx.db.get(Area, loc.area_id) if loc else None
    if loc is None or area is None or area.property_id != ctx.property_id:
        raise bad_request("location_id not found in this property")
    ctx.require_level(ctx.access.area_level(area), AccessLevel.MANAGE)


def _check_refs(ctx: PropertyContext, asset_id: str | None, body: AssetIn | AssetUpdate) -> None:
    db = ctx.db
    sent = body.model_fields_set
    if "product_id" in sent and body.product_id is not None:
        p = db.get(Product, body.product_id)
        if p is None or p.deleted_at is not None:
            raise bad_request("product_id not found")
    if "parent_asset_id" in sent and body.parent_asset_id is not None:
        parent = db.get(Asset, body.parent_asset_id)
        if parent is None or parent.deleted_at is not None:
            raise bad_request("parent_asset_id not found")
        if parent.property_id != ctx.property_id:
            raise bad_request("parent_asset_id not found")
        # Walk up from the new parent to refuse cycles.
        seen: set[str] = set()
        current: Asset | None = parent
        while current is not None and current.id not in seen:
            if current.id == asset_id:
                raise bad_request("parent_asset_id would create a cycle")
            seen.add(current.id)
            current = db.get(Asset, current.parent_asset_id) if current.parent_asset_id else None
    if body.tag_ids:
        found = set(
            db.scalars(
                select(Tag.id).where(
                    Tag.id.in_(body.tag_ids),
                    Tag.property_id == ctx.property_id,
                    Tag.deleted_at.is_(None),
                )
            )
        )
        if found != set(body.tag_ids):
            raise bad_request("tag_ids contains an unknown tag")


def _set_tags(db: DbSession, asset_id: str, tag_ids: list[str]) -> None:
    db.execute(delete(AssetTag).where(AssetTag.asset_id == asset_id))
    db.add_all([AssetTag(asset_id=asset_id, tag_id=t) for t in dict.fromkeys(tag_ids)])


def _add_identifier(ctx: PropertyContext, asset: Asset, body: IdentifierIn) -> AssetIdentifier:
    value = body.value.strip()
    if body.kind == "mac":
        value = value.lower().replace("-", ":")
    if body.kind in UNIQUE_IDENTIFIER_KINDS:
        clash = ctx.db.scalar(
            select(AssetIdentifier.id)
            .join(Asset, Asset.id == AssetIdentifier.asset_id)
            .where(
                AssetIdentifier.kind == body.kind,
                AssetIdentifier.value == value,
                AssetIdentifier.deleted_at.is_(None),
                Asset.property_id == ctx.property_id,
                Asset.deleted_at.is_(None),
            )
        )
        if clash is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, f"Another asset already has this {body.kind}"
            )
    row = AssetIdentifier(
        asset_id=asset.id,
        kind=body.kind,
        value=value,
        source=body.source,
        created_by=ctx.user_id,
        updated_by=ctx.user_id,
    )
    ctx.db.add(row)
    return row


# --- Assets -----------------------------------------------------------------


@router.get("/assets")
def list_assets(
    db: DbSession,
    principal: CurrentPrincipal,
    property_id: str | None = None,
    area_id: str | None = None,
    location_id: str | None = None,
    category: str | None = None,
    tag_id: str | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Limit = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> Page[AssetOut | AssetGuestOut]:
    ctx = property_context(db, principal, property_id)
    stmt = select(Asset).where(Asset.property_id == ctx.property_id, Asset.deleted_at.is_(None))
    if area_id is not None:
        stmt = stmt.join(Location, Location.id == Asset.location_id).where(
            Location.area_id == area_id
        )
    if location_id is not None:
        stmt = stmt.where(Asset.location_id == location_id)
    if category is not None:
        stmt = stmt.where(Asset.category == category)
    if tag_id is not None:
        stmt = stmt.join(AssetTag, AssetTag.asset_id == Asset.id).where(AssetTag.tag_id == tag_id)
    if q:
        like = f"%{q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')}%"
        stmt = stmt.where(
            or_(Asset.name.ilike(like, escape="\\"), Asset.notes.ilike(like, escape="\\"))
        )
    rows, nxt = paginate(
        db, stmt, Asset.id, limit=limit, cursor=cursor, level_of=ctx.access.asset_level
    )
    return Page(items=[asset_summary(ctx, a, lv) for a, lv in rows], next_cursor=nxt)


@router.get("/assets/{asset_id}")
def get_asset(
    asset_id: str, db: DbSession, principal: CurrentPrincipal
) -> AssetDetailOut | AssetGuestDetailOut:
    asset = _get_asset(db, asset_id)
    ctx = property_context(db, principal, asset.property_id)
    level = ctx.access.asset_level(asset)
    ctx.require_level(level, AccessLevel.VIEW)
    return _asset_detail(ctx, asset, level)


@router.post("/assets", status_code=status.HTTP_201_CREATED)
def create_asset(body: AssetIn, db: DbSession, principal: CurrentPrincipal) -> AssetDetailOut:
    ctx = property_context(db, principal, body.property_id)
    ctx.require_role(Role.MAINTAINER)
    if body.is_critical:
        ctx.require_role(Role.ADMIN)
    _check_location(ctx, body.location_id)
    _check_refs(ctx, None, body)
    fields = body.model_dump(exclude={"tag_ids", "identifiers"})
    asset = Asset(**fields, created_by=ctx.user_id, updated_by=ctx.user_id)
    db.add(asset)
    db.flush()
    _set_tags(db, asset.id, body.tag_ids)
    for ident in body.identifiers:
        _add_identifier(ctx, asset, ident)
    db.flush()
    audit(ctx, "create", "asset", asset.id, {"name": asset.name, "is_critical": asset.is_critical})
    level = ctx.access.asset_level(asset)
    detail = _asset_detail(ctx, asset, level)
    assert isinstance(detail, AssetDetailOut)  # noqa: S101 - maintainers are never guests
    return detail


@router.patch("/assets/{asset_id}")
def update_asset(
    asset_id: str, body: AssetUpdate, db: DbSession, principal: CurrentPrincipal
) -> AssetDetailOut | AssetGuestDetailOut:
    asset = _get_asset(db, asset_id)
    ctx = property_context(db, principal, asset.property_id)
    level = ctx.access.asset_level(asset)
    sent = body.model_fields_set
    if ctx.has_role(Role.MAINTAINER):
        ctx.require_level(level, AccessLevel.MANAGE)
    elif ctx.has_role(Role.RESIDENT) and sent <= RESIDENT_EDITABLE_ASSET_FIELDS:
        ctx.require_level(level, AccessLevel.CONTROL)
    else:
        ctx.require_level(level, AccessLevel.VIEW)
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Requires the maintainer role")
    if "is_critical" in sent:
        ctx.require_role(Role.ADMIN)
    if "location_id" in sent:
        _check_location(ctx, body.location_id)
    _check_refs(ctx, asset.id, body)
    diff = apply_update(asset, body, user_id=ctx.user_id, exclude={"tag_ids"})
    if body.tag_ids is not None:
        _set_tags(db, asset.id, body.tag_ids)
        diff["tag_ids"] = body.tag_ids
    if diff:
        asset.updated_by = ctx.user_id
        audit(ctx, "update", "asset", asset.id, diff)
    db.flush()
    ctx.refresh_access()
    return _asset_detail(ctx, asset, ctx.access.asset_level(asset))


@router.delete("/assets/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_asset(asset_id: str, db: DbSession, principal: CurrentPrincipal) -> None:
    asset = _get_asset(db, asset_id)
    ctx = property_context(db, principal, asset.property_id)
    ctx.require_role(Role.MAINTAINER)
    ctx.require_level(ctx.access.asset_level(asset), AccessLevel.MANAGE)
    asset.deleted_at = datetime.now(UTC)
    asset.updated_by = ctx.user_id
    audit(ctx, "delete", "asset", asset.id)


@router.post("/assets/{asset_id}/identifiers", status_code=status.HTTP_201_CREATED)
def add_identifier(
    asset_id: str, body: IdentifierIn, db: DbSession, principal: CurrentPrincipal
) -> IdentifierOut:
    asset = _get_asset(db, asset_id)
    ctx = property_context(db, principal, asset.property_id)
    ctx.require_role(Role.MAINTAINER)
    ctx.require_level(ctx.access.asset_level(asset), AccessLevel.MANAGE)
    row = _add_identifier(ctx, asset, body)
    db.flush()
    audit(ctx, "create", "asset_identifier", row.id, {"kind": row.kind})
    return IdentifierOut.model_validate(row)


@router.delete(
    "/assets/{asset_id}/identifiers/{identifier_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_identifier(
    asset_id: str, identifier_id: str, db: DbSession, principal: CurrentPrincipal
) -> None:
    asset = _get_asset(db, asset_id)
    ctx = property_context(db, principal, asset.property_id)
    ctx.require_role(Role.MAINTAINER)
    ctx.require_level(ctx.access.asset_level(asset), AccessLevel.MANAGE)
    row = db.get(AssetIdentifier, identifier_id)
    if row is None or row.asset_id != asset.id or row.deleted_at is not None:
        raise not_found()
    row.deleted_at = datetime.now(UTC)
    audit(ctx, "delete", "asset_identifier", row.id)


# --- Products (a shared catalog) --------------------------------------------


@router.get("/products/{product_id}")
def get_product(product_id: str, db: DbSession, principal: CurrentPrincipal) -> ProductOut:
    p = db.get(Product, product_id)
    if p is None or p.deleted_at is not None:
        raise not_found()
    # Products carry no private data, but only members of some property may read them.
    if not active_memberships(db, principal.user.id):
        raise not_found()
    return ProductOut.model_validate(p)


@router.post("/products", status_code=status.HTTP_201_CREATED)
def create_product(
    body: ProductIn,
    db: DbSession,
    principal: CurrentPrincipal,
    property_id: str | None = None,
) -> ProductOut:
    ctx = property_context(db, principal, property_id)
    ctx.require_role(Role.MAINTAINER)
    p = Product(**body.model_dump(), created_by=ctx.user_id, updated_by=ctx.user_id)
    db.add(p)
    db.flush()
    audit(ctx, "create", "product", p.id)
    return ProductOut.model_validate(p)


# --- Tags -------------------------------------------------------------------


@router.get("/tags")
def list_tags(
    db: DbSession,
    principal: CurrentPrincipal,
    property_id: str | None = None,
    limit: Limit = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> Page[TagOut]:
    ctx = property_context(db, principal, property_id)
    stmt = select(Tag).where(Tag.property_id == ctx.property_id, Tag.deleted_at.is_(None))
    rows, nxt = paginate(
        db, stmt, Tag.id, limit=limit, cursor=cursor, level_of=lambda _: AccessLevel.VIEW
    )
    return Page(items=[TagOut.model_validate(t) for t, _ in rows], next_cursor=nxt)


@router.post("/tags", status_code=status.HTTP_201_CREATED)
def create_tag(body: TagIn, db: DbSession, principal: CurrentPrincipal) -> TagOut:
    ctx = property_context(db, principal, body.property_id)
    ctx.require_role(Role.MAINTAINER)
    exists = db.scalar(
        select(Tag.id).where(Tag.property_id == ctx.property_id, Tag.name == body.name)
    )
    if exists is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "A tag with this name exists")
    t = Tag(**body.model_dump(), created_by=ctx.user_id, updated_by=ctx.user_id)
    db.add(t)
    db.flush()
    audit(ctx, "create", "tag", t.id)
    return TagOut.model_validate(t)
