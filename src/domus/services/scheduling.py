"""Maintenance scheduling: next-due dates, completions, and the due list.

Design: master plan section 4.1 and data-storage-backup.md section 2.3.

Two schedule kinds cover real life:

``after_completion``
    "6 months after it was last done". The next due date is the last
    completion plus ``interval_value`` ``interval_unit`` (day, week, month,
    year). Month arithmetic clamps to the month end, so Jan 31 + 1 month is
    Feb 28 (or 29). A task that was never done is due on ``anchor_date`` if
    set, otherwise today.

``fixed_calendar``
    "Every November 1". An RFC 5545 RRULE whose series starts on
    ``anchor_date``. The next due date is the first occurrence strictly after
    the last completion, or the first occurrence on or after ``anchor_date``
    if it was never done. As in python-dateutil (and unlike a strict reading
    of RFC 5545), the anchor date only counts as an occurrence when it matches
    the rule.

All recurrence is in calendar dates, never timestamps, so daylight saving
changes cannot move a due date.
"""

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from dateutil.rrule import rrule, rrulestr
from sqlalchemy import select
from sqlalchemy.orm import Session

from domus.models import MaintenanceEvent, MaintenanceTask, Property
from domus.models.enums import EVENT_OUTCOMES, INTERVAL_UNITS, SCHEDULE_KINDS

__all__ = [
    "RRULE_MAX_LENGTH",
    "Schedule",
    "ScheduleLike",
    "complete_task",
    "compute_next_due",
    "due_tasks",
    "validate_schedule",
]

RRULE_MAX_LENGTH = 500  # matches maintenance_task.rrule

# RRULE parts that make sense for whole-day schedules. Everything else is
# rejected: DTSTART (the series starts on anchor_date), sub-daily parts
# (BYHOUR, BYMINUTE, BYSECOND), and dateutil's non-standard BYEASTER.
_ALLOWED_PARTS = frozenset(
    {
        "FREQ",
        "INTERVAL",
        "COUNT",
        "UNTIL",
        "BYMONTH",
        "BYMONTHDAY",
        "BYYEARDAY",
        "BYWEEKNO",
        "BYDAY",
        "BYSETPOS",
        "WKST",
    }
)
_DATE_FREQS = ("YEARLY", "MONTHLY", "WEEKLY", "DAILY")
_SUB_DAILY_FREQS = ("HOURLY", "MINUTELY", "SECONDLY")
# RFC 5545 section 3.3.10: where BYWEEKNO, BYYEARDAY and BYMONTHDAY may appear.
_PART_FREQS = {
    "BYWEEKNO": ("YEARLY",),
    "BYYEARDAY": ("YEARLY",),
    "BYMONTHDAY": ("YEARLY", "MONTHLY", "DAILY"),
}
_PART_NAME = re.compile(r"[A-Z]+")
_POSITIVE_INT = re.compile(r"[1-9][0-9]{0,8}")
_UNTIL = re.compile(r"([0-9]{8})(T[0-9]{6}Z?)?")

# The Gregorian calendar repeats exactly every 400 years, which is a whole
# number of each unit below (146097 days, 20871 weeks, 4800 months).
_CYCLE_YEARS = 400
_UNITS_PER_CYCLE = {"YEARLY": 400, "MONTHLY": 4800, "WEEKLY": 20871, "DAILY": 146097}
_LAST_YEAR = 9998  # stay clear of datetime.MAXYEAR


@dataclass(frozen=True)
class Schedule:
    """The schedule fields of a task, for example from an API payload."""

    schedule_kind: str
    interval_value: int | None = None
    interval_unit: str | None = None
    rrule: str | None = None
    anchor_date: date | None = None

    @classmethod
    def of(cls, task: Schedule | MaintenanceTask) -> Schedule:
        if isinstance(task, Schedule):
            return task
        return cls(
            schedule_kind=task.schedule_kind,
            interval_value=task.interval_value,
            interval_unit=task.interval_unit,
            rrule=task.rrule,
            anchor_date=task.anchor_date,
        )


type ScheduleLike = Schedule | MaintenanceTask


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time())


def _parse_rrule_parts(text: str) -> dict[str, str]:
    """Split an RRULE value into checked ``NAME=VALUE`` parts."""
    if len(text) > RRULE_MAX_LENGTH:
        raise ValueError(f"rrule is longer than {RRULE_MAX_LENGTH} characters")
    if "\n" in text or "\r" in text:
        raise ValueError("rrule must be a single RRULE line")
    body = text.strip().upper()
    body = body.removeprefix("RRULE:")
    if not body:
        raise ValueError("rrule is empty")
    parts: dict[str, str] = {}
    for item in body.split(";"):
        name, sep, value = item.partition("=")
        name, value = name.strip(), value.strip()
        if not sep or not _PART_NAME.fullmatch(name) or not value:
            raise ValueError(f"rrule part {item!r} is not NAME=VALUE")
        if name in parts:
            raise ValueError(f"rrule repeats {name}")
        parts[name] = value
    return parts


