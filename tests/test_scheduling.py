"""Tests for maintenance scheduling (master plan 4.1, data-storage-backup.md 2.3)."""

import time
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from itertools import pairwise

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from domus.models import Asset, MaintenanceEvent, MaintenanceTask, Property
from domus.services.scheduling import (
    Schedule,
    complete_task,
    compute_next_due,
    due_tasks,
    validate_schedule,
)

TODAY = date(2026, 11, 6)
NOV_1 = "FREQ=YEARLY;BYMONTH=11;BYMONTHDAY=1"  # sample-home smoke detector, hose valve
APR_1 = "FREQ=YEARLY;BYMONTH=4;BYMONTHDAY=1"  # sample-home sump pump battery


def every(value: int, unit: str, anchor: date | None = None) -> Schedule:
    return Schedule(
        "after_completion", interval_value=value, interval_unit=unit, anchor_date=anchor
    )


def calendar(rule: str, anchor: date | None) -> Schedule:
    return Schedule("fixed_calendar", rrule=rule, anchor_date=anchor)


# --- after_completion ---------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "unit", "last_done", "expected"),
    [
        (10, "day", date(2026, 11, 6), date(2026, 11, 16)),
        (1, "day", date(2026, 12, 31), date(2027, 1, 1)),
        (2, "week", date(2026, 11, 6), date(2026, 11, 20)),
        (6, "month", date(2026, 9, 1), date(2027, 3, 1)),  # sample fridge filter
        (3, "month", date(2026, 10, 15), date(2027, 1, 15)),  # sample furnace filter
        (1, "month", date(2027, 1, 31), date(2027, 2, 28)),  # month end clamps
        (1, "month", date(2028, 1, 31), date(2028, 2, 29)),  # leap year
        (1, "month", date(2026, 3, 31), date(2026, 4, 30)),
        (1, "year", date(2026, 11, 6), date(2027, 11, 6)),
        (1, "year", date(2028, 2, 29), date(2029, 2, 28)),  # leap day + 1 year
        (4, "year", date(2028, 2, 29), date(2032, 2, 29)),
    ],
)
def test_after_completion(value: int, unit: str, last_done: date, expected: date) -> None:
    assert compute_next_due(every(value, unit), last_done, TODAY) == expected


def test_after_completion_never_done_uses_anchor_then_today() -> None:
    assert compute_next_due(every(3, "month", date(2027, 1, 1)), None, TODAY) == date(2027, 1, 1)
    assert compute_next_due(every(3, "month"), None, TODAY) == TODAY


def test_after_completion_ignores_anchor_once_done() -> None:
    schedule = every(1, "week", anchor=date(2030, 1, 1))
    assert compute_next_due(schedule, date(2026, 11, 6), TODAY) == date(2026, 11, 13)


def test_after_completion_out_of_range_is_a_value_error() -> None:
    with pytest.raises(ValueError, match="out of range"):
        compute_next_due(every(9000, "year"), date(2026, 1, 1), TODAY)


# --- fixed_calendar -----------------------------------------------------------


