"""Search across devices and areas (``GET /api/v1/search``)."""

from typing import Annotated

from fastapi import APIRouter, Query

from domus.api.common import to_out
from domus.api.deps import CurrentPrincipal, DbSession, property_context
from domus.api.routers.assets import asset_summary
from domus.api.schemas import AreaOut, AssetGuestOut, AssetOut, SearchOut
from domus.models import Area, Asset
from domus.models.enums import AccessLevel
from domus.services import search as search_index

router = APIRouter(tags=["search"])

# Hits are read in chunks and filtered by access rules, like list endpoints.
CHUNK = 100
# Stop after this many hits even if a page is not full, so a query that
# matches thousands of hidden items cannot make one request do unbounded work.
MAX_SCANNED = 2000


@router.get("/search")
def search(
    db: DbSession,
    principal: CurrentPrincipal,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    property_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> SearchOut:
    """Find devices and areas by name, notes, product, tags, place, or identifier.

    Every word must match, as a word prefix ("therm" finds "Thermostat").
    Guests never match on identifiers such as serial numbers or MAC
    addresses, or on vendors, since guest responses leave those out.
    """
    ctx = property_context(db, principal, property_id)
    assets: list[AssetOut | AssetGuestOut] = []
    areas: list[AreaOut] = []
    conn = db.connection()
    offset = 0
    while offset < MAX_SCANNED and (len(assets) < limit or len(areas) < limit):
        hits = search_index.search(
            conn,
            ctx.property_id,
            q,
            include_private=not ctx.is_guest,
            limit=CHUNK,
            offset=offset,
        )
        offset += CHUNK
        for hit in hits:
            if hit.kind == search_index.ASSET and len(assets) < limit:
                asset = db.get(Asset, hit.ref_id)
                if asset is None or asset.deleted_at is not None:
                    continue
                if asset.property_id != ctx.property_id:
                    continue
                level = ctx.access.asset_level(asset)
                if level is not AccessLevel.HIDDEN:
                    assets.append(asset_summary(ctx, asset, level))
            elif hit.kind == search_index.AREA and len(areas) < limit:
                area = db.get(Area, hit.ref_id)
                if area is None or area.deleted_at is not None:
                    continue
                if area.property_id != ctx.property_id:
                    continue
                level = ctx.access.area_level(area)
                if level is not AccessLevel.HIDDEN:
                    areas.append(to_out(AreaOut, area, access=level.value))
        if len(hits) < CHUNK:
            break
    return SearchOut(query=q, assets=assets, areas=areas)
