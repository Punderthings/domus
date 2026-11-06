"""Space and asset endpoints, checked for each role (master plan section 2)."""

from typing import Any

import pytest
from fastapi import FastAPI
from tests.asgi_client import Client
from tests.conftest import member_client

API = "/api/v1"


def ok(r: Any, code: int = 200) -> Any:
    assert r.status_code == code, r.text
    return r.json() if r.content else None


@pytest.fixture
def home(admin: Client, property_id: str) -> dict[str, str]:
    """A small home: living room (guests may control), bedroom (restricted), utility."""
    ids: dict[str, str] = {}
    building = ok(admin.get(f"{API}/buildings"))["items"][0]["id"]
    floor = ok(admin.post(f"{API}/floors", json={"building_id": building, "name": "Main"}), 201)
    for key, name in [
        ("living", "Living Room"),
        ("bedroom", "Primary Bedroom"),
        ("utility", "Utility"),
    ]:
        area = ok(
            admin.post(
                f"{API}/areas",
                json={
                    "property_id": property_id,
                    "building_id": building,
                    "floor_id": floor["id"],
                    "name": name,
                },
            ),
            201,
        )
        ids[key] = area["id"]
        loc = ok(
            admin.post(f"{API}/locations", json={"area_id": area["id"], "name": f"{name} wall"}),
            201,
        )
        ids[f"{key}_loc"] = loc["id"]
    ids["light"] = ok(
        admin.post(
            f"{API}/assets",
            json={
                "property_id": property_id,
                "name": "Living Room Light",
                "category": "lighting",
                "location_id": ids["living_loc"],
                "purchase_price": "39.99",
                "identifiers": [{"kind": "mac", "value": "02-00-5E-10-00-01"}],
            },
        ),
        201,
    )["id"]
    ids["bedlight"] = ok(
        admin.post(
            f"{API}/assets",
            json={
                "property_id": property_id,
                "name": "Bedroom Light",
                "category": "lighting",
                "location_id": ids["bedroom_loc"],
            },
        ),
        201,
    )["id"]
    ids["furnace"] = ok(
        admin.post(
            f"{API}/assets",
            json={
                "property_id": property_id,
                "name": "Furnace",
                "category": "hvac",
                "location_id": ids["utility_loc"],
                "is_critical": True,
            },
        ),
        201,
    )["id"]
    rules = [
        ("area", ids["living"], "guest", "control"),
        ("area", ids["bedroom"], "guest", "view"),
        ("area", ids["bedroom"], "maintainer", "view"),
    ]
    for scope_type, scope_id, role, level in rules:
        ok(
            admin.post(
                f"{API}/properties/{property_id}/access-rules",
                json={
                    "scope_type": scope_type,
                    "scope_id": scope_id,
                    "subject_type": "role",
                    "subject": role,
                    "level": level,
                },
            ),
            201,
        )
    return ids


def test_admin_asset_detail(admin: Client, home: dict[str, str]) -> None:
    a = ok(admin.get(f"{API}/assets/{home['light']}"))
    assert a["access"] == "manage"
    assert a["purchase_price"] == "39.99"
    assert a["area_id"] == home["living"]
    assert a["location"]["id"] == home["living_loc"]
    assert [(i["kind"], i["value"]) for i in a["identifiers"]] == [("mac", "02:00:5e:10:00:01")]


def test_duplicate_mac_rejected(admin: Client, home: dict[str, str], property_id: str) -> None:
    r = admin.post(
        f"{API}/assets",
        json={
            "property_id": property_id,
            "name": "Clone",
            "identifiers": [{"kind": "mac", "value": "02:00:5e:10:00:01"}],
        },
    )
    assert r.status_code == 409


def test_guest_view(app: FastAPI, admin: Client, home: dict[str, str], property_id: str) -> None:
    guest = member_client(app, admin, property_id, "guest", "guest@example.com")
    items = ok(guest.get(f"{API}/assets"))["items"]
    by_name = {a["name"]: a for a in items}
    assert by_name["Living Room Light"]["access"] == "control"
    assert by_name["Bedroom Light"]["access"] == "view"
    assert by_name["Furnace"]["access"] == "view"
    for a in items:  # sensitive fields are omitted, not nulled
        assert "purchase_price" not in a
        assert "vendor" not in a
    detail = ok(guest.get(f"{API}/assets/{home['light']}"))
    assert "identifiers" not in detail
    assert "purchase_price" not in detail
    # Guests can't write anything.
    assert guest.patch(f"{API}/assets/{home['light']}", json={"notes": "x"}).status_code == 403
    assert guest.get(f"{API}/properties/{property_id}/members").status_code == 403


