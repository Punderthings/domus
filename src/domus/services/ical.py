"""The iCalendar (RFC 5545) feed of upcoming maintenance (data-storage-backup.md 4.4).

Each active task with a due date becomes one all-day VEVENT on that date,
with a display alarm ``lead_days`` before it. Overdue tasks stay on their
due date so they remain visible. The output depends only on the arguments,
so the same data always gives the same bytes.
"""

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta

from icalendar import Alarm, Calendar, Component, Event

from domus.models import MaintenanceTask, Property

__all__ = ["PRODID", "build_calendar"]

PRODID = "-//Domus//Domus maintenance//EN"


def _add(component: Component, name: str, value: object) -> None:
    # icalendar leaves the value parameter of add() untyped.
    component.add(name, value)  # pyright: ignore[reportUnknownMemberType]


def _event(task: MaintenanceTask, asset_name: str | None, stamp: datetime) -> Event:
    if task.next_due is None:  # pragma: no cover - filtered by the caller
        raise ValueError("task has no next_due")
    event = Event()
    _add(event, "uid", f"{task.id}@domus")
    _add(event, "dtstamp", stamp)
    _add(event, "dtstart", task.next_due)
    _add(event, "dtend", task.next_due + timedelta(days=1))
    _add(event, "summary", task.title)
    lines = [text for text in (task.procedure, asset_name and f"Asset: {asset_name}") if text]
    if lines:
        _add(event, "description", "\n\n".join(lines))
    _add(event, "transp", "TRANSPARENT")

    alarm = Alarm()
    _add(alarm, "action", "DISPLAY")
    _add(alarm, "description", task.title)
    _add(alarm, "trigger", -timedelta(days=max(task.lead_days, 0)))
    event.add_component(alarm)
    return event


def build_calendar(
    prop: Property,
    tasks: Iterable[MaintenanceTask],
    *,
    now: datetime,
    asset_names: Mapping[str, str] | None = None,
) -> bytes:
    """Render the maintenance feed for one property as iCalendar bytes.

    ``now`` (timezone-aware) becomes every DTSTAMP. ``asset_names`` maps an
    asset id to the name added to the event description. Inactive, deleted,
    and finished (no ``next_due``) tasks are left out.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    stamp = now.astimezone(UTC).replace(microsecond=0)
    names = asset_names or {}

    cal = Calendar()
    _add(cal, "prodid", PRODID)
    _add(cal, "version", "2.0")
    _add(cal, "calscale", "GREGORIAN")
    _add(cal, "method", "PUBLISH")
    _add(cal, "x-wr-calname", f"Domus: {prop.name}")
    _add(cal, "x-wr-timezone", prop.timezone)

    shown = [t for t in tasks if t.active and t.deleted_at is None and t.next_due is not None]
    shown.sort(key=lambda t: (t.next_due, t.id))
    for task in shown:
        asset_name = names.get(task.asset_id) if task.asset_id else None
        cal.add_component(_event(task, asset_name, stamp))
    return cal.to_ical()
