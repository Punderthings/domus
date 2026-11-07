"""Match Home Assistant registries against Domus records, preview, and apply.

The rules follow data-storage-backup.md 2.4 ("no duplicates"):

1. A device already linked by ``ha_device_id`` is updated, never duplicated.
2. A ``connections`` value (MAC, Zigbee IEEE, Bluetooth) equal to an existing
   identifier proposes a link.
3. Serial number plus manufacturer proposes a link.
4. A similar name (and compatible model) in the same Area is a possible match.
5. Otherwise the device is new.

Applying is idempotent: running the same import twice changes nothing the
second time. Home Assistant never overwrites a Domus field the user owns,
such as a device's name; only firmware and hardware versions, missing
identifiers, a missing product, and the stored HA snapshot are updated.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import select

from domus.api.common import audit
from domus.api.deps import PropertyContext
from domus.homeassistant.registry import HaArea, HaDevice, HaFloor, HaRegistries
from domus.models import (
    Area,
    Asset,
    AssetIdentifier,
    AssetRelation,
    AssetTag,
    Building,
    Floor,
    Location,
    Product,
    Tag,
)
from domus.models.enums import AccessLevel, Role
from domus.services.access import at_least

SOURCE = "home_assistant"
EXTRA_KEY = "home_assistant"
UNSPECIFIED_LOCATION_KIND = "unspecified"
UNSPECIFIED_LOCATION_NAME = "Somewhere in this area"
NAME_SIMILARITY = 0.85

# HA connection type -> Domus identifier kind.
CONNECTION_KINDS: dict[str, str] = {
    "mac": "mac",
    "zigbee": "zigbee_ieee",
    "bluetooth": "ble_addr",
}

# The first entity domain found on a device, in this order, picks its category.
CATEGORY_BY_DOMAIN: tuple[tuple[str, str], ...] = (
    ("lock", "security"),
    ("alarm_control_panel", "security"),
    ("camera", "security"),
    ("siren", "security"),
    ("climate", "hvac"),
    ("water_heater", "hvac"),
    ("humidifier", "hvac"),
    ("fan", "hvac"),
    ("valve", "plumbing"),
    ("light", "lighting"),
    ("vacuum", "appliance"),
    ("media_player", "appliance"),
    ("remote", "appliance"),
    ("switch", "electrical"),
    ("binary_sensor", "sensor"),
    ("sensor", "sensor"),
    ("device_tracker", "network"),
)

DeviceStatus = Literal["new", "matched", "linked", "changed", "ignored"]
MatchReason = Literal["ha_device_id", "connection", "serial", "name"]
Action = Literal["create", "link", "skip"]


# --- Preview and result models ----------------------------------------------


class FieldChange(BaseModel):
    field: str
    old: str | None
    new: str | None


class IdentifierPlan(BaseModel):
    kind: str
    value: str


class FloorPlan(BaseModel):
    ha_floor_id: str
    name: str
    level: int | None
    status: Literal["new", "matched"]
    floor_id: str | None
    building_id: str


class AreaPlan(BaseModel):
    ha_area_id: str
    name: str
    ha_floor_id: str | None
    status: Literal["new", "matched"]
    match_reason: Literal["ha_area_id", "name"] | None
    area_id: str | None


class DevicePlan(BaseModel):
    ha_device_id: str
    name: str
    manufacturer: str | None
    model: str | None
    ha_area_id: str | None
    area_name: str | None
    status: DeviceStatus
    match_reason: MatchReason | None
    asset_id: str | None
    # None when the matched device is one the caller may not see.
    asset_name: str | None
    action: Action
    # False when the caller may not change the matched device or its Area.
    can_apply: bool
    changes: list[FieldChange]
    new_identifiers: list[IdentifierPlan]
    note: str | None


class ImportPreview(BaseModel):
    floors: list[FloorPlan]
    areas: list[AreaPlan]
    devices: list[DevicePlan]
    counts: dict[str, int]


class DeviceChoice(BaseModel):
    ha_device_id: str
    action: Action
    # For "link": the Domus device to link to. Defaults to the proposed match.
    asset_id: str | None = None


class DeviceResult(BaseModel):
    ha_device_id: str
    name: str
    outcome: Literal["created", "updated", "unchanged", "skipped"]
    asset_id: str | None
    note: str | None


class ImportResult(BaseModel):
    floors_created: int
    areas_created: int
    devices: list[DeviceResult]
    relations_created: int
    counts: dict[str, int]


class ImportRefused(Exception):
    """A choice that can't be applied; the whole import is rolled back."""


