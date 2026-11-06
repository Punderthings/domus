"""Properties, buildings, floors, areas (rooms), and locations."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query, status
from sqlalchemy import select

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
    AreaIn,
    AreaOut,
    AreaUpdate,
    BuildingIn,
    BuildingOut,
    BuildingUpdate,
    FloorIn,
    FloorOut,
    FloorUpdate,
    LocationIn,
    LocationOut,
    LocationUpdate,
    Page,
    PropertyOut,
    PropertyUpdate,
)
from domus.models import Area, Building, Floor, Location, Property
from domus.models.enums import AccessLevel, Role
from domus.services.access import at_least

router = APIRouter(tags=["space"])

Limit = Annotated[int, Query(ge=1, le=200)]


# --- Properties -------------------------------------------------------------


def _property_out(ctx: PropertyContext, prop: Property) -> PropertyOut:
    level = AccessLevel.MANAGE if ctx.is_admin else AccessLevel.VIEW
    return to_out(PropertyOut, prop, access=level.value)


@router.get("/properties")
def list_properties(db: DbSession, principal: CurrentPrincipal) -> Page[PropertyOut]:
    items: list[PropertyOut] = []
    for m in active_memberships(db, principal.user.id):
        prop = db.get(Property, m.property_id)
        if prop is not None and prop.deleted_at is None:
            items.append(_property_out(PropertyContext(db, principal, m), prop))
    items.sort(key=lambda p: p.id)
    return Page(items=items)


@router.get("/properties/{property_id}")
def get_property(property_id: str, db: DbSession, principal: CurrentPrincipal) -> PropertyOut:
    ctx = property_context(db, principal, property_id)
    prop = db.get(Property, property_id)
    if prop is None or prop.deleted_at is not None:
        raise not_found()
    return _property_out(ctx, prop)


@router.patch("/properties/{property_id}")
def update_property(
    property_id: str, body: PropertyUpdate, db: DbSession, principal: CurrentPrincipal
) -> PropertyOut:
    ctx = property_context(db, principal, property_id)
    ctx.require_role(Role.ADMIN)
    prop = db.get(Property, property_id)
    if prop is None:
        raise not_found()
    diff = apply_update(prop, body, user_id=ctx.user_id)
    if diff:
        audit(ctx, "update", "property", prop.id, diff)
    return _property_out(ctx, prop)


# --- Buildings --------------------------------------------------------------


def _get_building(ctx: PropertyContext | None, db: DbSession, building_id: str) -> Building:
    b = db.get(Building, building_id)
    if b is None or b.deleted_at is not None:
        raise not_found()
    if ctx is not None and b.property_id != ctx.property_id:
        raise not_found()
    return b


@router.get("/buildings")
def list_buildings(
    db: DbSession,
    principal: CurrentPrincipal,
    property_id: str | None = None,
    limit: Limit = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> Page[BuildingOut]:
    ctx = property_context(db, principal, property_id)
    stmt = select(Building).where(
        Building.property_id == ctx.property_id, Building.deleted_at.is_(None)
    )
    rows, nxt = paginate(
        db, stmt, Building.id, limit=limit, cursor=cursor, level_of=ctx.access.building_level
    )
    return Page(items=[to_out(BuildingOut, b, access=lv.value) for b, lv in rows], next_cursor=nxt)


@router.get("/buildings/{building_id}")
def get_building(building_id: str, db: DbSession, principal: CurrentPrincipal) -> BuildingOut:
    b = _get_building(None, db, building_id)
    ctx = property_context(db, principal, b.property_id)
    level = ctx.access.building_level(b)
    ctx.require_level(level, AccessLevel.VIEW)
    return to_out(BuildingOut, b, access=level.value)


@router.post("/buildings", status_code=status.HTTP_201_CREATED)
def create_building(body: BuildingIn, db: DbSession, principal: CurrentPrincipal) -> BuildingOut:
    ctx = property_context(db, principal, body.property_id)
    ctx.require_role(Role.MAINTAINER)
    if body.is_primary and not ctx.is_admin:
        ctx.require_role(Role.ADMIN)
    b = Building(**body.model_dump(), created_by=ctx.user_id, updated_by=ctx.user_id)
    db.add(b)
    db.flush()
    audit(ctx, "create", "building", b.id)
    return to_out(BuildingOut, b, access=ctx.access.building_level(b).value)


@router.patch("/buildings/{building_id}")
def update_building(
    building_id: str, body: BuildingUpdate, db: DbSession, principal: CurrentPrincipal
) -> BuildingOut:
    b = _get_building(None, db, building_id)
    ctx = property_context(db, principal, b.property_id)
    ctx.require_level(ctx.access.building_level(b), AccessLevel.MANAGE)
    diff = apply_update(b, body, user_id=ctx.user_id)
    if diff:
        audit(ctx, "update", "building", b.id, diff)
    return to_out(BuildingOut, b, access=ctx.access.building_level(b).value)


# --- Floors -----------------------------------------------------------------


def _get_floor(db: DbSession, floor_id: str) -> Floor:
    f = db.get(Floor, floor_id)
    if f is None or f.deleted_at is not None:
        raise not_found()
    return f


@router.get("/floors")
def list_floors(
    building_id: str,
    db: DbSession,
    principal: CurrentPrincipal,
    limit: Limit = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> Page[FloorOut]:
    b = _get_building(None, db, building_id)
    ctx = property_context(db, principal, b.property_id)
    level = ctx.access.building_level(b)
    ctx.require_level(level, AccessLevel.VIEW)
    stmt = select(Floor).where(Floor.building_id == b.id, Floor.deleted_at.is_(None))
    rows, nxt = paginate(db, stmt, Floor.id, limit=limit, cursor=cursor, level_of=lambda _: level)
    return Page(items=[to_out(FloorOut, f, access=lv.value) for f, lv in rows], next_cursor=nxt)


@router.get("/floors/{floor_id}")
def get_floor(floor_id: str, db: DbSession, principal: CurrentPrincipal) -> FloorOut:
    f = _get_floor(db, floor_id)
    b = _get_building(None, db, f.building_id)
    ctx = property_context(db, principal, b.property_id)
    level = ctx.access.building_level(b)
    ctx.require_level(level, AccessLevel.VIEW)
    return to_out(FloorOut, f, access=level.value)


@router.post("/floors", status_code=status.HTTP_201_CREATED)
def create_floor(body: FloorIn, db: DbSession, principal: CurrentPrincipal) -> FloorOut:
    b = _get_building(None, db, body.building_id)
    ctx = property_context(db, principal, b.property_id)
    ctx.require_role(Role.MAINTAINER)
    level = ctx.access.building_level(b)
    ctx.require_level(level, AccessLevel.MANAGE)
    f = Floor(**body.model_dump(), created_by=ctx.user_id, updated_by=ctx.user_id)
    db.add(f)
    db.flush()
    audit(ctx, "create", "floor", f.id)
    return to_out(FloorOut, f, access=level.value)


@router.patch("/floors/{floor_id}")
def update_floor(
    floor_id: str, body: FloorUpdate, db: DbSession, principal: CurrentPrincipal
) -> FloorOut:
    f = _get_floor(db, floor_id)
    b = _get_building(None, db, f.building_id)
    ctx = property_context(db, principal, b.property_id)
    level = ctx.access.building_level(b)
    ctx.require_level(level, AccessLevel.MANAGE)
    diff = apply_update(f, body, user_id=ctx.user_id)
    if diff:
        audit(ctx, "update", "floor", f.id, diff)
    return to_out(FloorOut, f, access=level.value)


# --- Areas ------------------------------------------------------------------


def _get_area(db: DbSession, area_id: str) -> Area:
    a = db.get(Area, area_id)
    if a is None or a.deleted_at is not None:
        raise not_found()
    return a


def _check_area_placement(
    ctx: PropertyContext, db: DbSession, building_id: str | None, floor_id: str | None
) -> None:
    """Building and floor must belong to this property, and the floor to the building."""
    if floor_id is not None and building_id is None:
        raise bad_request("floor_id requires building_id")
    if building_id is not None:
        _get_building(ctx, db, building_id)
    if floor_id is not None:
        f = _get_floor(db, floor_id)
        if f.building_id != building_id:
            raise bad_request("floor_id belongs to a different building")


@router.get("/areas")
def list_areas(
    db: DbSession,
    principal: CurrentPrincipal,
    property_id: str | None = None,
    building_id: str | None = None,
    floor_id: str | None = None,
    limit: Limit = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> Page[AreaOut]:
    ctx = property_context(db, principal, property_id)
    stmt = select(Area).where(Area.property_id == ctx.property_id, Area.deleted_at.is_(None))
    if building_id is not None:
        stmt = stmt.where(Area.building_id == building_id)
    if floor_id is not None:
        stmt = stmt.where(Area.floor_id == floor_id)
    rows, nxt = paginate(
        db, stmt, Area.id, limit=limit, cursor=cursor, level_of=ctx.access.area_level
    )
    return Page(items=[to_out(AreaOut, a, access=lv.value) for a, lv in rows], next_cursor=nxt)


@router.get("/areas/{area_id}")
def get_area(area_id: str, db: DbSession, principal: CurrentPrincipal) -> AreaOut:
    a = _get_area(db, area_id)
    ctx = property_context(db, principal, a.property_id)
    level = ctx.access.area_level(a)
    ctx.require_level(level, AccessLevel.VIEW)
    return to_out(AreaOut, a, access=level.value)


@router.post("/areas", status_code=status.HTTP_201_CREATED)
def create_area(body: AreaIn, db: DbSession, principal: CurrentPrincipal) -> AreaOut:
    ctx = property_context(db, principal, body.property_id)
    ctx.require_role(Role.MAINTAINER)
    if body.is_critical:
        ctx.require_role(Role.ADMIN)
    _check_area_placement(ctx, db, body.building_id, body.floor_id)
    if body.building_id is not None:
        b = _get_building(ctx, db, body.building_id)
        ctx.require_level(ctx.access.building_level(b), AccessLevel.MANAGE)
    a = Area(**body.model_dump(), created_by=ctx.user_id, updated_by=ctx.user_id)
    db.add(a)
    db.flush()
    audit(ctx, "create", "area", a.id, {"is_critical": a.is_critical})
    return to_out(AreaOut, a, access=ctx.access.area_level(a).value)


@router.patch("/areas/{area_id}")
def update_area(
    area_id: str, body: AreaUpdate, db: DbSession, principal: CurrentPrincipal
) -> AreaOut:
    a = _get_area(db, area_id)
    ctx = property_context(db, principal, a.property_id)
    ctx.require_level(ctx.access.area_level(a), AccessLevel.MANAGE)
    if "is_critical" in body.model_fields_set:
        ctx.require_role(Role.ADMIN)
    sent = body.model_fields_set
    if "building_id" in sent or "floor_id" in sent:
        building_id = body.building_id if "building_id" in sent else a.building_id
        floor_id = body.floor_id if "floor_id" in sent else a.floor_id
        _check_area_placement(ctx, db, building_id, floor_id)
    diff = apply_update(a, body, user_id=ctx.user_id)
    if diff:
        audit(ctx, "update", "area", a.id, diff)
    return to_out(AreaOut, a, access=ctx.access.area_level(a).value)


@router.delete("/areas/{area_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_area(area_id: str, db: DbSession, principal: CurrentPrincipal) -> None:
    a = _get_area(db, area_id)
    ctx = property_context(db, principal, a.property_id)
    ctx.require_level(ctx.access.area_level(a), AccessLevel.MANAGE)
    a.deleted_at = datetime.now(UTC)
    a.updated_by = ctx.user_id
    audit(ctx, "delete", "area", a.id)


# --- Locations --------------------------------------------------------------


def _get_location(db: DbSession, location_id: str) -> Location:
    loc = db.get(Location, location_id)
    if loc is None or loc.deleted_at is not None:
        raise not_found()
    return loc


@router.get("/locations")
def list_locations(
    area_id: str,
    db: DbSession,
    principal: CurrentPrincipal,
    limit: Limit = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> Page[LocationOut]:
    a = _get_area(db, area_id)
    ctx = property_context(db, principal, a.property_id)
    level = ctx.access.area_level(a)
    ctx.require_level(level, AccessLevel.VIEW)
    stmt = select(Location).where(Location.area_id == a.id, Location.deleted_at.is_(None))
    rows, nxt = paginate(
        db, stmt, Location.id, limit=limit, cursor=cursor, level_of=lambda _: level
    )
    return Page(
        items=[to_out(LocationOut, loc, access=lv.value) for loc, lv in rows], next_cursor=nxt
    )


@router.get("/locations/{location_id}")
def get_location(location_id: str, db: DbSession, principal: CurrentPrincipal) -> LocationOut:
    loc = _get_location(db, location_id)
    a = _get_area(db, loc.area_id)
    ctx = property_context(db, principal, a.property_id)
    level = ctx.access.area_level(a)
    ctx.require_level(level, AccessLevel.VIEW)
    return to_out(LocationOut, loc, access=level.value)


def _check_parent_location(db: DbSession, area_id: str, parent_id: str | None) -> None:
    if parent_id is None:
        return
    parent = _get_location(db, parent_id)
    if parent.area_id != area_id:
        raise bad_request("parent_location_id is in a different area")


@router.post("/locations", status_code=status.HTTP_201_CREATED)
def create_location(body: LocationIn, db: DbSession, principal: CurrentPrincipal) -> LocationOut:
    a = _get_area(db, body.area_id)
    ctx = property_context(db, principal, a.property_id)
    ctx.require_role(Role.MAINTAINER)
    level = ctx.access.area_level(a)
    ctx.require_level(level, AccessLevel.MANAGE)
    _check_parent_location(db, a.id, body.parent_location_id)
    loc = Location(**body.model_dump(), created_by=ctx.user_id, updated_by=ctx.user_id)
    db.add(loc)
    db.flush()
    audit(ctx, "create", "location", loc.id)
    return to_out(LocationOut, loc, access=level.value)


@router.patch("/locations/{location_id}")
def update_location(
    location_id: str, body: LocationUpdate, db: DbSession, principal: CurrentPrincipal
) -> LocationOut:
    loc = _get_location(db, location_id)
    a = _get_area(db, loc.area_id)
    ctx = property_context(db, principal, a.property_id)
    level = ctx.access.area_level(a)
    ctx.require_level(level, AccessLevel.MANAGE)
    if "parent_location_id" in body.model_fields_set:
        if body.parent_location_id == loc.id:
            raise bad_request("a location cannot be its own parent")
        _check_parent_location(db, a.id, body.parent_location_id)
    diff = apply_update(loc, body, user_id=ctx.user_id)
    if diff:
        audit(ctx, "update", "location", loc.id, diff)
    return to_out(LocationOut, loc, access=level.value)


def visible(level: AccessLevel) -> bool:
    return at_least(level, AccessLevel.VIEW)
