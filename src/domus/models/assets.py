"""Products, assets, identifiers, relations, and tags (data-storage-backup.md 2.3)."""

from datetime import date
from decimal import Decimal

from sqlalchemy import ForeignKey, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from domus.models.base import Base, EntityMixin, ExtraMixin, IdStr

Money = Numeric(12, 2, asdecimal=True)


class Product(EntityMixin, ExtraMixin, Base):
    """A shared catalog entry: every unit of one model shares one product."""

    __tablename__ = "product"

    manufacturer: Mapped[str | None] = mapped_column(String(200), default=None)
    model: Mapped[str | None] = mapped_column(String(200), default=None)
    model_id: Mapped[str | None] = mapped_column(String(200), default=None)
    category: Mapped[str | None] = mapped_column(String(32), default=None)
    manual_url: Mapped[str | None] = mapped_column(String(2048), default=None)
    support_url: Mapped[str | None] = mapped_column(String(2048), default=None)


class Asset(EntityMixin, ExtraMixin, Base):
    """A physical device, appliance, or piece of equipment (an HA "device" when linked)."""

    __tablename__ = "asset"

    property_id: Mapped[str] = mapped_column(IdStr, ForeignKey("property.id"))
    product_id: Mapped[str | None] = mapped_column(
        IdStr, ForeignKey("product.id"), index=True, default=None
    )
    location_id: Mapped[str | None] = mapped_column(
        IdStr, ForeignKey("location.id"), index=True, default=None
    )
    parent_asset_id: Mapped[str | None] = mapped_column(
        IdStr, ForeignKey("asset.id"), index=True, default=None
    )
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(32), default="other")
    status: Mapped[str] = mapped_column(String(16), default="active")
    install_date: Mapped[date | None] = mapped_column(default=None)
    purchase_date: Mapped[date | None] = mapped_column(default=None)
    purchase_price: Mapped[Decimal | None] = mapped_column(Money, default=None)
    vendor: Mapped[str | None] = mapped_column(String(200), default=None)
    warranty_expires: Mapped[date | None] = mapped_column(default=None)
    sw_version: Mapped[str | None] = mapped_column(String(64), default=None)
    hw_version: Mapped[str | None] = mapped_column(String(64), default=None)
    is_critical: Mapped[bool] = mapped_column(default=False)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    __table_args__ = (Index("ix_asset_property_category", "property_id", "category"),)


class AssetIdentifier(EntityMixin, Base):
    """One id per row: serial, MAC, HA device id, and so on. Drives HA import dedupe."""

    __tablename__ = "asset_identifier"

    asset_id: Mapped[str] = mapped_column(IdStr, ForeignKey("asset.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    value: Mapped[str] = mapped_column(String(256))
    source: Mapped[str] = mapped_column(String(32), default="manual")

    __table_args__ = (Index("ix_asset_identifier_kind_value", "kind", "value"),)


class AssetRelation(EntityMixin, Base):
    """powered_by, networked_via, controls, supplied_by, shutoff_for, drains_to."""

    __tablename__ = "asset_relation"

    from_asset_id: Mapped[str] = mapped_column(IdStr, ForeignKey("asset.id"), index=True)
    to_asset_id: Mapped[str] = mapped_column(IdStr, ForeignKey("asset.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str | None] = mapped_column(String(500), default=None)


class Tag(EntityMixin, Base):
    """A free label; maps to Home Assistant labels."""

    __tablename__ = "tag"

    property_id: Mapped[str] = mapped_column(IdStr, ForeignKey("property.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    color: Mapped[str | None] = mapped_column(String(16), default=None)

    __table_args__ = (UniqueConstraint("property_id", "name"),)


class AssetTag(Base):
    __tablename__ = "asset_tag"

    tag_id: Mapped[str] = mapped_column(IdStr, ForeignKey("tag.id"), primary_key=True)
    asset_id: Mapped[str] = mapped_column(
        IdStr, ForeignKey("asset.id"), primary_key=True, index=True
    )
