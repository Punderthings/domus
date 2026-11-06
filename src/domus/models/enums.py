"""Controlled vocabularies shared by the models, API schemas, and services.

Names follow Home Assistant where the concept overlaps (area, floor, device
categories); see data-storage-backup.md section 2.
"""

from enum import StrEnum


class Role(StrEnum):
    """Per-property membership roles, ranked admin > maintainer > resident > guest."""

    ADMIN = "admin"
    MAINTAINER = "maintainer"
    RESIDENT = "resident"
    GUEST = "guest"


class AccessLevel(StrEnum):
    """The access ladder: hidden < view < control < manage."""

    HIDDEN = "hidden"
    VIEW = "view"
    CONTROL = "control"
    MANAGE = "manage"


LEVEL_RANK: dict[AccessLevel, int] = {
    AccessLevel.HIDDEN: 0,
    AccessLevel.VIEW: 1,
    AccessLevel.CONTROL: 2,
    AccessLevel.MANAGE: 3,
}


class ScopeType(StrEnum):
    BUILDING = "building"
    AREA = "area"
    TAG = "tag"
    ASSET = "asset"


class SubjectType(StrEnum):
    ROLE = "role"
    MEMBERSHIP = "membership"


BUILDING_KINDS = (
    "house",
    "garage",
    "shed",
    "barn",
    "workshop",
    "pool_house",
    "cottage",
    "other",
)

AREA_KINDS = (
    "room",
    "hallway",
    "attic",
    "crawlspace",
    "basement",
    "yard",
    "garden",
    "driveway",
    "patio",
    "pool",
    "other_outdoor",
)

LOCATION_KINDS = (
    "wall",
    "window",
    "door",
    "ceiling",
    "floor",
    "cabinet",
    "closet",
    "exterior_wall",
)

ASSET_CATEGORIES = (
    "appliance",
    "hvac",
    "plumbing",
    "electrical",
    "lighting",
    "network",
    "sensor",
    "security",
    "structural",
    "other",
)

ASSET_STATUSES = ("active", "spare", "retired", "disposed")

IDENTIFIER_KINDS = (
    "serial",
    "mac",
    "zigbee_ieee",
    "zwave_dsk",
    "thread_ext_addr",
    "ble_addr",
    "upc",
    "asset_tag",
    "ha_device_id",
    "ha_entity_id",
    "other",
)

# Identifier kinds that must be unique within a property.
UNIQUE_IDENTIFIER_KINDS = frozenset(
    {
        "mac",
        "zigbee_ieee",
        "zwave_dsk",
        "thread_ext_addr",
        "ble_addr",
        "ha_device_id",
        "ha_entity_id",
    }
)

RELATION_KINDS = (
    "powered_by",
    "networked_via",
    "controls",
    "supplied_by",
    "shutoff_for",
    "drains_to",
)

SPATIAL_KINDS = ("attached_to", "adjacent_to", "detached_from", "connected_by")

SCHEDULE_KINDS = ("after_completion", "fixed_calendar")
INTERVAL_UNITS = ("day", "week", "month", "year")
EVENT_OUTCOMES = ("done", "skipped", "partial", "failed")

DOCUMENT_KINDS = (
    "manual",
    "photo",
    "label_photo",
    "receipt",
    "warranty",
    "invoice",
    "procedure",
    "floor_plan",
    "wall_photo",
    "other",
)
SENSITIVITIES = ("guest", "resident", "admin")

CANVAS_KINDS = ("floor_plan", "wall_photo", "panel_photo", "site_plan")
CANVAS_SCOPES = ("property", "building", "floor", "area")
# Upload types the server accepts, found by magic bytes rather than the
# client's Content-Type. SVG is left out: it can carry script.
IMAGE_MIME_TYPES = ("image/jpeg", "image/png", "image/webp", "image/gif")
UPLOAD_MIME_TYPES = (*IMAGE_MIME_TYPES, "application/pdf")