@pytest.mark.parametrize(
    ("rule", "anchor", "last_done", "expected"),
    [
        # never done: the first occurrence on or after the anchor (may be overdue)
        (NOV_1, date(2026, 11, 1), None, date(2026, 11, 1)),
        (APR_1, date(2026, 4, 1), None, date(2026, 4, 1)),
        # an anchor that does not match the rule is only the start of the series
        (NOV_1, date(2026, 3, 15), None, date(2026, 11, 1)),
        (NOV_1, date(2026, 11, 2), None, date(2027, 11, 1)),
        # done before, on, and after an occurrence
        (NOV_1, date(2026, 11, 1), date(2026, 10, 28), date(2026, 11, 1)),
        (NOV_1, date(2026, 11, 1), date(2026, 11, 1), date(2027, 11, 1)),
        (NOV_1, date(2026, 11, 1), date(2026, 11, 6), date(2027, 11, 1)),
        (APR_1, date(2026, 4, 1), date(2026, 3, 31), date(2026, 4, 1)),
        (APR_1, date(2026, 4, 1), date(2026, 4, 1), date(2027, 4, 1)),
        (APR_1, date(2026, 4, 1), date(2026, 5, 2), date(2027, 4, 1)),
        # done long ago, before the series even started
        (APR_1, date(2026, 4, 1), date(2020, 1, 1), date(2026, 4, 1)),
        # other shapes
        ("FREQ=MONTHLY;BYDAY=1SA", date(2026, 1, 1), date(2026, 11, 7), date(2026, 12, 5)),
        (
            "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO",
            date(2026, 11, 2),
            date(2026, 11, 2),
            date(2026, 11, 16),
        ),
        ("FREQ=MONTHLY;BYMONTHDAY=-1", date(2026, 1, 1), date(2027, 1, 31), date(2027, 2, 28)),
        ("FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=29", date(2026, 1, 1), None, date(2028, 2, 29)),
        ("RRULE:freq=yearly;bymonth=11;bymonthday=1", date(2026, 1, 1), None, date(2026, 11, 1)),
    ],
)
def test_fixed_calendar(rule: str, anchor: date, last_done: date | None, expected: date) -> None:
    assert compute_next_due(calendar(rule, anchor), last_done, TODAY) == expected


def test_fixed_calendar_spanning_dst_keeps_calendar_dates() -> None:
    # US DST ends 2026-11-01 and starts 2027-03-14; EU DST starts 2027-03-28.
    # Schedules are dates, not instants, so the weekly Sunday stays on Sunday.
    schedule = calendar("FREQ=WEEKLY;BYDAY=SU", date(2026, 10, 25))
    got: list[date] = []
    last: date | None = None
    for _ in range(25):
        nxt = compute_next_due(schedule, last, TODAY)
        assert nxt is not None
        got.append(nxt)
        last = nxt
    assert got[:3] == [date(2026, 10, 25), date(2026, 11, 1), date(2026, 11, 8)]
    assert date(2027, 3, 14) in got
    assert date(2027, 3, 28) in got
    assert all(day.weekday() == 6 for day in got)
    assert all(b - a == timedelta(days=7) for a, b in pairwise(got))


def test_fixed_calendar_count_exhausted_returns_none() -> None:
    schedule = calendar("FREQ=YEARLY;BYMONTH=4;BYMONTHDAY=1;COUNT=2", date(2026, 4, 1))
    assert compute_next_due(schedule, None, TODAY) == date(2026, 4, 1)
    assert compute_next_due(schedule, date(2026, 4, 1), TODAY) == date(2027, 4, 1)
    assert compute_next_due(schedule, date(2027, 4, 1), TODAY) is None


@pytest.mark.parametrize("until", ["20271231", "20271231T235959Z", "20271231T120000"])
def test_fixed_calendar_until_exhausted_returns_none(until: str) -> None:
    schedule = calendar(f"{NOV_1};UNTIL={until}", date(2026, 11, 1))
    assert compute_next_due(schedule, date(2026, 11, 1), TODAY) == date(2027, 11, 1)
    assert compute_next_due(schedule, date(2027, 11, 1), TODAY) is None


def test_fixed_calendar_impossible_rule_is_rejected_quickly() -> None:
    started = time.monotonic()
    with pytest.raises(ValueError, match="never matches"):
        compute_next_due(calendar("FREQ=DAILY;BYMONTH=2;BYMONTHDAY=30", TODAY), None, TODAY)
    # Without the 400-year bound dateutil searches to the year 9999 (seconds).
    assert time.monotonic() - started < 5  # generous for slow CI runners