# --- Helpers ----------------------------------------------------------------


def normalize_identifier(kind: str, value: str) -> str:
    """Match the normalization used by the asset identifier endpoints."""
    value = value.strip()
    if kind in {"mac", "zigbee_ieee", "ble_addr"}:
        value = value.lower().replace("-", ":")
    return value


def _norm_name(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").casefold()).strip()


def _similar(a: str | None, b: str | None) -> bool:
    na, nb = _norm_name(a), _norm_name(b)
    if not na or not nb:
        return False
    return na == nb or SequenceMatcher(None, na, nb).ratio() >= NAME_SIMILARITY


def device_identifiers(device: HaDevice) -> list[IdentifierPlan]:
    """The Domus identifier rows a HA device implies, ha_device_id first."""
    out = [IdentifierPlan(kind="ha_device_id", value=device.id)]
    for conn_type, value in device.connections:
        kind = CONNECTION_KINDS.get(conn_type)
        if kind and value.strip():
            out.append(IdentifierPlan(kind=kind, value=normalize_identifier(kind, value)))
    if device.serial_number and device.serial_number.strip():
        out.append(IdentifierPlan(kind="serial", value=device.serial_number.strip()))
    seen: set[tuple[str, str]] = set()
    unique: list[IdentifierPlan] = []
    for ident in out:
        if (ident.kind, ident.value) not in seen:
            seen.add((ident.kind, ident.value))
            unique.append(ident)
    return unique


def snapshot(device: HaDevice, entity_ids: list[str]) -> dict[str, Any]:
    """The HA registry fields kept on the asset, for "last known" context offline."""
    return {
        "device_id": device.id,
        "name": device.name,
        "name_by_user": device.name_by_user,
        "manufacturer": device.manufacturer,
        "model": device.model,
        "model_id": device.model_id,
        "serial_number": device.serial_number,
        "sw_version": device.sw_version,
        "hw_version": device.hw_version,
        "area_id": device.area_id,
        "via_device_id": device.via_device_id,
        "connections": [list(p) for p in device.connections],
        "identifiers": [list(p) for p in device.identifiers],
        "entity_ids": sorted(entity_ids),
    }


def category_for(domains: Iterable[str]) -> str:
    present = set(domains)
    for domain, category in CATEGORY_BY_DOMAIN:
        if domain in present:
            return category
    return "other"


def _product_label(manufacturer: str | None, model: str | None) -> str | None:
    label = " ".join(p for p in (manufacturer, model) if p)
    return label or None


# --- Snapshot of the Domus side ---------------------------------------------


@dataclass
class _Domus:
    """The property's current records, loaded once per preview or apply."""

    ctx: PropertyContext
    primary_building: Building
    buildings: dict[str, Building]
    floors: list[Floor]
    areas: list[Area]
    assets: dict[str, Asset]
    products: dict[str, Product]
    # (kind, value) -> asset id, for live identifiers on live assets.
    identifiers: dict[tuple[str, str], str]
    identifiers_by_asset: dict[str, set[tuple[str, str]]]
    asset_area: dict[str, str | None] = field(default_factory=dict[str, str | None])

    @classmethod
    def load(cls, ctx: PropertyContext) -> _Domus:
        db = ctx.db
        pid = ctx.property_id
        buildings = {
            b.id: b
            for b in db.scalars(
                select(Building).where(Building.property_id == pid, Building.deleted_at.is_(None))
            )
        }
        if not buildings:
            raise ImportRefused("This property has no building to import into")
        primary = next((b for b in buildings.values() if b.is_primary), None)
        primary = primary or min(buildings.values(), key=lambda b: b.id)
        floors = list(
            db.scalars(
                select(Floor).where(Floor.building_id.in_(buildings), Floor.deleted_at.is_(None))
            )
        )
        areas = list(
            db.scalars(select(Area).where(Area.property_id == pid, Area.deleted_at.is_(None)))
        )
        assets = {
            a.id: a
            for a in db.scalars(
                select(Asset).where(Asset.property_id == pid, Asset.deleted_at.is_(None))
            )
        }
        product_ids = {a.product_id for a in assets.values() if a.product_id}
        products = (
            {p.id: p for p in db.scalars(select(Product).where(Product.id.in_(product_ids)))}
            if product_ids
            else {}
        )
        identifiers: dict[tuple[str, str], str] = {}
        by_asset: dict[str, set[tuple[str, str]]] = {}
        if assets:
            for row in db.scalars(
                select(AssetIdentifier).where(
                    AssetIdentifier.asset_id.in_(assets), AssetIdentifier.deleted_at.is_(None)
                )
            ):
                key = (row.kind, row.value)
                identifiers.setdefault(key, row.asset_id)
                by_asset.setdefault(row.asset_id, set()).add(key)
        domus = cls(ctx, primary, buildings, floors, areas, assets, products, identifiers, by_asset)
        locations = {
            loc.id: loc.area_id
            for loc in db.scalars(
                select(Location).where(Location.area_id.in_([a.id for a in areas]))
            )
        }
        for a in assets.values():
            domus.asset_area[a.id] = locations.get(a.location_id) if a.location_id else None
        return domus

    def can_manage_asset(self, asset: Asset) -> bool:
        return at_least(self.ctx.access.asset_level(asset), AccessLevel.MANAGE)

    def can_see_asset(self, asset: Asset) -> bool:
        return self.ctx.access.asset_level(asset) is not AccessLevel.HIDDEN

    def can_manage_area(self, area: Area) -> bool:
        return at_least(self.ctx.access.area_level(area), AccessLevel.MANAGE)


# --- Matching ---------------------------------------------------------------


@dataclass
class _Matching:
    floors: list[FloorPlan]
    areas: list[AreaPlan]
    devices: list[DevicePlan]
    # ha_area_id -> Domus area (existing only).
    area_for: dict[str, Area]
    entity_ids: dict[str, list[str]]
    domains: dict[str, set[str]]


def _match_floors(
    reg: HaRegistries, domus: _Domus, building_for_floor: dict[str, str]
) -> tuple[list[FloorPlan], dict[str, Floor]]:
    plans: list[FloorPlan] = []
    found: dict[str, Floor] = {}
    for hf in reg.floors:
        building_id = building_for_floor.get(hf.floor_id, domus.primary_building.id)
        if building_id not in domus.buildings:
            raise ImportRefused(f"Unknown building for floor {hf.name!r}")
        floor = next((f for f in domus.floors if f.ha_floor_id == hf.floor_id), None)
        if floor is None:
            floor = next(
                (
                    f
                    for f in domus.floors
                    if f.building_id == building_id
                    and f.ha_floor_id is None
                    and _norm_name(f.name) == _norm_name(hf.name)
                ),
                None,
            )
        if floor is not None:
            found[hf.floor_id] = floor
        plans.append(
            FloorPlan(
                ha_floor_id=hf.floor_id,
                name=hf.name,
                level=hf.level,
                status="matched" if floor else "new",
                floor_id=floor.id if floor else None,
                building_id=floor.building_id if floor else building_id,
            )
        )
    return plans, found


def _match_areas(reg: HaRegistries, domus: _Domus) -> tuple[list[AreaPlan], dict[str, Area]]:
    plans: list[AreaPlan] = []
    found: dict[str, Area] = {}
    claimed: set[str] = set()
    for ha in reg.areas:
        area = next((a for a in domus.areas if a.ha_area_id == ha.area_id), None)
        reason: Literal["ha_area_id", "name"] | None = "ha_area_id" if area else None
        if area is None:
            area = next(
                (
                    a
                    for a in domus.areas
                    if a.ha_area_id is None
                    and a.id not in claimed
                    and _norm_name(a.name) == _norm_name(ha.name)
                ),
                None,
            )
            reason = "name" if area else None
        if area is not None:
            found[ha.area_id] = area
            claimed.add(area.id)
        plans.append(
            AreaPlan(
                ha_area_id=ha.area_id,
                name=ha.name,
                ha_floor_id=ha.floor_id,
                status="matched" if area else "new",
                match_reason=reason,
                area_id=area.id if area else None,
            )
        )
    return plans, found


def _changes(domus: _Domus, asset: Asset, device: HaDevice) -> list[FieldChange]:
    out: list[FieldChange] = []
    for name in ("sw_version", "hw_version"):
        new = getattr(device, name)
        old = getattr(asset, name)
        if new and new != old:
            out.append(FieldChange(field=name, old=old, new=new))
    if asset.product_id is None and (label := _product_label(device.manufacturer, device.model)):
        out.append(FieldChange(field="product", old=None, new=label))
    return out


def _new_identifiers(
    domus: _Domus, asset_id: str | None, device: HaDevice
) -> tuple[list[IdentifierPlan], list[str]]:
    """Identifiers to add to ``asset_id`` and the ones another device already holds."""
    have: set[tuple[str, str]] = (
        domus.identifiers_by_asset.get(asset_id, set()) if asset_id else set()
    )
    add: list[IdentifierPlan] = []
    clashes: list[str] = []
    for ident in device_identifiers(device):
        key = (ident.kind, ident.value)
        if key in have:
            continue
        owner = domus.identifiers.get(key)
        if owner is not None and owner != asset_id and ident.kind != "serial":
            clashes.append(ident.kind)
            continue
        add.append(ident)
    return add, clashes


def _ignored_reason(device: HaDevice) -> str | None:
    if device.entry_type == "service":
        return "A Home Assistant service, not a physical device"
    if device.disabled_by:
        return "Disabled in Home Assistant"
    return None


def match(
    reg: HaRegistries, domus: _Domus, building_for_floor: dict[str, str] | None = None
) -> _Matching:
    floors, _ = _match_floors(reg, domus, building_for_floor or {})
    areas, area_for = _match_areas(reg, domus)
    ha_area_names = {a.area_id: a.name for a in reg.areas}
    entity_ids: dict[str, list[str]] = {}
    domains: dict[str, set[str]] = {}
    for ent in reg.entities:
        if ent.device_id:
            entity_ids.setdefault(ent.device_id, []).append(ent.entity_id)
            if not ent.disabled_by:
                domains.setdefault(ent.device_id, set()).add(ent.domain)

    claimed: set[str] = set()
    found: dict[str, tuple[Asset, MatchReason]] = {}
    # Pass 1: devices already linked. These always win their asset.
    for device in reg.devices:
        owner = domus.identifiers.get(("ha_device_id", device.id))
        if owner is not None and owner in domus.assets:
            found[device.id] = (domus.assets[owner], "ha_device_id")
            claimed.add(owner)
    # Linked assets can't be claimed again by a weaker match.
    linked_assets = {aid for (kind, _), aid in domus.identifiers.items() if kind == "ha_device_id"}
    claimed |= linked_assets
    # Pass 2: strong identifiers, then serial, then names.
    for device in reg.devices:
        if device.id in found or _ignored_reason(device):
            continue
        hit = _strong_match(domus, device, claimed) or _name_match(domus, device, area_for, claimed)
        if hit is not None:
            found[device.id] = hit
            claimed.add(hit[0].id)

    plans: list[DevicePlan] = []
    for device in reg.devices:
        area = area_for.get(device.area_id) if device.area_id else None
        area_name = area.name if area else ha_area_names.get(device.area_id or "")
        hit = found.get(device.id)
        asset = hit[0] if hit else None
        reason = hit[1] if hit else None
        add, clashes = _new_identifiers(domus, asset.id if asset else None, device)
        changes = _changes(domus, asset, device) if asset else []
        notes: list[str] = []
        if clashes:
            notes.append(f"Another Domus device already has this {', '.join(sorted(clashes))}")
        ignored = _ignored_reason(device)
        if asset is None:
            status: DeviceStatus = "ignored" if ignored else "new"
            can_apply = area is None or domus.can_manage_area(area)
            if not can_apply:
                notes.append("You can't add devices to this Area")
            action: Action = "create" if status == "new" and can_apply else "skip"
            if ignored:
                notes.append(ignored)
        else:
            if reason == "ha_device_id":
                status = "changed" if changes or add else "linked"
            else:
                status = "matched"
            can_apply = domus.can_manage_asset(asset)
            if not can_apply:
                notes.append("You can't change the matching Domus device")
            action = "link" if can_apply and status != "linked" else "skip"
        plans.append(
            DevicePlan(
                ha_device_id=device.id,
                name=device.display_name,
                manufacturer=device.manufacturer,
                model=device.model,
                ha_area_id=device.area_id,
                area_name=area_name,
                status=status,
                match_reason=reason,
                asset_id=asset.id if asset and domus.can_see_asset(asset) else None,
                asset_name=asset.name if asset and domus.can_see_asset(asset) else None,
                action=action,
                can_apply=can_apply,
                changes=changes,
                new_identifiers=add,
                note="; ".join(notes) or None,
            )
        )
    return _Matching(floors, areas, plans, area_for, entity_ids, domains)


def _strong_match(
    domus: _Domus, device: HaDevice, claimed: set[str]
) -> tuple[Asset, MatchReason] | None:
    for ident in device_identifiers(device):
        if ident.kind in ("ha_device_id", "serial"):
            continue
        owner = domus.identifiers.get((ident.kind, ident.value))
        if owner is not None and owner not in claimed and owner in domus.assets:
            return domus.assets[owner], "connection"
    if device.serial_number and device.manufacturer:
        serial = device.serial_number.strip()
        for (kind, value), owner in domus.identifiers.items():
            if kind != "serial" or value != serial or owner in claimed:
                continue
            asset = domus.assets.get(owner)
            product = domus.products.get(asset.product_id or "") if asset else None
            if (
                asset is not None
                and product is not None
                and _norm_name(product.manufacturer) == _norm_name(device.manufacturer)
            ):
                return asset, "serial"
    return None


def _name_match(
    domus: _Domus, device: HaDevice, area_for: dict[str, Area], claimed: set[str]
) -> tuple[Asset, MatchReason] | None:
    area = area_for.get(device.area_id) if device.area_id else None
    if area is None:
        return None
    for asset in domus.assets.values():
        if asset.id in claimed or domus.asset_area.get(asset.id) != area.id:
            continue
        if not (_similar(asset.name, device.name) or _similar(asset.name, device.name_by_user)):
            continue
        product = domus.products.get(asset.product_id or "")
        if (
            product
            and product.model
            and device.model
            and _norm_name(product.model) != _norm_name(device.model)
        ):
            continue
        return asset, "name"
    return None


def _counts(values: Iterable[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return out


def preview(
    ctx: PropertyContext, reg: HaRegistries, building_for_floor: dict[str, str] | None = None
) -> ImportPreview:
    ctx.require_role(Role.MAINTAINER)
    domus = _Domus.load(ctx)
    m = match(reg, domus, building_for_floor)
    return ImportPreview(
        floors=m.floors,
        areas=m.areas,
        devices=m.devices,
        counts=_counts(d.status for d in m.devices),
    )


# --- Apply ------------------------------------------------------------------


class _Applier:
    def __init__(self, ctx: PropertyContext, reg: HaRegistries, domus: _Domus) -> None:
        self.ctx = ctx
        self.db = ctx.db
        self.reg = reg
        self.domus = domus
        self.floor_for: dict[str, Floor] = {}
        self.area_for: dict[str, Area] = {}
        self.unspecified: dict[str, Location] = {}
        self.tags: dict[str, Tag] = {}
        self.floors_created = 0
        self.areas_created = 0

    def _who(self) -> dict[str, str]:
        return {"created_by": self.ctx.user_id, "updated_by": self.ctx.user_id}

    # Floors and Areas

    def floors(self, plans: list[FloorPlan], ha_floors: dict[str, HaFloor]) -> None:
        manage_building = {
            bid: at_least(self.ctx.access.building_level(b), AccessLevel.MANAGE)
            for bid, b in self.domus.buildings.items()
        }
        for plan in plans:
            if plan.floor_id is not None:
                floor = self.db.get(Floor, plan.floor_id)
                assert floor is not None  # noqa: S101 - loaded moments ago
                if floor.ha_floor_id is None and manage_building[floor.building_id]:
                    floor.ha_floor_id = plan.ha_floor_id
                    floor.updated_by = self.ctx.user_id
                self.floor_for[plan.ha_floor_id] = floor
                continue
            if not manage_building[plan.building_id]:
                continue
            hf = ha_floors[plan.ha_floor_id]
            floor = Floor(
                building_id=plan.building_id,
                name=hf.name,
                level=hf.level or 0,
                ha_floor_id=hf.floor_id,
                **self._who(),
            )
            self.db.add(floor)
            self.db.flush()
            audit(self.ctx, "create", "floor", floor.id, {"source": SOURCE})
            self.floor_for[plan.ha_floor_id] = floor
            self.floors_created += 1

    def areas(self, plans: list[AreaPlan], ha_areas: dict[str, HaArea]) -> None:
        for plan in plans:
            if plan.area_id is not None:
                area = self.db.get(Area, plan.area_id)
                assert area is not None  # noqa: S101 - loaded moments ago
                if area.ha_area_id is None and self.domus.can_manage_area(area):
                    area.ha_area_id = plan.ha_area_id
                    area.updated_by = self.ctx.user_id
                    audit(self.ctx, "update", "area", area.id, {"ha_area_id": plan.ha_area_id})
                self.area_for[plan.ha_area_id] = area
                continue
            ha = ha_areas[plan.ha_area_id]
            floor = self.floor_for.get(ha.floor_id) if ha.floor_id else None
            building = (
                self.domus.buildings[floor.building_id] if floor else self.domus.primary_building
            )
            if not at_least(self.ctx.access.building_level(building), AccessLevel.MANAGE):
                continue
            area = Area(
                property_id=self.ctx.property_id,
                building_id=building.id,
                floor_id=floor.id if floor else None,
                name=ha.name,
                ha_area_id=ha.area_id,
                **self._who(),
            )
            self.db.add(area)
            self.db.flush()
            audit(self.ctx, "create", "area", area.id, {"source": SOURCE})
            self.area_for[plan.ha_area_id] = area
            self.areas_created += 1
        self.ctx.refresh_access()

    def location_in(self, area: Area) -> Location:
        if area.id in self.unspecified:
            return self.unspecified[area.id]
        loc = self.db.scalar(
            select(Location)
            .where(
                Location.area_id == area.id,
                Location.kind == UNSPECIFIED_LOCATION_KIND,
                Location.deleted_at.is_(None),
            )
            .order_by(Location.id)
            .limit(1)
        )
        if loc is None:
            loc = Location(
                area_id=area.id,
                name=UNSPECIFIED_LOCATION_NAME,
                kind=UNSPECIFIED_LOCATION_KIND,
                **self._who(),
            )
            self.db.add(loc)
            self.db.flush()
            audit(self.ctx, "create", "location", loc.id, {"source": SOURCE})
        self.unspecified[area.id] = loc
        return loc

    # Products, tags, identifiers

    def product_for(self, device: HaDevice) -> Product | None:
        if not (device.manufacturer or device.model):
            return None
        product = self.db.scalar(
            select(Product)
            .where(
                Product.manufacturer == device.manufacturer,
                Product.model == device.model,
                Product.model_id == device.model_id,
                Product.deleted_at.is_(None),
            )
            .order_by(Product.id)
            .limit(1)
        )
        if product is None:
            product = Product(
                manufacturer=device.manufacturer,
                model=device.model,
                model_id=device.model_id,
                **self._who(),
            )
            self.db.add(product)
            self.db.flush()
            audit(self.ctx, "create", "product", product.id, {"source": SOURCE})
        return product

    def tag_ids(self, device: HaDevice) -> list[str]:
        names = {lb.label_id: lb for lb in self.reg.labels}
        out: list[str] = []
        for label_id in device.labels:
            label = names.get(label_id)
            if label is None or not label.name.strip():
                continue
            key = label.name.strip()
            if key not in self.tags:
                tag = self.db.scalar(
                    select(Tag).where(Tag.property_id == self.ctx.property_id, Tag.name == key)
                )
                if tag is None:
                    tag = Tag(
                        property_id=self.ctx.property_id,
                        name=key,
                        color=label.color,
                        **self._who(),
                    )
                    self.db.add(tag)
                    self.db.flush()
                    audit(self.ctx, "create", "tag", tag.id, {"source": SOURCE})
                elif tag.deleted_at is not None:
                    continue
                self.tags[key] = tag
            out.append(self.tags[key].id)
        return out

    def add_tags(self, asset: Asset, tag_ids: list[str]) -> bool:
        have = set(self.db.scalars(select(AssetTag.tag_id).where(AssetTag.asset_id == asset.id)))
        new = [t for t in dict.fromkeys(tag_ids) if t not in have]
        self.db.add_all([AssetTag(asset_id=asset.id, tag_id=t) for t in new])
        return bool(new)

    def add_identifiers(self, asset: Asset, idents: list[IdentifierPlan]) -> None:
        for ident in idents:
            key = (ident.kind, ident.value)
            owner = self.domus.identifiers.get(key)
            if owner is not None and (owner != asset.id and ident.kind != "serial"):
                continue
            if key in self.domus.identifiers_by_asset.get(asset.id, set()):
                continue
            self.db.add(
                AssetIdentifier(
                    asset_id=asset.id,
                    kind=ident.kind,
                    value=ident.value,
                    source=SOURCE,
                    **self._who(),
                )
            )
            self.domus.identifiers.setdefault(key, asset.id)
            self.domus.identifiers_by_asset.setdefault(asset.id, set()).add(key)

    # Devices

    def create(self, device: HaDevice, plan: DevicePlan, m: _Matching) -> DeviceResult:
        area = self.area_for.get(device.area_id) if device.area_id else None
        if area is not None and not self.domus.can_manage_area(area):
            return self._skipped(device, "You can't add devices to this Area")
        location = self.location_in(area) if area else None
        product = self.product_for(device)
        asset = Asset(
            property_id=self.ctx.property_id,
            product_id=product.id if product else None,
            location_id=location.id if location else None,
            name=device.display_name,
            category=category_for(m.domains.get(device.id, set())),
            sw_version=device.sw_version,
            hw_version=device.hw_version,
            extra={EXTRA_KEY: snapshot(device, m.entity_ids.get(device.id, []))},
            **self._who(),
        )
        self.db.add(asset)
        self.db.flush()
        self.domus.assets[asset.id] = asset
        self.add_identifiers(asset, device_identifiers(device))
        self.add_tags(asset, self.tag_ids(device))
        audit(
            self.ctx,
            "create",
            "asset",
            asset.id,
            {"name": asset.name, "source": SOURCE, "ha_device_id": device.id},
        )
        return DeviceResult(
            ha_device_id=device.id,
            name=device.display_name,
            outcome="created",
            asset_id=asset.id,
            note=plan.note,
        )

    def link(self, device: HaDevice, asset: Asset, m: _Matching) -> DeviceResult:
        diff: dict[str, Any] = {}
        for change in _changes(self.domus, asset, device):
            if change.field == "product":
                product = self.product_for(device)
                if product is not None:
                    asset.product_id = product.id
                    self.domus.products[product.id] = product
                    diff["product_id"] = product.id
            else:
                setattr(asset, change.field, change.new)
                diff[change.field] = [change.old, change.new]
        add, _ = _new_identifiers(self.domus, asset.id, device)
        self.add_identifiers(asset, add)
        if add:
            diff["identifiers"] = [i.kind for i in add]
        if self.add_tags(asset, self.tag_ids(device)):
            diff["tags"] = "added"
        snap = snapshot(device, m.entity_ids.get(device.id, []))
        extra = dict(asset.extra or {})
        snapshot_changed = extra.get(EXTRA_KEY) != snap
        if snapshot_changed:
            extra[EXTRA_KEY] = snap
            asset.extra = extra
        if diff or snapshot_changed:
            asset.updated_by = self.ctx.user_id
        if diff:
            diff.update(source=SOURCE, ha_device_id=device.id)
            audit(self.ctx, "update", "asset", asset.id, diff)
        return DeviceResult(
            ha_device_id=device.id,
            name=device.display_name,
            outcome="updated" if diff else "unchanged",
            asset_id=asset.id,
            note=None,
        )

    def _skipped(self, device: HaDevice, note: str | None) -> DeviceResult:
        return DeviceResult(
            ha_device_id=device.id,
            name=device.display_name,
            outcome="skipped",
            asset_id=None,
            note=note,
        )

    def device(
        self, device: HaDevice, plan: DevicePlan, choice: DeviceChoice | None, m: _Matching
    ) -> DeviceResult:
        action = choice.action if choice else plan.action
        linked_to = self.domus.identifiers.get(("ha_device_id", device.id))
        if action == "skip":
            if linked_to is not None:
                return DeviceResult(
                    ha_device_id=device.id,
                    name=device.display_name,
                    outcome="unchanged",
                    asset_id=plan.asset_id,
                    note=plan.note,
                )
            return self._skipped(device, plan.note)
        if action == "create":
            if linked_to is not None:
                # Never duplicate a linked device, whatever the request says.
                return self.link(device, self.domus.assets[linked_to], m)
            if plan.status == "ignored" and choice is None:
                return self._skipped(device, plan.note)
            return self.create(device, plan, m)
        # link
        asset_id = (choice.asset_id if choice else None) or plan.asset_id
        if asset_id is None and linked_to is not None:
            asset_id = linked_to
        asset = self.domus.assets.get(asset_id or "")
        if asset is None or not self.domus.can_see_asset(asset):
            raise ImportRefused(f"No Domus device to link {device.display_name!r} to")
        if linked_to is not None and linked_to != asset.id:
            raise ImportRefused(f"{device.display_name!r} is already linked to another device")
        other = self.domus.identifiers_by_asset.get(asset.id, set())
        if any(k == "ha_device_id" and v != device.id for k, v in other):
            raise ImportRefused(
                f"That Domus device is already linked to another Home Assistant device"
                f" (importing {device.display_name!r})"
            )
        if not self.domus.can_manage_asset(asset):
            raise ImportRefused(f"You can't change the Domus device for {device.display_name!r}")
        return self.link(device, asset, m)

    def relations(self, results: dict[str, DeviceResult]) -> int:
        made = 0
        for device in self.reg.devices:
            via = device.via_device_id
            here = results.get(device.id)
            hub = results.get(via) if via else None
            if not (here and hub and here.asset_id and hub.asset_id):
                continue
            if here.asset_id == hub.asset_id:
                continue
            exists = self.db.scalar(
                select(AssetRelation.id).where(
                    AssetRelation.from_asset_id == here.asset_id,
                    AssetRelation.to_asset_id == hub.asset_id,
                    AssetRelation.kind == "networked_via",
                    AssetRelation.deleted_at.is_(None),
                )
            )
            if exists is None:
                rel = AssetRelation(
                    from_asset_id=here.asset_id,
                    to_asset_id=hub.asset_id,
                    kind="networked_via",
                    detail="From Home Assistant",
                    **self._who(),
                )
                self.db.add(rel)
                self.db.flush()
                audit(self.ctx, "create", "asset_relation", rel.id, {"source": SOURCE})
                made += 1
        return made


def apply(
    ctx: PropertyContext,
    reg: HaRegistries,
    choices: list[DeviceChoice],
    building_for_floor: dict[str, str] | None = None,
) -> ImportResult:
    """Apply an import in the caller's transaction. Raises ImportRefused on a bad choice."""
    ctx.require_role(Role.MAINTAINER)
    domus = _Domus.load(ctx)
    m = match(reg, domus, building_for_floor)
    by_id = {c.ha_device_id: c for c in choices}
    known = {d.id for d in reg.devices}
    unknown = set(by_id) - known
    if unknown:
        raise ImportRefused("Some chosen devices are no longer in Home Assistant; preview again")
    applier = _Applier(ctx, reg, domus)
    applier.floors(m.floors, {f.floor_id: f for f in reg.floors})
    applier.areas(m.areas, {a.area_id: a for a in reg.areas})
    results: dict[str, DeviceResult] = {}
    plans = {p.ha_device_id: p for p in m.devices}
    for device in reg.devices:
        results[device.id] = applier.device(device, plans[device.id], by_id.get(device.id), m)
        ctx.db.flush()
    ctx.refresh_access()
    relations = applier.relations(results)
    outcomes = [r.outcome for r in results.values()]
    audit(
        ctx,
        "import",
        "home_assistant",
        ctx.property_id,
        {"devices": len(outcomes), **_counts(outcomes)},
    )
    return ImportResult(
        floors_created=applier.floors_created,
        areas_created=applier.areas_created,
        devices=list(results.values()),
        relations_created=relations,
        counts=_counts(outcomes),
    )
