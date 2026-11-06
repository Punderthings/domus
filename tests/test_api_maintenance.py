"""Maintenance task endpoints, completion, history, and the iCal feed."""

from typing import Any

import pytest
from fastapi import FastAPI
from icalendar import Calendar
from tests.asgi_client import Client
from tests.conftest import member_client

API = "/api/v1"


def ok(r: Any, code: int = 200) -> Any:
    assert r.status_code == code, r.text
    return r.json() if r.content else None


@pytest.fixture
def fridge(admin: Client, property_id: str) -> str:
    return ok(
        admin.post(f"{API}/assets", json={"property_id": property_id, "name": "Refrigerator"}), 201
    )["id"]


@pytest.fixture
def filter_task(admin: Client, property_id: str, fridge: str) -> dict[str, Any]:
    return ok(
        admin.post(
            f"{API}/maintenance/tasks",
            json={
                "property_id": property_id,
                "asset_id": fridge,
                "title": "Replace water filter",
                "schedule_kind": "after_completion",
                "interval_value": 6,
                "interval_unit": "month",
                "next_due": "2027-03-01",
            },
        ),
        201,
    )


def test_create_fixed_calendar_task_computes_next_due(admin: Client, property_id: str) -> None:
    t = ok(
        admin.post(
            f"{API}/maintenance/tasks",
            json={
                "property_id": property_id,
                "title": "Close hose valve",
                "schedule_kind": "fixed_calendar",
                "rrule": "FREQ=YEARLY;BYMONTH=11;BYMONTHDAY=1",
                "anchor_date": "2026-11-01",
            },
        ),
        201,
    )
    assert t["next_due"] == "2026-11-01"
    assert t["access"] == "manage"


@pytest.mark.parametrize(
    "bad",
    [
        {"schedule_kind": "after_completion"},  # no interval
        {"schedule_kind": "fixed_calendar", "rrule": "FREQ=YEARLY"},  # no anchor
        {"schedule_kind": "fixed_calendar", "rrule": "FREQ=HOURLY", "anchor_date": "2026-01-01"},
    ],
)
def test_invalid_schedules_rejected(admin: Client, property_id: str, bad: dict[str, Any]) -> None:
    r = admin.post(
        f"{API}/maintenance/tasks", json={"property_id": property_id, "title": "x", **bad}
    )
    assert r.status_code == 422


def test_complete_and_history(admin: Client, filter_task: dict[str, Any]) -> None:
    r = ok(
        admin.post(
            f"{API}/maintenance/tasks/{filter_task['id']}/complete",
            json={"performed_on": "2026-11-06", "cost": "49.99", "notes": "FR-WF1"},
        )
    )
    assert r["task"]["next_due"] == "2027-05-06"
    assert r["event"]["cost"] == "49.99"
    assert r["event"]["currency"] == "USD"
    events = ok(admin.get(f"{API}/maintenance/events", params={"task_id": filter_task["id"]}))
    assert [e["performed_on"] for e in events["items"]] == ["2026-11-06"]


def test_due_before_filter(admin: Client, filter_task: dict[str, Any]) -> None:
    due = ok(admin.get(f"{API}/maintenance/tasks", params={"due_before": "2027-03-02"}))["items"]
    assert [t["id"] for t in due] == [filter_task["id"]]
    assert (
        ok(admin.get(f"{API}/maintenance/tasks", params={"due_before": "2027-03-01"}))["items"]
        == []
    )


def test_guest_cannot_complete_or_see_costs(
    app: FastAPI, admin: Client, property_id: str, filter_task: dict[str, Any]
) -> None:
    ok(
        admin.post(
            f"{API}/maintenance/tasks/{filter_task['id']}/complete",
            json={"performed_on": "2026-11-06", "cost": "10"},
        )
    )
    guest = member_client(app, admin, property_id, "guest", "g@example.com")
    r = guest.post(
        f"{API}/maintenance/tasks/{filter_task['id']}/complete", json={"performed_on": "2026-11-07"}
    )
    assert r.status_code == 403
    events = ok(guest.get(f"{API}/maintenance/events"))["items"]
    assert events and all("cost" not in e and "notes" not in e for e in events)


def test_resident_can_complete_but_not_edit(
    app: FastAPI, admin: Client, property_id: str, filter_task: dict[str, Any]
) -> None:
    res = member_client(app, admin, property_id, "resident", "r@example.com")
    ok(
        res.post(
            f"{API}/maintenance/tasks/{filter_task['id']}/complete",
            json={"performed_on": "2026-11-06"},
        )
    )
    r = res.patch(f"{API}/maintenance/tasks/{filter_task['id']}", json={"title": "x"})
    assert r.status_code == 403


def test_changing_schedule_recomputes_next_due(admin: Client, filter_task: dict[str, Any]) -> None:
    t = ok(
        admin.patch(
            f"{API}/maintenance/tasks/{filter_task['id']}",
            json={
                "schedule_kind": "fixed_calendar",
                "rrule": "FREQ=YEARLY;BYMONTH=4;BYMONTHDAY=1",
                "anchor_date": "2027-04-01",
            },
        )
    )
    assert t["next_due"] == "2027-04-01"


def test_calendar_feed(admin: Client, app: FastAPI, filter_task: dict[str, Any]) -> None:
    token = ok(
        admin.post(f"{API}/auth/tokens", json={"name": "phone", "scopes": ["calendar"]}), 201
    )["token"]
    anon = Client(app)
    r = anon.get("/calendar.ics", params={"token": token})
    assert r.status_code == 200
    assert (r.header("content-type") or "").startswith("text/calendar")
    cal = Calendar.from_ical(r.content)
    events = [c for c in cal.walk("VEVENT")]  # pyright: ignore[reportUnknownMemberType]
    assert [str(e["SUMMARY"]) for e in events] == ["Replace water filter"]
    # A calendar-only token can't read the API, and a read token can't read the feed.
    assert (
        anon.get(f"{API}/assets", headers={"authorization": f"Bearer {token}"}).status_code == 403
    )
    read = ok(admin.post(f"{API}/auth/tokens", json={"name": "r"}), 201)["token"]
    assert anon.get("/calendar.ics", params={"token": read}).status_code == 401
    assert anon.get("/calendar.ics", params={"token": "domus_pat_nope"}).status_code == 401