# --- validation ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("schedule", "message"),
    [
        (Schedule("weekly"), "schedule_kind must be one of"),
        (every(0, "month"), "interval_value greater than 0"),
        (every(-1, "month"), "interval_value greater than 0"),
        (Schedule("after_completion", interval_unit="month"), "interval_value greater than 0"),
        (every(1, "fortnight"), "interval_unit must be one of"),
        (Schedule("after_completion", interval_value=1), "interval_unit must be one of"),
        (calendar("", date(2026, 1, 1)), "needs an rrule"),
        (calendar(NOV_1, None), "needs an anchor_date"),
        (calendar("DTSTART:20260101\nRRULE:FREQ=YEARLY", TODAY), "single RRULE line"),
        (calendar("DTSTART=20260101;FREQ=YEARLY", TODAY), "must not contain DTSTART"),
        (calendar("FREQ=HOURLY", TODAY), "finer than a day"),
        (calendar("FREQ=MINUTELY;INTERVAL=1", TODAY), "finer than a day"),
        (calendar("FREQ=SECONDLY", TODAY), "finer than a day"),
        (calendar("FREQ=FORTNIGHTLY", TODAY), "is not one of"),
        (calendar("INTERVAL=2", TODAY), "needs FREQ"),
        (calendar("FREQ=DAILY;BYHOUR=9", TODAY), "BYHOUR is not supported"),
        (calendar("FREQ=YEARLY;BYEASTER=0", TODAY), "BYEASTER is not supported"),
        (calendar("FREQ=WEEKLY;BYMONTHDAY=1", TODAY), "not valid with FREQ=WEEKLY"),
        (calendar("FREQ=MONTHLY;BYWEEKNO=1", TODAY), "not valid with FREQ=MONTHLY"),
        (calendar("FREQ=DAILY;BYYEARDAY=1", TODAY), "not valid with FREQ=DAILY"),
        (calendar("FREQ=YEARLY;INTERVAL=0", TODAY), "INTERVAL must be a positive"),
        (calendar("FREQ=YEARLY;COUNT=-1", TODAY), "COUNT must be a positive"),
        (calendar("FREQ=YEARLY;COUNT=2;UNTIL=20300101", TODAY), "both COUNT and UNTIL"),
        (calendar("FREQ=YEARLY;UNTIL=soon", TODAY), "UNTIL must be a date"),
        (calendar("FREQ=YEARLY;FREQ=DAILY", TODAY), "repeats FREQ"),
        (calendar("FREQ=YEARLY;;", TODAY), "is not NAME=VALUE"),
        (calendar("FREQ=YEARLY;BYMONTH=13", TODAY), "never matches"),
        (calendar("FREQ=YEARLY;BYDAY=XX", TODAY), "rrule is not valid"),
        (calendar("FREQ=YEARLY;BYMONTH=4;BYMONTHDAY=31", TODAY), "never matches"),
        (calendar("FREQ=MONTHLY;BYDAY=MO;BYSETPOS=6", TODAY), "never matches"),
        (calendar("FREQ=YEARLY;" + "BYMONTH=1," * 60, TODAY), "longer than 500"),
    ],
)
def test_validate_schedule_errors(schedule: Schedule, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        validate_schedule(schedule)
    with pytest.raises(ValueError, match=message):
        compute_next_due(schedule, None, TODAY)


@pytest.mark.parametrize(
    "schedule",
    [
        every(6, "month"),
        calendar(NOV_1, date(2026, 11, 1)),
        # unused fields are ignored
        Schedule("after_completion", interval_value=1, interval_unit="day", rrule="junk"),
        Schedule("fixed_calendar", interval_value=-5, rrule=APR_1, anchor_date=TODAY),
    ],
)
def test_validate_schedule_ok(schedule: Schedule) -> None:
    validate_schedule(schedule)


# --- complete_task and due_tasks (database) -----------------------------------


@pytest.fixture
def home(session: Session) -> Property:
    prop = Property(name="Sample Home", timezone="America/New_York", default_currency="CAD")
    session.add(prop)
    session.flush()
    return prop


@pytest.fixture
def fridge(session: Session, home: Property) -> Asset:
    asset = Asset(property_id=home.id, name="Refrigerator", category="appliance")
    session.add(asset)
    session.flush()
    return asset


def make_task(
    session: Session, home: Property, asset: Asset | None = None, **fields: object
) -> MaintenanceTask:
    fields.setdefault("title", "Task")
    task = MaintenanceTask(property_id=home.id, asset_id=asset.id if asset else None, **fields)
    session.add(task)
    session.flush()
    return task


def water_filter(session: Session, home: Property, fridge: Asset) -> MaintenanceTask:
    return make_task(
        session,
        home,
        fridge,
        title="Replace refrigerator water filter",
        schedule_kind="after_completion",
        interval_value=6,
        interval_unit="month",
        next_due=date(2027, 3, 1),
    )


def smoke_test(session: Session, home: Property) -> MaintenanceTask:
    return make_task(
        session,
        home,
        title="Test smoke detector",
        schedule_kind="fixed_calendar",
        rrule=NOV_1,
        anchor_date=date(2026, 11, 1),
        next_due=date(2026, 11, 1),
    )


@pytest.mark.parametrize("outcome", ["done", "partial"])
def test_complete_done_or_partial_recomputes(
    session: Session, home: Property, fridge: Asset, outcome: str
) -> None:
    task = water_filter(session, home, fridge)
    event = complete_task(
        session,
        task,
        performed_on=date(2026, 11, 6),
        outcome=outcome,
        cost=Decimal("49.99"),
        notes="Replaced with FR-WF1.",
        performed_by="user-1",
    )
    assert task.next_due == date(2027, 5, 6)
    assert event.task_id == task.id
    assert event.asset_id == fridge.id
    assert event.outcome == outcome
    assert event.performed_on == date(2026, 11, 6)
    assert event.cost == Decimal("49.99")
    assert event.currency == "CAD"  # the property's default
    assert event.notes == "Replaced with FR-WF1."
    assert event.performed_by == "user-1"
    assert session.scalars(select(MaintenanceEvent)).all() == [event]


def test_complete_fixed_calendar_overdue(session: Session, home: Property) -> None:
    task = smoke_test(session, home)
    complete_task(session, task, performed_on=date(2026, 11, 6))
    assert task.next_due == date(2027, 11, 1)


@pytest.mark.parametrize(
    ("performed_on", "expected"),
    [
        (date(2026, 10, 25), date(2027, 11, 1)),  # inside the 7-day reminder window
        (date(2026, 10, 24), date(2026, 11, 1)),  # earlier than that: still due this year
    ],
)
def test_complete_fixed_calendar_early_within_lead_days(
    session: Session, home: Property, performed_on: date, expected: date
) -> None:
    task = smoke_test(session, home)  # lead_days defaults to 7
    complete_task(session, task, performed_on=performed_on)
    assert task.next_due == expected


def test_complete_backfilled_event_does_not_move_schedule_back(
    session: Session, home: Property, fridge: Asset
) -> None:
    task = water_filter(session, home, fridge)
    complete_task(session, task, performed_on=date(2026, 11, 6))
    complete_task(session, task, performed_on=date(2026, 5, 1))  # entered late
    assert task.next_due == date(2027, 5, 6)


def test_complete_skipped_advances_from_next_due(
    session: Session, home: Property, fridge: Asset
) -> None:
    task = water_filter(session, home, fridge)
    event = complete_task(session, task, performed_on=date(2026, 11, 6), outcome="skipped")
    assert task.next_due == date(2027, 9, 1)  # 2027-03-01 + 6 months
    assert event.outcome == "skipped"
    # a skip is not a completion: a later done counts from its own date
    complete_task(session, task, performed_on=date(2026, 12, 1))
    assert task.next_due == date(2027, 6, 1)


def test_complete_skipped_fixed_calendar(session: Session, home: Property) -> None:
    task = smoke_test(session, home)
    complete_task(session, task, performed_on=date(2026, 11, 6), outcome="skipped")
    assert task.next_due == date(2027, 11, 1)


def test_complete_skipped_without_next_due_skips_the_first(
    session: Session, home: Property
) -> None:
    task = make_task(
        session, home, schedule_kind="after_completion", interval_value=1, interval_unit="week"
    )
    complete_task(session, task, performed_on=date(2026, 11, 6), outcome="skipped")
    assert task.next_due == date(2026, 11, 13)


def test_complete_failed_leaves_next_due(session: Session, home: Property, fridge: Asset) -> None:
    task = water_filter(session, home, fridge)
    event = complete_task(session, task, performed_on=date(2026, 11, 6), outcome="failed")
    assert task.next_due == date(2027, 3, 1)
    assert event.outcome == "failed"


def test_complete_exhausted_series_clears_next_due(session: Session, home: Property) -> None:
    task = make_task(
        session,
        home,
        schedule_kind="fixed_calendar",
        rrule=NOV_1 + ";COUNT=1",
        anchor_date=date(2026, 11, 1),
        next_due=date(2026, 11, 1),
    )
    complete_task(session, task, performed_on=date(2026, 11, 2))
    assert task.next_due is None
    assert due_tasks(session, home.id) == []


def test_complete_explicit_currency_and_no_cost(
    session: Session, home: Property, fridge: Asset
) -> None:
    task = water_filter(session, home, fridge)
    event = complete_task(
        session, task, performed_on=TODAY, cost=Decimal("12.50"), currency=" usd "
    )
    assert event.currency == "USD"
    event = complete_task(session, task, performed_on=TODAY)
    assert event.cost is None
    assert event.currency is None


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"outcome": "maybe"}, "outcome must be one of"),
        ({"cost": Decimal("-1")}, "must not be negative"),
        ({"cost": Decimal(1), "currency": "dollars"}, "three-letter"),
    ],
)
def test_complete_rejects_bad_input(
    session: Session, home: Property, fridge: Asset, kwargs: dict[str, object], message: str
) -> None:
    task = water_filter(session, home, fridge)
    with pytest.raises(ValueError, match=message):
        complete_task(session, task, performed_on=TODAY, **kwargs)  # pyright: ignore[reportArgumentType]
    assert task.next_due == date(2027, 3, 1)
    assert session.scalars(select(MaintenanceEvent)).all() == []