def _check_rrule_parts(parts: dict[str, str]) -> dict[str, str]:
    """Reject parts that make no sense for dates; return them normalized."""
    if "DTSTART" in parts:
        raise ValueError("rrule must not contain DTSTART; set anchor_date instead")
    freq = parts.get("FREQ")
    if freq is None:
        raise ValueError("rrule needs FREQ")
    if freq in _SUB_DAILY_FREQS:
        raise ValueError(f"rrule FREQ={freq} is finer than a day; use DAILY or longer")
    if freq not in _DATE_FREQS:
        raise ValueError(f"rrule FREQ={freq} is not one of {', '.join(_DATE_FREQS)}")
    for name in parts:
        if name not in _ALLOWED_PARTS:
            raise ValueError(f"rrule part {name} is not supported for date schedules")
        allowed = _PART_FREQS.get(name)
        if allowed is not None and freq not in allowed:
            raise ValueError(f"rrule {name} is not valid with FREQ={freq} (RFC 5545)")
    for name in ("INTERVAL", "COUNT"):
        if name in parts and not _POSITIVE_INT.fullmatch(parts[name]):
            raise ValueError(f"rrule {name} must be a positive whole number")
    if "COUNT" in parts and "UNTIL" in parts:
        raise ValueError("rrule must not have both COUNT and UNTIL (RFC 5545)")
    if "UNTIL" in parts:
        match = _UNTIL.fullmatch(parts["UNTIL"])
        if match is None:
            raise ValueError("rrule UNTIL must be a date (YYYYMMDD)")
        # Schedules are whole days: keep only the date of a DATE-TIME UNTIL.
        parts = {**parts, "UNTIL": match.group(1)}
    return parts


def _cycle_years(freq: str, interval: int) -> int:
    """Years after which the rule's pattern repeats exactly."""
    units = _UNITS_PER_CYCLE[freq]
    return _CYCLE_YEARS * (interval // math.gcd(interval, units))


def _has_any_occurrence(rule: rrule, anchor: date, freq: str, interval: int) -> bool:
    """Whether the rule, ignoring COUNT and UNTIL, ever produces a date.

    dateutil searches up to the year 9999 for a rule that can never match
    (say February 30), which takes seconds for a daily rule. The calendar
    repeats every 400 years, so moving the start forward by whole cycles keeps
    the same pattern and bounds that search to about one cycle.
    """
    span = _cycle_years(freq, interval)
    cycles = (_LAST_YEAR - span - anchor.year) // span
    start = anchor.replace(year=anchor.year + cycles * span) if cycles > 0 else anchor
    probe = rule.replace(dtstart=_midnight(start), count=None, until=None)
    return probe.after(_midnight(start), inc=True) is not None


def _build_rrule(text: str, anchor: date) -> rrule:
    parts = _check_rrule_parts(_parse_rrule_parts(text))
    normalized = ";".join(f"{name}={value}" for name, value in parts.items())
    try:
        rule = rrulestr(normalized, dtstart=_midnight(anchor))
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(f"rrule is not valid: {exc}") from exc
    if not isinstance(rule, rrule):  # pragma: no cover - a single line always is
        raise ValueError("rrule must be a single RRULE line")
    interval = int(parts.get("INTERVAL", "1"))
    try:
        possible = _has_any_occurrence(rule, anchor, parts["FREQ"], interval)
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"rrule is not valid: {exc}") from exc
    if not possible:
        raise ValueError("rrule never matches a date (for example February 30)")
    return rule


def validate_schedule(schedule: ScheduleLike) -> None:
    """Raise ``ValueError`` with a readable message if the schedule is unusable.

    Fields that the schedule kind does not use are ignored.
    """
    schedule = Schedule.of(schedule)
    kind = schedule.schedule_kind
    if kind not in SCHEDULE_KINDS:
        raise ValueError(f"schedule_kind must be one of {', '.join(SCHEDULE_KINDS)}")
    if kind == "after_completion":
        value = schedule.interval_value
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError("after_completion needs interval_value greater than 0")
        if schedule.interval_unit not in INTERVAL_UNITS:
            raise ValueError(f"interval_unit must be one of {', '.join(INTERVAL_UNITS)}")
        return
    if not schedule.rrule:
        raise ValueError("fixed_calendar needs an rrule")
    if schedule.anchor_date is None:
        raise ValueError("fixed_calendar needs an anchor_date (the first day of the series)")
    _build_rrule(schedule.rrule, schedule.anchor_date)


