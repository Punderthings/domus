"""Request and response schemas for /api/v1.

Field names follow the data model (and so the JSONL export and Home Assistant
names where they overlap). Every response object carries ``access``: the
caller's level for it, so the UI can hide buttons it would only get a 403 for.

Guests get separate, narrower response schemas: costs, purchase details,
serials, and network identifiers are omitted, not nulled (master plan 2).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, GetCoreSchemaHandler, GetJsonSchemaHandler
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import core_schema

from domus.models import enums

AccessStr = Literal["view", "control", "manage"]


@dataclass(frozen=True)
class OneOf:
    """Annotated metadata: a string limited to ``values``, shown as an enum in OpenAPI."""

    values: Sequence[str]

    def __get_pydantic_core_schema__(
        self, source: type[Any], handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        allowed = tuple(self.values)

        def check(v: str) -> str:
            if v not in allowed:
                raise ValueError(f"must be one of: {', '.join(allowed)}")
            return v

        return core_schema.no_info_after_validator_function(check, handler(source))

    def __get_pydantic_json_schema__(
        self, schema: core_schema.CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        result = handler(schema)
        result["enum"] = list(self.values)
        return result


BuildingKind = Annotated[str, OneOf(enums.BUILDING_KINDS)]
AreaKind = Annotated[str, OneOf(enums.AREA_KINDS)]
LocationKind = Annotated[str, OneOf(enums.LOCATION_KINDS)]
AssetCategory = Annotated[str, OneOf(enums.ASSET_CATEGORIES)]
AssetStatus = Annotated[str, OneOf(enums.ASSET_STATUSES)]
IdentifierKind = Annotated[str, OneOf(enums.IDENTIFIER_KINDS)]
RelationKind = Annotated[str, OneOf(enums.RELATION_KINDS)]
ScheduleKind = Annotated[str, OneOf(enums.SCHEDULE_KINDS)]
IntervalUnit = Annotated[str, OneOf(enums.INTERVAL_UNITS)]
Outcome = Annotated[str, OneOf(enums.EVENT_OUTCOMES)]
RoleStr = Annotated[str, OneOf([r.value for r in enums.Role])]
LevelStr = Annotated[str, OneOf([lv.value for lv in enums.AccessLevel])]
ScopeStr = Annotated[str, OneOf([s.value for s in enums.ScopeType])]
SubjectStr = Annotated[str, OneOf([s.value for s in enums.SubjectType])]

Name = Annotated[str, Field(min_length=1, max_length=200)]
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
Money = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Entity(Out):
    id: str
    created_at: datetime
    updated_at: datetime


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None = None


# --- Auth -----------------------------------------------------------------


class SetupStatus(BaseModel):
    needs_setup: bool


class SampleDataStatus(BaseModel):
    """Whether the sample home can be loaded from the web interface."""

    available: bool  # this install ships the sample dataset
    loaded: bool  # Sample Home already exists with members (or was deleted)
    property_id: str | None  # the Sample Home property, when available


class SetupIn(BaseModel):
    email: Annotated[str, Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")]
    display_name: Name
    password: Annotated[str, Field(min_length=12, max_length=1024)]
    property_name: Name
    timezone: str = "UTC"


class LoginIn(BaseModel):
    email: Annotated[str, Field(max_length=320)]
    password: Annotated[str, Field(max_length=1024)]


class MembershipOut(Out):
    id: str
    property_id: str
    role: str
    expires_at: datetime | None


class MeOut(Out):
    id: str
    email: str
    display_name: str
    memberships: list[MembershipOut]


class TokenIn(BaseModel):
    name: Name
    scopes: list[Literal["read", "write", "calendar"]] = Field(default_factory=lambda: ["read"])
    expires_at: datetime | None = None


class TokenOut(Out):
    id: str
    name: str
    scopes: str
    created_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None


class TokenCreated(TokenOut):
    token: str = Field(description="Shown once; only its hash is stored.")


# --- Members and access rules (Admin only) ----------------------------------


class MemberIn(BaseModel):
    email: Annotated[str, Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")]
    display_name: Name
    password: Annotated[str, Field(min_length=12, max_length=1024)]
    role: RoleStr
    expires_at: datetime | None = None


class MemberUpdate(BaseModel):
    role: RoleStr | None = None
    expires_at: datetime | None = None


class MemberOut(Out):
    id: str
    property_id: str
    user_id: str
    email: str
    display_name: str
    role: str
    expires_at: datetime | None


class AccessRuleIn(BaseModel):
    scope_type: ScopeStr
    scope_id: str
    subject_type: SubjectStr
    subject: str
    level: LevelStr
    expires_at: datetime | None = None
    note: str | None = None


class AccessRuleOut(Entity):
    property_id: str
    scope_type: str
    scope_id: str
    subject_type: str
    subject: str
    level: str
    expires_at: datetime | None
    note: str | None


# --- Space ------------------------------------------------------------------


class PropertyOut(Entity):
    name: str
    address: str | None
    timezone: str
    default_currency: str
    access: AccessStr


class PropertyUpdate(BaseModel):
    name: Name | None = None
    address: str | None = None
    timezone: str | None = None
    default_currency: Currency | None = None


class BuildingIn(BaseModel):
    property_id: str
    name: Name
    kind: BuildingKind = "house"
    is_primary: bool = False
    year_built: int | None = None
    notes: str | None = None


class BuildingUpdate(BaseModel):
    name: Name | None = None
    kind: BuildingKind | None = None
    year_built: int | None = None
    notes: str | None = None


class BuildingOut(Entity):
    property_id: str
    name: str
    kind: str
    is_primary: bool
    year_built: int | None
    notes: str | None
    access: AccessStr


class FloorIn(BaseModel):
    building_id: str
    name: Name
    level: int = 0
    ha_floor_id: str | None = None


class FloorUpdate(BaseModel):
    name: Name | None = None
    level: int | None = None
    ha_floor_id: str | None = None


class FloorOut(Entity):
    building_id: str
    name: str
    level: int
    ha_floor_id: str | None
    access: AccessStr


class AreaIn(BaseModel):
    property_id: str
    building_id: str | None = None
    floor_id: str | None = None
    name: Name
    kind: AreaKind = "room"
    ha_area_id: str | None = None
    is_critical: bool = False


class AreaUpdate(BaseModel):
    building_id: str | None = None
    floor_id: str | None = None
    name: Name | None = None
    kind: AreaKind | None = None
    ha_area_id: str | None = None
    is_critical: bool | None = None


class AreaOut(Entity):
    property_id: str
    building_id: str | None
    floor_id: str | None
    name: str
    kind: str
    ha_area_id: str | None
    is_critical: bool
    access: AccessStr


class LocationIn(BaseModel):
    area_id: str
    parent_location_id: str | None = None
    name: Name
    kind: LocationKind = "wall"
    orientation: str | None = None
    position_note: str | None = None


class LocationUpdate(BaseModel):
    parent_location_id: str | None = None
    name: Name | None = None
    kind: LocationKind | None = None
    orientation: str | None = None
    position_note: str | None = None


class LocationOut(Entity):
    area_id: str
    parent_location_id: str | None
    name: str
    kind: str
    orientation: str | None
    position_note: str | None
    access: AccessStr


# --- Products, tags, assets -------------------------------------------------


class ProductIn(BaseModel):
    manufacturer: str | None = None
    model: str | None = None
    model_id: str | None = None
    category: AssetCategory | None = None
    manual_url: Annotated[str, Field(max_length=2048, pattern=r"^https?://")] | None = None
    support_url: Annotated[str, Field(max_length=2048, pattern=r"^https?://")] | None = None


class ProductOut(Entity):
    manufacturer: str | None
    model: str | None
    model_id: str | None
    category: str | None
    manual_url: str | None
    support_url: str | None


class TagIn(BaseModel):
    property_id: str
    name: Annotated[str, Field(min_length=1, max_length=100)]
    color: Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")] | None = None


class TagOut(Entity):
    property_id: str
    name: str
    color: str | None


class TagRef(Out):
    id: str
    name: str
    color: str | None


class IdentifierIn(BaseModel):
    kind: IdentifierKind
    value: Annotated[str, Field(min_length=1, max_length=256)]
    source: str = "manual"


class IdentifierOut(Out):
    id: str
    kind: str
    value: str
    source: str


class AssetIn(BaseModel):
    property_id: str
    name: Name
    category: AssetCategory = "other"
    status: AssetStatus = "active"
    product_id: str | None = None
    location_id: str | None = None
    parent_asset_id: str | None = None
    install_date: date | None = None
    purchase_date: date | None = None
    purchase_price: Money | None = None
    vendor: str | None = None
    warranty_expires: date | None = None
    sw_version: str | None = None
    hw_version: str | None = None
    is_critical: bool = False
    notes: str | None = None
    tag_ids: list[str] = Field(default_factory=list[str])
    identifiers: list[IdentifierIn] = Field(default_factory=list[IdentifierIn])


class AssetUpdate(BaseModel):
    """Fields a Resident may change on an asset they can control: ``notes`` only."""

    name: Name | None = None
    category: AssetCategory | None = None
    status: AssetStatus | None = None
    product_id: str | None = None
    location_id: str | None = None
    parent_asset_id: str | None = None
    install_date: date | None = None
    purchase_date: date | None = None
    purchase_price: Money | None = None
    vendor: str | None = None
    warranty_expires: date | None = None
    sw_version: str | None = None
    hw_version: str | None = None
    is_critical: bool | None = None
    notes: str | None = None
    tag_ids: list[str] | None = None


RESIDENT_EDITABLE_ASSET_FIELDS = frozenset({"notes"})


class AssetGuestOut(Entity):
    """What a guest may see of an asset."""

    property_id: str
    product_id: str | None
    location_id: str | None
    area_id: str | None
    parent_asset_id: str | None
    name: str
    category: str
    status: str
    is_critical: bool
    notes: str | None
    tags: list[TagRef]
    access: AccessStr


class AssetOut(AssetGuestOut):
    install_date: date | None
    purchase_date: date | None
    purchase_price: Decimal | None
    vendor: str | None
    warranty_expires: date | None
    sw_version: str | None
    hw_version: str | None


class AssetGuestDetailOut(AssetGuestOut):
    product: ProductOut | None
    location: LocationOut | None


class AssetDetailOut(AssetOut):
    product: ProductOut | None
    location: LocationOut | None
    identifiers: list[IdentifierOut]


# --- Maintenance ------------------------------------------------------------


class TaskIn(BaseModel):
    property_id: str
    asset_id: str | None = None
    location_id: str | None = None
    title: Annotated[str, Field(min_length=1, max_length=300)]
    procedure: str | None = None
    schedule_kind: ScheduleKind = "after_completion"
    interval_value: Annotated[int, Field(gt=0, le=1000)] | None = None
    interval_unit: IntervalUnit | None = None
    rrule: Annotated[str, Field(max_length=500)] | None = None
    anchor_date: date | None = None
    next_due: date | None = None
    lead_days: Annotated[int, Field(ge=0, le=365)] = 7
    active: bool = True


class TaskUpdate(BaseModel):
    title: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    procedure: str | None = None
    schedule_kind: ScheduleKind | None = None
    interval_value: Annotated[int, Field(gt=0, le=1000)] | None = None
    interval_unit: IntervalUnit | None = None
    rrule: Annotated[str, Field(max_length=500)] | None = None
    anchor_date: date | None = None
    next_due: date | None = None
    lead_days: Annotated[int, Field(ge=0, le=365)] | None = None
    active: bool | None = None


class TaskOut(Entity):
    property_id: str
    asset_id: str | None
    location_id: str | None
    title: str
    procedure: str | None
    schedule_kind: str
    interval_value: int | None
    interval_unit: str | None
    rrule: str | None
    anchor_date: date | None
    next_due: date | None
    lead_days: int
    active: bool
    access: AccessStr


class CompleteIn(BaseModel):
    performed_on: date
    outcome: Outcome = "done"
    cost: Money | None = None
    currency: Currency | None = None
    notes: str | None = None


class EventGuestOut(Entity):
    task_id: str | None
    asset_id: str | None
    performed_on: date
    outcome: str


class EventOut(EventGuestOut):
    performed_by: str | None
    cost: Decimal | None
    currency: str | None
    vendor: str | None
    duration_min: int | None
    notes: str | None


class CompleteOut(BaseModel):
    event: EventOut
    task: TaskOut
