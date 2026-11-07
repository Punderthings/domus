"""Floor plans, wall photos, and the device pins placed on them.

A canvas belongs to a property, building, floor, or area, and takes its access
level from that scope. Each pin also needs the caller to see its device, so a
guest never learns where a hidden device is from a floor plan.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import select

from domus.api.common import DEFAULT_LIMIT, apply_update, audit, bad_request, paginate, to_out
from domus.api.deps import (
    CurrentPrincipal,
    DbSession,
    PropertyContext,
    SettingsDep,
    not_found,
    property_context,
)
from domus.api.routers.documents import blob_store, file_response, get_document
from domus.api.schemas import (
    CanvasIn,
    CanvasKind,
    CanvasOut,
    CanvasScope,
    CanvasUpdate,
    Page,
    PlacementIn,
    PlacementOut,
    PlacementUpdate,
)
from domus.models import Area, Asset, Blob, Building, Canvas, Document, Floor, Placement
from domus.models.enums import IMAGE_MIME_TYPES, AccessLevel, Role
from domus.services.access import at_least

router = APIRouter(tags=["canvases"])

Limit = Annotated[int, Query(ge=1, le=200)]
MAX_PLACEMENTS = 1000


def _live[M: (Building, Floor, Area)](db: DbSession, model: type[M], row_id: str) -> M | None:
    row = db.get(model, row_id)
    return row if row is not None and row.deleted_at is None else None


def scope_level(ctx: PropertyContext, scope_type: str, scope_id: str) -> AccessLevel:
    """The caller's level on a canvas scope; HIDDEN if it is missing or in another property."""
    db = ctx.db
    if scope_type == "property":
        return ctx.access.default_level() if scope_id == ctx.property_id else AccessLevel.HIDDEN
    building: Building | None = None
    if scope_type == "area":
        area = _live(db, Area, scope_id)
        if area is None or area.property_id != ctx.property_id:
            return AccessLevel.HIDDEN
        return ctx.access.area_level(area)
    if scope_type == "floor":
        floor = _live(db, Floor, scope_id)
        building = _live(db, Building, floor.building_id) if floor else None
    elif scope_type == "building":
        building = _live(db, Building, scope_id)
    if building is None or building.property_id != ctx.property_id:
        return AccessLevel.HIDDEN
    return ctx.access.building_level(building)


def _get_canvas(db: DbSession, canvas_id: str) -> Canvas:
    c = db.get(Canvas, canvas_id)
    if c is None or c.deleted_at is not None:
        raise not_found()
    return c


def _canvas_ctx(
    db: DbSession, principal: CurrentPrincipal, canvas: Canvas, minimum: AccessLevel
) -> tuple[PropertyContext, AccessLevel]:
    ctx = property_context(db, principal, canvas.property_id)
    level = scope_level(ctx, canvas.scope_type, canvas.scope_id)
    ctx.require_level(level, minimum)
    if minimum is AccessLevel.MANAGE:
        ctx.require_role(Role.MAINTAINER)
    return ctx, level


def _canvas_out(canvas: Canvas, level: AccessLevel) -> CanvasOut:
    # The document id in the URL changes when the image is replaced, so
    # browsers fetch the new image instead of a cached copy.
    url = f"/api/v1/canvases/{canvas.id}/image?v={canvas.document_id}"
    return to_out(CanvasOut, canvas, image_url=url, access=level.value)


def _image_document(ctx: PropertyContext, document_id: str) -> Document:
    """A live image document in this property."""
    try:
        doc = get_document(ctx.db, document_id)
    except HTTPException:
        raise bad_request("document_id not found") from None
    if doc.property_id != ctx.property_id:
        raise bad_request("document_id not found")
    blob = ctx.db.get(Blob, doc.blob_sha256) if doc.blob_sha256 else None
    if blob is None or blob.mime_type not in IMAGE_MIME_TYPES:
        raise bad_request("document_id must be an uploaded image")
    return doc