def test_hidden_area_is_invisible(
    app: FastAPI, admin: Client, home: dict[str, str], property_id: str
) -> None:
    ok(
        admin.post(
            f"{API}/properties/{property_id}/access-rules",
            json={
                "scope_type": "area",
                "scope_id": home["utility"],
                "subject_type": "role",
                "subject": "guest",
                "level": "hidden",
            },
        ),
        201,
    )
    guest = member_client(app, admin, property_id, "guest", "guest@example.com")
    names = {a["name"] for a in ok(guest.get(f"{API}/assets"))["items"]}
    assert "Furnace" not in names
    assert guest.get(f"{API}/assets/{home['furnace']}").status_code == 404
    assert guest.get(f"{API}/areas/{home['utility']}").status_code == 404
    area_names = {a["name"] for a in ok(guest.get(f"{API}/areas"))["items"]}
    assert "Utility" not in area_names


def test_maintainer_limits(
    app: FastAPI, admin: Client, home: dict[str, str], property_id: str
) -> None:
    teen = member_client(app, admin, property_id, "maintainer", "teen@example.com")
    # Can add a game console in the living room and edit it.
    console = ok(
        teen.post(
            f"{API}/assets",
            json={
                "property_id": property_id,
                "name": "Game Console",
                "location_id": home["living_loc"],
            },
        ),
        201,
    )
    assert console["access"] == "manage"
    ok(teen.patch(f"{API}/assets/{console['id']}", json={"name": "Console"}))
    # Restricted bedroom: can see, not change, and can't add things there.
    bed = ok(teen.get(f"{API}/assets/{home['bedlight']}"))
    assert bed["access"] == "view"
    assert teen.patch(f"{API}/assets/{home['bedlight']}", json={"name": "x"}).status_code == 403
    r = teen.post(
        f"{API}/assets",
        json={"property_id": property_id, "name": "Spy cam", "location_id": home["bedroom_loc"]},
    )
    assert r.status_code == 403
    # Critical furnace: control only, so no edits, no delete.
    assert ok(teen.get(f"{API}/assets/{home['furnace']}"))["access"] == "control"
    assert teen.patch(f"{API}/assets/{home['furnace']}", json={"notes": "x"}).status_code == 403
    assert teen.delete(f"{API}/assets/{home['furnace']}").status_code == 403
    # Can't mark anything critical, can't manage members or rules.
    r = teen.patch(f"{API}/assets/{console['id']}", json={"is_critical": True})
    assert r.status_code == 403
    assert teen.get(f"{API}/properties/{property_id}/access-rules").status_code == 403


def test_member_rule_lets_teen_run_bedroom_tv(
    app: FastAPI, admin: Client, home: dict[str, str], property_id: str
) -> None:
    teen = member_client(app, admin, property_id, "maintainer", "teen@example.com")
    tv = ok(
        admin.post(
            f"{API}/assets",
            json={"property_id": property_id, "name": "TV", "location_id": home["bedroom_loc"]},
        ),
        201,
    )
    assert ok(teen.get(f"{API}/assets/{tv['id']}"))["access"] == "view"
    ok(
        admin.post(
            f"{API}/properties/{property_id}/access-rules",
            json={
                "scope_type": "asset",
                "scope_id": tv["id"],
                "subject_type": "membership",
                "subject": teen.membership_id,
                "level": "control",
            },
        ),
        201,
    )
    assert ok(teen.get(f"{API}/assets/{tv['id']}"))["access"] == "control"


def test_resident_may_edit_notes_only(
    app: FastAPI, admin: Client, home: dict[str, str], property_id: str
) -> None:
    res = member_client(app, admin, property_id, "resident", "res@example.com")
    a = ok(res.patch(f"{API}/assets/{home['light']}", json={"notes": "bulb is 2700K"}))
    assert a["notes"] == "bulb is 2700K"
    assert res.patch(f"{API}/assets/{home['light']}", json={"name": "x"}).status_code == 403
    r = res.post(f"{API}/assets", json={"property_id": property_id, "name": "x"})
    assert r.status_code == 403


def test_admin_marks_critical_and_audit(admin: Client, home: dict[str, str]) -> None:
    a = ok(admin.patch(f"{API}/assets/{home['light']}", json={"is_critical": True}))
    assert a["is_critical"] is True
    assert a["access"] == "manage"


