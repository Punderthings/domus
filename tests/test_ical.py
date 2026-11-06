"""Tests for the iCalendar maintenance feed (data-storage-backup.md 4.4)."""

from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from icalendar import Calendar, Component

from domus.models import MaintenanceTask, Property
from domus.services.ical import PRODID, build_calendar

NOW = datetime(2026, 11, 6, 12, 30, 15, 123456, tzinfo=UTC)
HOME = Property(id="prop-1", name="Sample Home", timezone="America/New_York")


def task(task_id: str, title: str, due: date | None, **fields: object) -> MaintenanceTask:
    return MaintenanceTask(
        id=task_id, property_id="prop-1", title=title, next_due=due, active=True, **fields
    )


SMOKE = task(
    "01a1a901-5800-7030-8000-000000000030",
    "Test smoke detector and replace 9V battery",
    date(2026, 11, 1),  # overdue on NOW
    asset_id="smoke-1",
    lead_days=7,
)
HOSE = task(
    "01a1a901-5800-7031-8000-000000000031",
    "Close outdoor hose valve, drain the hose",
    date(2026, 11, 1),
    procedure="1. Close this valve.\n2. Open the hose bib; drain it.",
    lead_days=0,
)
FILTER = task(
    "01a1a901-5800-702d-8000-00000000002d",
    "Replace refrigerator water filter",
    date(2027, 3, 1),
    asset_id="fridge-1",
    procedure="Turn the old filter a quarter turn left.",
    lead_days=14,
)
INACTIVE = task("t-inactive", "Inactive", date(2026, 12, 1), lead_days=7)
INACTIVE.active = False
FINISHED = task("t-finished", "Finished", None, lead_days=7)
DELETED = task("t-deleted", "Deleted", date(2026, 12, 1), lead_days=7)
DELETED.deleted_at = datetime(2026, 11, 5, tzinfo=UTC)
ALL = [FILTER, INACTIVE, HOSE, FINISHED, SMOKE, DELETED]
NAMES = {"smoke-1": "Hallway smoke detector", "fridge-1": "Kitchen refrigerator"}


def parse(data: bytes) -> Calendar:
    return Calendar.from_ical(data)


def walk(component: Component, name: str) -> list[Component]:
    return component.walk(name)  # pyright: ignore[reportUnknownMemberType]


def events(cal: Calendar) -> list[Component]:
    return walk(cal, "VEVENT")


def test_calendar_headers() -> None:
    cal = parse(build_calendar(HOME, [], now=NOW))
    assert str(cal["PRODID"]) == PRODID
    assert str(cal["VERSION"]) == "2.0"
    assert str(cal["X-WR-CALNAME"]) == "Domus: Sample Home"
    assert str(cal["X-WR-TIMEZONE"]) == "America/New_York"
    assert events(cal) == []


def test_one_all_day_event_per_due_active_task() -> None:
    data = build_calendar(HOME, ALL, now=NOW, asset_names=NAMES)
    found = events(parse(data))
    # sorted by due date, then id; inactive, finished and deleted left out
    assert [str(e["UID"]) for e in found] == [
        f"{SMOKE.id}@domus",
        f"{HOSE.id}@domus",
        f"{FILTER.id}@domus",
    ]

    by_uid = {str(e["UID"]): e for e in found}
    smoke = by_uid[f"{SMOKE.id}@domus"]
    assert smoke.decoded("DTSTART") == date(2026, 11, 1)  # overdue stays on its date
    assert b"DTSTART;VALUE=DATE:20261101" in data
    assert smoke.decoded("DTEND") == date(2026, 11, 2)
    assert str(smoke["SUMMARY"]) == SMOKE.title
    assert str(smoke["DESCRIPTION"]) == "Asset: Hallway smoke detector"
    assert smoke.decoded("DTSTAMP") == datetime(2026, 11, 6, 12, 30, 15, tzinfo=UTC)

    hose = by_uid[f"{HOSE.id}@domus"]
    assert str(hose["SUMMARY"]) == "Close outdoor hose valve, drain the hose"
    assert str(hose["DESCRIPTION"]) == HOSE.procedure

    water = by_uid[f"{FILTER.id}@domus"]
    assert water.decoded("DTSTART") == date(2027, 3, 1)
    assert str(water["DESCRIPTION"]) == (
        "Turn the old filter a quarter turn left.\n\nAsset: Kitchen refrigerator"
    )


@pytest.mark.parametrize(
    ("item", "lead"),
    [(SMOKE, timedelta(days=-7)), (HOSE, timedelta(0)), (FILTER, timedelta(days=-14))],
)
def test_alarm_fires_lead_days_before(item: MaintenanceTask, lead: timedelta) -> None:
    event = next(
        e
        for e in events(parse(build_calendar(HOME, ALL, now=NOW)))
        if e["UID"] == f"{item.id}@domus"
    )
    alarms = walk(event, "VALARM")
    assert len(alarms) == 1
    assert str(alarms[0]["ACTION"]) == "DISPLAY"
    assert str(alarms[0]["DESCRIPTION"]) == item.title
    assert alarms[0].decoded("TRIGGER") == lead


def test_negative_lead_days_alarm_at_start() -> None:
    odd = task("t-odd", "Odd", date(2026, 12, 1), lead_days=-3)
    (event,) = events(parse(build_calendar(HOME, [odd], now=NOW)))
    assert walk(event, "VALARM")[0].decoded("TRIGGER") == timedelta(0)


def test_output_is_deterministic() -> None:
    first = build_calendar(HOME, ALL, now=NOW, asset_names=NAMES)
    second = build_calendar(HOME, list(reversed(ALL)), now=NOW, asset_names=NAMES)
    assert first == second
    assert b"\r\n" in first  # RFC 5545 line endings


def test_now_is_stamped_in_utc() -> None:
    eastern = timezone(timedelta(hours=-5))
    local_now = datetime(2026, 11, 6, 7, 30, 15, tzinfo=eastern)
    (event,) = events(parse(build_calendar(HOME, [SMOKE], now=local_now)))
    assert event.decoded("DTSTAMP") == datetime(2026, 11, 6, 12, 30, 15, tzinfo=UTC)


def test_naive_now_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        build_calendar(HOME, [SMOKE], now=datetime(2026, 11, 6))


def test_text_is_escaped() -> None:
    tricky = task("t-x", "Line one\nBEGIN:VEVENT; x, y", date(2026, 12, 1), lead_days=1)
    data = build_calendar(HOME, [tricky], now=NOW)
    assert data.count(b"\r\nBEGIN:VEVENT\r\n") == 1
    (event,) = events(parse(data))
    assert str(event["SUMMARY"]) == "Line one\nBEGIN:VEVENT; x, y"