@router.get("/canvases")
def list_canvases(
    db: DbSession,
    principal: CurrentPrincipal,
    property_id: str | None = None,
    scope_type: CanvasScope | None = None,
    scope_id: str | None = None,
    kind: CanvasKind | None = None,
    limit: Limit = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> Page[CanvasOut]:
    ctx = property_context(db, principal, property_id)
    stmt = select(Canvas).where(Canvas.property_id == ctx.property_id, Canvas.deleted_at.is_(None))
    if scope_type is not None:
        stmt = stmt.where(Canvas.scope_type == scope_type)
    if scope_id is not None:
        stmt = stmt.where(Canvas.scope_id == scope_id)
    if kind is not None:
        stmt = stmt.where(Canvas.kind == kind)
    levels: dict[tuple[str, str], AccessLevel] = {}

    def level_of(c: Canvas) -> AccessLevel:
        key = (c.scope_type, c.scope_id)
        if key not in levels:
            levels[key] = scope_level(ctx, *key)
        return levels[key]

    rows, nxt = paginate(db, stmt, Canvas.id, limit=limit, cursor=cursor, level_of=level_of)
    return Page(items=[_canvas_out(c, lv) for c, lv in rows], next_cursor=nxt)


@router.get("/canvases/{canvas_id}")
def get_canvas(canvas_id: str, db: DbSession, principal: CurrentPrincipal) -> CanvasOut:
    c = _get_canvas(db, canvas_id)
    _, level = _canvas_ctx(db, principal, c, AccessLevel.VIEW)
    return _canvas_out(c, level)


@router.get(
    "/canvases/{canvas_id}/image",
    response_class=FileResponse,
    responses={200: {"content": {m: {} for m in IMAGE_MIME_TYPES}}},
)
def get_canvas_image(
    canvas_id: str,
    db: DbSession,
    principal: CurrentPrincipal,
    settings: SettingsDep,
    v: str | None = None,
) -> FileResponse:
    """The canvas image. Anyone who can see the canvas can see its image.

    ``v`` is ignored; ``image_url`` sets it to bust browser caches.
    """
    del v
    c = _get_canvas(db, canvas_id)
    _canvas_ctx(db, principal, c, AccessLevel.VIEW)
    doc = db.get(Document, c.document_id)
    blob = db.get(Blob, doc.blob_sha256) if doc and doc.blob_sha256 else None
    if blob is None:
        raise not_found()
    return file_response(blob_store(settings), blob, None)


@router.post("/canvases", status_code=status.HTTP_201_CREATED)
def create_canvas(body: CanvasIn, db: DbSession, principal: CurrentPrincipal) -> CanvasOut:
    ctx = property_context(db, principal, body.property_id)
    ctx.require_role(Role.MAINTAINER)
    level = scope_level(ctx, body.scope_type, body.scope_id)
    if level is AccessLevel.HIDDEN:
        raise bad_request("scope not found")
    ctx.require_level(level, AccessLevel.MANAGE)
    _image_document(ctx, body.document_id)
    c = Canvas(
        **body.model_dump(exclude={"property_id"}),
        property_id=ctx.property_id,
        created_by=ctx.user_id,
        updated_by=ctx.user_id,
    )
    db.add(c)
    db.flush()
    audit(ctx, "create", "canvas", c.id, {"kind": c.kind, "scope_type": c.scope_type})
    return _canvas_out(c, level)


@router.patch("/canvases/{canvas_id}")
def update_canvas(
    canvas_id: str, body: CanvasUpdate, db: DbSession, principal: CurrentPrincipal
) -> CanvasOut:
    """Rename a canvas or replace its image. Pins keep their 0-1 positions."""
    c = _get_canvas(db, canvas_id)
    ctx, level = _canvas_ctx(db, principal, c, AccessLevel.MANAGE)
    if "document_id" in body.model_fields_set:
        if body.document_id is None:
            raise bad_request("document_id cannot be cleared")
        _image_document(ctx, body.document_id)
    diff = apply_update(c, body, user_id=ctx.user_id)
    if diff:
        audit(ctx, "update", "canvas", c.id, diff)
    return _canvas_out(c, level)


@router.delete("/canvases/{canvas_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_canvas(canvas_id: str, db: DbSession, principal: CurrentPrincipal) -> None:
    c = _get_canvas(db, canvas_id)
    ctx, _ = _canvas_ctx(db, principal, c, AccessLevel.MANAGE)
    now = datetime.now(UTC)
    c.deleted_at = now
    c.updated_by = ctx.user_id
    for p in db.scalars(
        select(Placement).where(Placement.canvas_id == c.id, Placement.deleted_at.is_(None))
    ):
        p.deleted_at = now
        p.updated_by = ctx.user_id
    audit(ctx, "delete", "canvas", c.id)


# --- Placements ---------------------------------------------------------------


def _visible_asset(ctx: PropertyContext, asset_id: str) -> Asset | None:
    a = ctx.db.get(Asset, asset_id)
    if a is None or a.deleted_at is not None or a.property_id != ctx.property_id:
        return None
    return a if at_least(ctx.access.asset_level(a), AccessLevel.VIEW) else None


def _placement_out(p: Placement, asset: Asset, level: AccessLevel) -> PlacementOut:
    return to_out(PlacementOut, p, asset_name=asset.name, access=level.value)


def _get_placement(db: DbSession, placement_id: str) -> Placement:
    p = db.get(Placement, placement_id)
    if p is None or p.deleted_at is not None:
        raise not_found()
    return p


@router.get("/canvases/{canvas_id}/placements")
def list_placements(
    canvas_id: str, db: DbSession, principal: CurrentPrincipal
) -> Page[PlacementOut]:
    """Every pin on a canvas whose device the caller can see (not paginated)."""
    c = _get_canvas(db, canvas_id)
    ctx, level = _canvas_ctx(db, principal, c, AccessLevel.VIEW)
    rows = db.scalars(
        select(Placement)
        .where(Placement.canvas_id == c.id, Placement.deleted_at.is_(None))
        .order_by(Placement.id)
        .limit(MAX_PLACEMENTS)
    ).all()
    ctx.access.prefetch_tags(p.asset_id for p in rows)
    items: list[PlacementOut] = []
    for p in rows:
        asset = _visible_asset(ctx, p.asset_id)
        if asset is not None:
            items.append(_placement_out(p, asset, level))
    return Page(items=items)


@router.get("/placements")
def placements_for_asset(
    asset_id: str, db: DbSession, principal: CurrentPrincipal
) -> Page[PlacementOut]:
    """Where one device is pinned, on canvases the caller can see."""
    a = db.get(Asset, asset_id)
    if a is None or a.deleted_at is not None:
        raise not_found()
    ctx = property_context(db, principal, a.property_id)
    if _visible_asset(ctx, a.id) is None:
        raise not_found()
    rows = db.scalars(
        select(Placement)
        .join(Canvas, Canvas.id == Placement.canvas_id)
        .where(
            Placement.asset_id == a.id,
            Placement.deleted_at.is_(None),
            Canvas.deleted_at.is_(None),
        )
        .order_by(Placement.id)
    ).all()
    items: list[PlacementOut] = []
    for p in rows:
        c = db.get(Canvas, p.canvas_id)
        if c is None:
            continue
        level = scope_level(ctx, c.scope_type, c.scope_id)
        if at_least(level, AccessLevel.VIEW):
            items.append(_placement_out(p, a, level))
    return Page(items=items)


@router.post("/placements", status_code=status.HTTP_201_CREATED)
def create_placement(body: PlacementIn, db: DbSession, principal: CurrentPrincipal) -> PlacementOut:
    c = _get_canvas(db, body.canvas_id)
    ctx, level = _canvas_ctx(db, principal, c, AccessLevel.MANAGE)
    asset = _visible_asset(ctx, body.asset_id)
    if asset is None:
        raise bad_request("asset_id not found")
    taken = db.scalar(
        select(Placement.id).where(
            Placement.canvas_id == c.id,
            Placement.asset_id == asset.id,
            Placement.deleted_at.is_(None),
        )
    )
    if taken is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This device is already on this canvas")
    p = Placement(
        **body.model_dump(), shape="point", created_by=ctx.user_id, updated_by=ctx.user_id
    )
    db.add(p)
    db.flush()
    audit(ctx, "create", "placement", p.id, {"canvas_id": c.id, "asset_id": asset.id})
    return _placement_out(p, asset, level)


@router.patch("/placements/{placement_id}")
def update_placement(
    placement_id: str, body: PlacementUpdate, db: DbSession, principal: CurrentPrincipal
) -> PlacementOut:
    p = _get_placement(db, placement_id)
    c = _get_canvas(db, p.canvas_id)
    ctx, level = _canvas_ctx(db, principal, c, AccessLevel.MANAGE)
    asset = _visible_asset(ctx, p.asset_id)
    if asset is None:
        raise not_found()
    for field in ("x", "y"):
        if field in body.model_fields_set and getattr(body, field) is None:
            raise bad_request(f"{field} cannot be cleared")
    diff = apply_update(p, body, user_id=ctx.user_id)
    if diff:
        audit(ctx, "update", "placement", p.id, diff)
    return _placement_out(p, asset, level)


@router.delete("/placements/{placement_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_placement(placement_id: str, db: DbSession, principal: CurrentPrincipal) -> None:
    p = _get_placement(db, placement_id)
    c = _get_canvas(db, p.canvas_id)
    ctx, _ = _canvas_ctx(db, principal, c, AccessLevel.MANAGE)
    if _visible_asset(ctx, p.asset_id) is None:
        raise not_found()
    p.deleted_at = datetime.now(UTC)
    p.updated_by = ctx.user_id
    audit(ctx, "delete", "placement", p.id)