def _add_interval(day: date, value: int, unit: str) -> date:
    step = {
        "day": relativedelta(days=value),
        "week": relativedelta(weeks=value),
        "month": relativedelta(months=value),
        "year": relativedelta(years=value),
    }[unit]
    try:
        return day + step
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"next due date is out of range: {exc}") from exc


def compute_next_due(schedule: ScheduleLike, last_done: date | None, today: date) -> date | None:
    """The next due date, or ``None`` when a COUNT or UNTIL rule is used up.

    ``last_done`` is the date the task was last done (or ``None`` if never).
    ``today`` is only used for an ``after_completion`` task that was never
    done and has no ``anchor_date``. Raises ``ValueError`` for an invalid
    schedule.
    """
    schedule = Schedule.of(schedule)
    validate_schedule(schedule)
    if schedule.schedule_kind == "after_completion":
        if last_done is None:
            return schedule.anchor_date or today
        value, unit = schedule.interval_value, schedule.interval_unit
        if value is None or unit is None:  # pragma: no cover - validated above
            raise ValueError("after_completion needs interval_value and interval_unit")
        return _add_interval(last_done, value, unit)

    text, anchor = schedule.rrule, schedule.anchor_date
    if text is None or anchor is None:  # pragma: no cover - validated above
        raise ValueError("fixed_calendar needs an rrule and an anchor_date")
    rule = _build_rrule(text, anchor)
    if last_done is None:
        found = rule.after(_midnight(anchor), inc=True)
    else:
        found = rule.after(_midnight(last_done), inc=False)
    return None if found is None else found.date()


def _last_done_on(session: Session, task_id: str) -> date | None:
    """The latest done or partial completion already recorded for a task."""
    stmt = (
        select(MaintenanceEvent.performed_on)
        .where(
            MaintenanceEvent.task_id == task_id,
            MaintenanceEvent.outcome.in_(("done", "partial")),
            MaintenanceEvent.deleted_at.is_(None),
        )
        .order_by(MaintenanceEvent.performed_on.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()


def complete_task(
    session: Session,
    task: MaintenanceTask,
    *,
    performed_on: date,
    outcome: str = "done",
    cost: Decimal | None = None,
    currency: str | None = None,
    notes: str | None = None,
    performed_by: str | None = None,
) -> MaintenanceEvent:
    """Record work on a task and move its schedule on. The caller commits.

    - ``done`` and ``partial`` count as done: ``next_due`` is recomputed from
      the latest completion (``performed_on``, or a later one already on
      record, so back-filling an old event never moves the schedule back).
    - ``skipped`` advances the schedule from the current ``next_due`` as if it
      had been done that day, without counting as done.
    - ``failed`` records the event and leaves ``next_due`` unchanged.

    If ``cost`` is given without ``currency``, the property's default
    currency is used.
    """
    if outcome not in EVENT_OUTCOMES:
        raise ValueError(f"outcome must be one of {', '.join(EVENT_OUTCOMES)}")
    if cost is not None and cost < 0:
        raise ValueError("cost must not be negative")
    if currency is not None:
        currency = currency.strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise ValueError("currency must be a three-letter ISO 4217 code")
    elif cost is not None:
        prop = session.get(Property, task.property_id)
        if prop is None:
            raise ValueError(f"task {task.id} refers to a missing property")
        currency = prop.default_currency

    if outcome in ("done", "partial"):
        previous = _last_done_on(session, task.id)
        last_done = performed_on if previous is None else max(previous, performed_on)
        task.next_due = compute_next_due(task, last_done, performed_on)
    elif outcome == "skipped":
        current = task.next_due or compute_next_due(task, None, performed_on)
        if current is not None:
            task.next_due = compute_next_due(task, current, performed_on)

    event = MaintenanceEvent(
        task_id=task.id,
        asset_id=task.asset_id,
        performed_on=performed_on,
        performed_by=performed_by,
        outcome=outcome,
        cost=cost,
        currency=currency,
        notes=notes,
    )
    session.add(event)
    session.flush()
    return event


def due_tasks(
    session: Session,
    property_id: str,
    *,
    before: date | None = None,
    include_inactive: bool = False,
) -> Sequence[MaintenanceTask]:
    """Tasks with a due date, soonest first; ``before`` is exclusive.

    Overdue tasks are included. Deleted tasks and tasks with no next due date
    (finished series) never are.
    """
    stmt = select(MaintenanceTask).where(
        MaintenanceTask.property_id == property_id,
        MaintenanceTask.next_due.is_not(None),
        MaintenanceTask.deleted_at.is_(None),
    )
    if before is not None:
        stmt = stmt.where(MaintenanceTask.next_due < before)
    if not include_inactive:
        stmt = stmt.where(MaintenanceTask.active.is_(True))
    stmt = stmt.order_by(MaintenanceTask.next_due, MaintenanceTask.title, MaintenanceTask.id)
    return session.scalars(stmt).all()