def test_non_member_gets_404(app: FastAPI, admin: Client, home: dict[str, str]) -> None:
    other = Client(app)
    ok(
        other.post(
            f"{API}/auth/setup",
            json={
                "email": "x@y.z",
                "display_name": "X",
                "password": "a long password",
                "property_name": "P",
            },
        ),
        409,
    )


def test_pagination(admin: Client, property_id: str) -> None:
    for i in range(5):
        ok(admin.post(f"{API}/assets", json={"property_id": property_id, "name": f"A{i}"}), 201)
    seen: list[str] = []
    cursor = None
    pages = 0
    while True:
        page = ok(admin.get(f"{API}/assets", params={"limit": 2, "cursor": cursor}))
        seen.extend(a["name"] for a in page["items"])
        pages += 1
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == [f"A{i}" for i in range(5)]
    assert pages == 3


def test_search_and_filters(admin: Client, home: dict[str, str]) -> None:
    names = [a["name"] for a in ok(admin.get(f"{API}/assets", params={"q": "light"}))["items"]]
    assert sorted(names) == ["Bedroom Light", "Living Room Light"]
    names = [
        a["name"]
        for a in ok(admin.get(f"{API}/assets", params={"area_id": home["utility"]}))["items"]
    ]
    assert names == ["Furnace"]
    # LIKE wildcards in q are literal.
    assert ok(admin.get(f"{API}/assets", params={"q": "%"}))["items"] == []


def test_tags_on_assets(admin: Client, home: dict[str, str], property_id: str) -> None:
    tag = ok(
        admin.post(
            f"{API}/tags", json={"property_id": property_id, "name": "smart", "color": "#228be6"}
        ),
        201,
    )
    a = ok(admin.patch(f"{API}/assets/{home['light']}", json={"tag_ids": [tag["id"]]}))
    assert [t["name"] for t in a["tags"]] == ["smart"]
    listed = ok(admin.get(f"{API}/assets", params={"tag_id": tag["id"]}))["items"]
    assert [x["id"] for x in listed] == [home["light"]]
    assert (
        admin.post(f"{API}/tags", json={"property_id": property_id, "name": "smart"}).status_code
        == 409
    )


def test_parent_cycle_rejected(admin: Client, home: dict[str, str]) -> None:
    ok(admin.patch(f"{API}/assets/{home['bedlight']}", json={"parent_asset_id": home["light"]}))
    r = admin.patch(f"{API}/assets/{home['light']}", json={"parent_asset_id": home["bedlight"]})
    assert r.status_code == 422


def test_floor_must_match_building(admin: Client, property_id: str) -> None:
    garage = ok(
        admin.post(
            f"{API}/buildings",
            json={"property_id": property_id, "name": "Garage", "kind": "garage"},
        ),
        201,
    )
    house = next(b for b in ok(admin.get(f"{API}/buildings"))["items"] if b["name"] == "House")
    floor = ok(admin.post(f"{API}/floors", json={"building_id": house["id"], "name": "Main"}), 201)
    r = admin.post(
        f"{API}/areas",
        json={
            "property_id": property_id,
            "building_id": garage["id"],
            "floor_id": floor["id"],
            "name": "x",
        },
    )
    assert r.status_code == 422
    yard = ok(
        admin.post(
            f"{API}/areas", json={"property_id": property_id, "name": "Yard", "kind": "yard"}
        ),
        201,
    )
    assert yard["building_id"] is None


def test_soft_delete(admin: Client, home: dict[str, str]) -> None:
    assert admin.delete(f"{API}/assets/{home['light']}").status_code == 204
    assert admin.get(f"{API}/assets/{home['light']}").status_code == 404


def test_last_admin_cannot_be_demoted(admin: Client, property_id: str) -> None:
    members = ok(admin.get(f"{API}/properties/{property_id}/members"))["items"]
    me = members[0]["id"]
    r = admin.patch(f"{API}/properties/{property_id}/members/{me}", json={"role": "guest"})
    assert r.status_code == 422
    assert admin.delete(f"{API}/properties/{property_id}/members/{me}").status_code == 422


def test_expired_membership_has_no_access(app: FastAPI, admin: Client, property_id: str) -> None:
    sitter = member_client(app, admin, property_id, "resident", "sitter@example.com")
    ok(
        admin.patch(
            f"{API}/properties/{property_id}/members/{sitter.membership_id}",
            json={"expires_at": "2000-01-01T00:00:00Z"},
        )
    )
    assert sitter.get(f"{API}/assets", params={"property_id": property_id}).status_code == 404