def test_complete_does_not_commit(session: Session, home: Property, fridge: Asset) -> None:
    task = water_filter(session, home, fridge)
    session.commit()
    complete_task(session, task, performed_on=TODAY)
    session.rollback()
    assert task.next_due == date(2027, 3, 1)
    assert session.scalars(select(MaintenanceEvent)).all() == []


def test_due_tasks_order_and_filters(session: Session, home: Property) -> None:
    def add(title: str, due: date | None, **fields: object) -> MaintenanceTask:
        return make_task(
            session,
            home,
            None,
            title=title,
            interval_value=1,
            interval_unit="month",
            next_due=due,
            **fields,
        )

    later = add("B later", date(2027, 4, 1))
    overdue = add("Overdue", date(2026, 11, 1))
    same_day = add("A same day", date(2027, 4, 1))
    inactive = add("Inactive", date(2026, 12, 1), active=False)
    add("Finished", None)
    add("Deleted", date(2026, 12, 2), deleted_at=datetime(2026, 11, 5, tzinfo=UTC))
    other = Property(name="Elsewhere")
    session.add(other)
    session.flush()
    make_task(session, other, None, title="Other home", next_due=date(2026, 11, 2))

    assert due_tasks(session, home.id) == [overdue, same_day, later]
    assert due_tasks(session, home.id, include_inactive=True) == [
        overdue,
        inactive,
        same_day,
        later,
    ]
    assert due_tasks(session, home.id, before=date(2027, 4, 1)) == [overdue]
    assert due_tasks(session, home.id, before=date(2027, 4, 2)) == [overdue, same_day, later]
