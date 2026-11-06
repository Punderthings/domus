"""Maintenance tasks and the service history (data-storage-backup.md 2.3)."""

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from domus.models.assets import Money
from domus.models.base import Base, EntityMixin, ExtraMixin, IdStr


class MaintenanceTask(EntityMixin, ExtraMixin, Base):
    """A recurring job on an asset or a location.

    ``schedule_kind`` is ``after_completion`` (every N units after it was last
    done) or ``fixed_calendar`` (an RFC 5545 RRULE from ``anchor_date``).
    """

    __tablename__ = "maintenance_task"

    property_id: Mapped[str] = mapped_column(IdStr, ForeignKey("property.id"))
    asset_id: Mapped[str | None] = mapped_column(
        IdStr, ForeignKey("asset.id"), index=True, default=None
    )
    location_id: Mapped[str | None] = mapped_column(
        IdStr, ForeignKey("location.id"), index=True, default=None
    )
    title: Mapped[str] = mapped_column(String(300))
    procedure: Mapped[str | None] = mapped_column(Text, default=None)
    schedule_kind: Mapped[str] = mapped_column(String(32), default="after_completion")
    interval_value: Mapped[int | None] = mapped_column(default=None)
    interval_unit: Mapped[str | None] = mapped_column(String(8), default=None)
    rrule: Mapped[str | None] = mapped_column(String(500), default=None)
    anchor_date: Mapped[date | None] = mapped_column(default=None)
    next_due: Mapped[date | None] = mapped_column(default=None)
    lead_days: Mapped[int] = mapped_column(default=7)
    active: Mapped[bool] = mapped_column(default=True)
    assignee_role: Mapped[str | None] = mapped_column(String(16), default=None)

    __table_args__ = (Index("ix_maintenance_task_property_next_due", "property_id", "next_due"),)


class MaintenanceEvent(EntityMixin, Base):
    """One completed (or skipped) piece of work, with cost and notes."""

    __tablename__ = "maintenance_event"

    task_id: Mapped[str | None] = mapped_column(
        IdStr, ForeignKey("maintenance_task.id"), index=True, default=None
    )
    asset_id: Mapped[str | None] = mapped_column(
        IdStr, ForeignKey("asset.id"), index=True, default=None
    )
    performed_on: Mapped[date]
    performed_by: Mapped[str | None] = mapped_column(IdStr, default=None)
    outcome: Mapped[str] = mapped_column(String(16), default="done")
    cost: Mapped[Decimal | None] = mapped_column(Money, default=None)
    currency: Mapped[str | None] = mapped_column(String(3), default=None)
    vendor: Mapped[str | None] = mapped_column(String(200), default=None)
    duration_min: Mapped[int | None] = mapped_column(default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    readings: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
