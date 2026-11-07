"""Home Assistant import: connect, preview what would change, and apply.

The access token is sent with each request, used for that one connection,
and never stored, logged, or returned. Both steps re-read the registries, so
apply always works from what Home Assistant says now, not from a stale preview.
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, SecretStr

from domus.api.deps import CurrentPrincipal, DbSession, PropertyContext, property_context
from domus.homeassistant import importer
from domus.homeassistant.client import HaAuthError, HaError, fetch_registries
from domus.homeassistant.importer import DeviceChoice, ImportPreview, ImportRefused, ImportResult
from domus.homeassistant.registry import HaRegistries
from domus.models.enums import Role

router = APIRouter(prefix="/homeassistant", tags=["homeassistant"])


class HaConnectIn(BaseModel):
    property_id: str | None = None
    base_url: str = Field(
        min_length=1, max_length=2048, examples=["http://homeassistant.local:8123"]
    )
    token: SecretStr = Field(min_length=1, max_length=4096)
    # HA floor id -> Domus building id; floors not listed go to the primary building.
    building_for_floor: dict[str, str] = Field(default_factory=dict[str, str], max_length=500)


class HaApplyIn(HaConnectIn):
    # Devices not listed get the action the preview proposed.
    devices: list[DeviceChoice] = Field(default_factory=list[DeviceChoice], max_length=10000)


def _fetch(ctx: PropertyContext, body: HaConnectIn) -> HaRegistries:
    # Check the role before connecting anywhere, so only maintainers and admins
    # can make the server open a connection.
    ctx.require_role(Role.MAINTAINER)
    try:
        return fetch_registries(body.base_url, body.token.get_secret_value())
    except HaAuthError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except HaError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@router.post("/preview")
def preview_import(body: HaConnectIn, db: DbSession, principal: CurrentPrincipal) -> ImportPreview:
    """Read Home Assistant's registries and show what an import would do. Changes nothing."""
    ctx = property_context(db, principal, body.property_id)
    reg = _fetch(ctx, body)
    try:
        return importer.preview(ctx, reg, body.building_for_floor)
    except ImportRefused as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.post("/apply")
def apply_import(body: HaApplyIn, db: DbSession, principal: CurrentPrincipal) -> ImportResult:
    """Import in one transaction. Running it again with the same choices changes nothing."""
    ctx = property_context(db, principal, body.property_id)
    reg = _fetch(ctx, body)
    try:
        return importer.apply(ctx, reg, body.devices, body.building_for_floor)
    except ImportRefused as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
