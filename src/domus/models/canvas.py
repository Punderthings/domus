"""Images that devices can be pinned onto (data-storage-backup.md 2.3).

A ``Canvas`` is a floor plan, wall photo, or panel photo. A ``Placement`` is one
device pin on it. Pin positions are normalized to 0..1 of the image's width and
height, so they survive replacing the image with one of a different resolution.
"""

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from domus.models.base import Base, EntityMixin, IdStr


class Canvas(EntityMixin, Base):
    __tablename__ = "canvas"

    property_id: Mapped[str] = mapped_column(IdStr, ForeignKey("property.id"), index=True)
    document_id: Mapped[str] = mapped_column(IdStr, ForeignKey("document.id"), index=True)
    scope_type: Mapped[str] = mapped_column(String(16))
    scope_id: Mapped[str] = mapped_column(IdStr, index=True)
    kind: Mapped[str] = mapped_column(String(32))
    name: Mapped[str | None] = mapped_column(String(200), default=None)
    scale_px_per_m: Mapped[float | None] = mapped_column(default=None)

    __table_args__ = (
        CheckConstraint(
            "scope_type IN ('property', 'building', 'floor', 'area')", name="scope_type"
        ),
    )


class Placement(EntityMixin, Base):
    __tablename__ = "placement"

    canvas_id: Mapped[str] = mapped_column(IdStr, ForeignKey("canvas.id"), index=True)
    asset_id: Mapped[str] = mapped_column(IdStr, ForeignKey("asset.id"), index=True)
    x: Mapped[float]
    y: Mapped[float]
    label: Mapped[str | None] = mapped_column(String(200), default=None)
    shape: Mapped[str] = mapped_column(String(16), default="point")

    __table_args__ = (
        CheckConstraint("x >= 0 AND x <= 1", name="x_normalized"),
        CheckConstraint("y >= 0 AND y <= 1", name="y_normalized"),
    )
