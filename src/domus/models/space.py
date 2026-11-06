"""Property > Building > Floor > Area > Location (data-storage-backup.md 2.3, 2.3.2)."""

from typing import Any

from sqlalchemy import JSON, CheckConstraint, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from domus.models.base import Base, EntityMixin, ExtraMixin, IdStr


class Property(EntityMixin, ExtraMixin, Base):
    __tablename__ = "property"

    name: Mapped[str] = mapped_column(String(200))
    address: Mapped[str | None] = mapped_column(Text, default=None)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    default_currency: Mapped[str] = mapped_column(String(3), default="USD")


class Building(EntityMixin, ExtraMixin, Base):
    __tablename__ = "building"

    property_id: Mapped[str] = mapped_column(IdStr, ForeignKey("property.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(32), default="house")
    is_primary: Mapped[bool] = mapped_column(default=False)
    year_built: Mapped[int | None] = mapped_column(default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    # Site placement for the future outdoor map, in meters in a local
    # per-property grid (x east, y north). Nullable placeholders in v0.1.
    site_x: Mapped[float | None] = mapped_column(default=None)
    site_y: Mapped[float | None] = mapped_column(default=None)
    rotation_deg: Mapped[float | None] = mapped_column(default=None)
    footprint: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)


class SpatialRelation(EntityMixin, Base):
    __tablename__ = "spatial_relation"

    property_id: Mapped[str] = mapped_column(IdStr, ForeignKey("property.id"), index=True)
    from_type: Mapped[str] = mapped_column(String(16))
    from_id: Mapped[str] = mapped_column(IdStr)
    to_type: Mapped[str] = mapped_column(String(16))
    to_id: Mapped[str] = mapped_column(IdStr)
    kind: Mapped[str] = mapped_column(String(32))
    via: Mapped[str | None] = mapped_column(String(200), default=None)
    distance_m: Mapped[float | None] = mapped_column(default=None)
    bearing_deg: Mapped[float | None] = mapped_column(default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    __table_args__ = (
        CheckConstraint("from_type IN ('building', 'area')", name="from_type"),
        CheckConstraint("to_type IN ('building', 'area')", name="to_type"),
    )


class Floor(EntityMixin, Base):
    __tablename__ = "floor"

    building_id: Mapped[str] = mapped_column(IdStr, ForeignKey("building.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    level: Mapped[int] = mapped_column(default=0)
    ha_floor_id: Mapped[str | None] = mapped_column(String(128), default=None)


class Area(EntityMixin, ExtraMixin, Base):
    """A room or outdoor area. Home Assistant calls these "areas"; the UI says "Room"."""

    __tablename__ = "area"

    property_id: Mapped[str] = mapped_column(IdStr, ForeignKey("property.id"), index=True)
    building_id: Mapped[str | None] = mapped_column(
        IdStr, ForeignKey("building.id"), index=True, default=None
    )
    floor_id: Mapped[str | None] = mapped_column(
        IdStr, ForeignKey("floor.id"), index=True, default=None
    )
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(32), default="room")
    site_x: Mapped[float | None] = mapped_column(default=None)
    site_y: Mapped[float | None] = mapped_column(default=None)
    footprint: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    ha_area_id: Mapped[str | None] = mapped_column(String(128), default=None)
    is_critical: Mapped[bool] = mapped_column(default=False)

    __table_args__ = (
        CheckConstraint("floor_id IS NULL OR building_id IS NOT NULL", name="floor_needs_building"),
    )


class Location(EntityMixin, Base):
    """A spot inside an area: "north wall, left of the window"."""

    __tablename__ = "location"

    area_id: Mapped[str] = mapped_column(IdStr, ForeignKey("area.id"), index=True)
    parent_location_id: Mapped[str | None] = mapped_column(
        IdStr, ForeignKey("location.id"), index=True, default=None
    )
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(32), default="wall")
    orientation: Mapped[str | None] = mapped_column(String(32), default=None)
    position_note: Mapped[str | None] = mapped_column(Text, default=None)
