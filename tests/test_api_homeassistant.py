"""Home Assistant import through the API, against the fake HA server."""

from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session
from tests.asgi_client import Client
from tests.conftest import member_client
from tests.fake_ha import TOKEN, FakeHa

from domus.models import (
    Area,
    Asset,
    AssetIdentifier,
    AssetRelation,
    AuditLog,
    Floor,
    Location,
    Product,
    Tag,
)

API = "/api/v1"
PREVIEW = f"{API}/homeassistant/preview"
APPLY = f"{API}/homeassistant/apply"


def ok(r: Any, code: int = 200) -> Any:
    assert r.status_code == code, r.text
    return r.json() if r.content else None


def body(ha: FakeHa, **extra: Any) -> dict[str, Any]:
    return {"base_url": ha.url, "token": TOKEN, **extra}


def devices(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {d["ha_device_id"]: d for d in result["devices"]}


def count(engine: Engine, model: type[Any]) -> int:
    with Session(engine) as s:
        return s.scalar(select(func.count()).select_from(model)) or 0


def table_counts(engine: Engine) -> dict[str, int]:
    models = (Area, Asset, AssetIdentifier, AssetRelation, Floor, Location, Product, Tag)
    return {m.__tablename__: count(engine, m) for m in models}


# --- Preview ----------------------------------------------------------------


def test_preview_on_an_empty_home(admin: Client, fake_ha: FakeHa, engine: Engine) -> None:
    before = table_counts(engine)
    result = ok(admin.post(PREVIEW, json=body(fake_ha)))
    assert table_counts(engine) == before, "preview must not write"
    assert {f["status"] for f in result["floors"]} == {"new"}
    assert {a["status"] for a in result["areas"]} == {"new"}
    d = devices(result)
    assert d["dev_lamp"]["status"] == "new"
    assert d["dev_lamp"]["action"] == "create"
    assert d["dev_lamp"]["name"] == "Reading Lamp"
    assert d["dev_lamp"]["area_name"] == "Living Room"
    assert d["dev_sun"]["status"] == "ignored"
    assert d["dev_sun"]["action"] == "skip"
    assert "service" in d["dev_sun"]["note"]
    assert result["counts"] == {"new": 4, "ignored": 1}
    kinds = {(i["kind"], i["value"]) for i in d["dev_hub"]["new_identifiers"]}
    assert kinds == {
        ("ha_device_id", "dev_hub"),
        ("mac", "aa:bb:cc:00:00:01"),
        ("serial", "HUB-0001"),
    }


def test_token_is_never_echoed(admin: Client, fake_ha: FakeHa) -> None:
    r = admin.post(PREVIEW, json=body(fake_ha))
    assert TOKEN not in r.text
    r = admin.post(APPLY, json=body(fake_ha))
    assert TOKEN not in r.text
    r = admin.post(PREVIEW, json=body(fake_ha, token="wrong"))  # noqa: S106
    assert r.status_code == 422
    assert "wrong" not in r.text


def test_preview_errors(admin: Client, fake_ha: FakeHa) -> None:
    r = admin.post(PREVIEW, json=body(fake_ha, token="nope"))  # noqa: S106
    assert r.status_code == 422
    assert "rejected" in r.json()["detail"]
    r = admin.post(PREVIEW, json=body(fake_ha, base_url="ftp://ha.local"))
    assert r.status_code == 502
    fake_ha.not_home_assistant = True
    r = admin.post(PREVIEW, json=body(fake_ha))
    assert r.status_code == 502


@pytest.mark.parametrize("role", ["resident", "guest"])
def test_only_maintainers_and_admins(
    app: FastAPI, admin: Client, property_id: str, fake_ha: FakeHa, role: str
) -> None:
    c = member_client(app, admin, property_id, role, f"{role}@example.com")
    assert c.post(PREVIEW, json=body(fake_ha)).status_code == 403
    assert c.post(APPLY, json=body(fake_ha)).status_code == 403
    # Refused before the server connected anywhere.
    assert fake_ha.connections == 0


def test_requires_login(client: Client, fake_ha: FakeHa) -> None:
    assert client.post(PREVIEW, json=body(fake_ha)).status_code == 401
    assert fake_ha.connections == 0


# --- Apply ------------------------------------------------------------------


def test_apply_creates_and_is_idempotent(admin: Client, fake_ha: FakeHa, engine: Engine) -> None:
    result = ok(admin.post(APPLY, json=body(fake_ha)))
    assert result["floors_created"] == 2
    assert result["areas_created"] == 4
    assert result["relations_created"] == 1
    assert result["counts"] == {"created": 4, "skipped": 1}
    d = devices(result)
    assert d["dev_sun"]["outcome"] == "skipped"

    lamp = ok(admin.get(f"{API}/assets/{d['dev_lamp']['asset_id']}"))
    assert lamp["name"] == "Reading Lamp"
    assert lamp["category"] == "lighting"
    assert lamp["sw_version"] == "1.104.2"
    assert lamp["product"]["manufacturer"] == "Signify"
    assert lamp["location"]["kind"] == "unspecified"
    assert [t["name"] for t in lamp["tags"]] == ["Lights"]
    assert {(i["kind"], i["value"], i["source"]) for i in lamp["identifiers"]} == {
        ("ha_device_id", "dev_lamp", "home_assistant"),
        ("zigbee_ieee", "00:17:88:01:0a:0b:0c:0d", "home_assistant"),
    }
    assert ok(admin.get(f"{API}/assets/{d['dev_thermostat']['asset_id']}"))["category"] == "hvac"
    fridge = ok(admin.get(f"{API}/assets/{d['dev_fridge']['asset_id']}"))
    assert fridge["category"] == "sensor"
    with Session(engine) as s:
        rel = s.scalars(select(AssetRelation)).one()
        assert (rel.from_asset_id, rel.to_asset_id, rel.kind) == (
            d["dev_lamp"]["asset_id"],
            d["dev_hub"]["asset_id"],
            "networked_via",
        )
        hub = s.get(Asset, d["dev_hub"]["asset_id"])
        assert hub is not None and hub.extra is not None
        assert hub.extra["home_assistant"]["device_id"] == "dev_hub"
        garden = s.scalars(select(Area).where(Area.ha_area_id == "garden")).one()
        assert garden.floor_id is None
        upstairs = s.scalars(select(Floor).where(Floor.ha_floor_id == "upstairs")).one()
        assert upstairs.level == 1
        audits = s.scalar(select(func.count()).where(AuditLog.action == "import"))
        assert audits == 1

    before = table_counts(engine)
    again = ok(admin.post(APPLY, json=body(fake_ha)))
    assert table_counts(engine) == before
    assert again["floors_created"] == 0
    assert again["areas_created"] == 0
    assert again["relations_created"] == 0
    assert again["counts"] == {"unchanged": 4, "skipped": 1}
    preview = ok(admin.post(PREVIEW, json=body(fake_ha)))
    assert preview["counts"] == {"linked": 4, "ignored": 1}
    assert {f["status"] for f in preview["floors"]} == {"matched"}
    assert {a["match_reason"] for a in preview["areas"]} == {"ha_area_id"}


def test_reimport_updates_firmware_but_not_names(
    admin: Client, fake_ha: FakeHa, engine: Engine
) -> None:
    first = devices(ok(admin.post(APPLY, json=body(fake_ha))))
    lamp_id = first["dev_lamp"]["asset_id"]
    ok(admin.patch(f"{API}/assets/{lamp_id}", json={"name": "Grandma's lamp"}))
    lamp = fake_ha.device("dev_lamp")
    lamp["sw_version"] = "1.200.0"
    lamp["name_by_user"] = "HA renamed it"
    lamp["connections"].append(["mac", "02:00:00:00:00:42"])

    preview = devices(ok(admin.post(PREVIEW, json=body(fake_ha))))
    assert preview["dev_lamp"]["status"] == "changed"
    assert preview["dev_lamp"]["asset_name"] == "Grandma's lamp"
    assert preview["dev_lamp"]["changes"] == [
        {"field": "sw_version", "old": "1.104.2", "new": "1.200.0"}
    ]
    assert preview["dev_lamp"]["new_identifiers"] == [{"kind": "mac", "value": "02:00:00:00:00:42"}]

    result = devices(ok(admin.post(APPLY, json=body(fake_ha))))
    assert result["dev_lamp"]["outcome"] == "updated"
    asset = ok(admin.get(f"{API}/assets/{lamp_id}"))
    assert asset["name"] == "Grandma's lamp"
    assert asset["sw_version"] == "1.200.0"
    assert ("mac", "02:00:00:00:00:42") in {(i["kind"], i["value"]) for i in asset["identifiers"]}
    with Session(engine) as s:
        a = s.get(Asset, lamp_id)
        assert a is not None and a.extra is not None
        assert a.extra["home_assistant"]["name_by_user"] == "HA renamed it"


def _existing(admin: Client, property_id: str, **fields: Any) -> str:
    return ok(admin.post(f"{API}/assets", json={"property_id": property_id, **fields}), 201)["id"]


def test_matches_existing_devices_instead_of_duplicating(
    admin: Client, property_id: str, fake_ha: FakeHa, engine: Engine
) -> None:
    # Already in Domus before HA was connected: matched by MAC, by serial and
    # manufacturer, and by name in the same Area.
    hub = _existing(
        admin,
        property_id,
        name="Hub in the closet",
        identifiers=[{"kind": "mac", "value": "AA:BB:CC:00:00:01"}],
    )
    product = ok(admin.post(f"{API}/products", json={"manufacturer": "COOLCO", "model": "x"}), 201)
    fridge = _existing(
        admin,
        property_id,
        name="Kitchen fridge",
        product_id=product["id"],
        identifiers=[{"kind": "serial", "value": "SN-12345"}],
    )
    building = ok(admin.get(f"{API}/buildings"))["items"][0]["id"]
    bedroom = ok(
        admin.post(
            f"{API}/areas",
            json={"property_id": property_id, "building_id": building, "name": "bedroom"},
        ),
        201,
    )
    wall = ok(admin.post(f"{API}/locations", json={"area_id": bedroom["id"], "name": "Wall"}), 201)
    thermostat = _existing(
        admin, property_id, name="Bedroom thermostat", location_id=wall["id"], category="hvac"
    )
    # Same name, but a different Area: not a match.
    _existing(admin, property_id, name="Reading Lamp")

    d = devices(ok(admin.post(PREVIEW, json=body(fake_ha))))
    assert (d["dev_hub"]["status"], d["dev_hub"]["match_reason"]) == ("matched", "connection")
    assert d["dev_hub"]["asset_id"] == hub
    assert (d["dev_fridge"]["match_reason"], d["dev_fridge"]["asset_id"]) == ("serial", fridge)
    assert d["dev_thermostat"]["match_reason"] == "name"
    assert d["dev_thermostat"]["asset_id"] == thermostat
    assert d["dev_thermostat"]["action"] == "link"
    assert d["dev_lamp"]["status"] == "new"
    areas = {a["ha_area_id"]: a for a in ok(admin.post(PREVIEW, json=body(fake_ha)))["areas"]}
    assert (areas["bedroom"]["status"], areas["bedroom"]["match_reason"]) == ("matched", "name")

    assets_before = count(engine, Asset)
    result = devices(ok(admin.post(APPLY, json=body(fake_ha))))
    assert result["dev_hub"]["outcome"] == "updated"
    assert result["dev_hub"]["asset_id"] == hub
    assert result["dev_thermostat"]["asset_id"] == thermostat
    assert count(engine, Asset) == assets_before + 1  # only the lamp is new
    hub_asset = ok(admin.get(f"{API}/assets/{hub}"))
    assert hub_asset["name"] == "Hub in the closet"
    assert hub_asset["product"]["model"] == "Hub 2"
    # The thermostat stays where the user put it.
    assert ok(admin.get(f"{API}/assets/{thermostat}"))["location_id"] == wall["id"]
    with Session(engine) as s:
        area = s.get(Area, bedroom["id"])
        assert area is not None and area.ha_area_id == "bedroom"


def test_user_choices(admin: Client, property_id: str, fake_ha: FakeHa, engine: Engine) -> None:
    other = _existing(admin, property_id, name="Some lamp")
    choices = [
        {"ha_device_id": "dev_hub", "action": "skip"},
        {"ha_device_id": "dev_lamp", "action": "link", "asset_id": other},
        {"ha_device_id": "dev_sun", "action": "create"},
    ]
    d = devices(ok(admin.post(APPLY, json=body(fake_ha, devices=choices))))
    assert d["dev_hub"]["outcome"] == "skipped"
    assert d["dev_lamp"] == {
        "ha_device_id": "dev_lamp",
        "name": "Reading Lamp",
        "outcome": "updated",
        "asset_id": other,
        "note": None,
    }
    assert d["dev_sun"]["outcome"] == "created"
    # Skipping a device leaves it unlinked, so the next preview offers it again.
    p = devices(ok(admin.post(PREVIEW, json=body(fake_ha))))
    assert p["dev_hub"]["status"] == "new"
    assert p["dev_lamp"]["status"] == "linked"

    # Asking to create an already linked device never duplicates it.
    before = count(engine, Asset)
    again = devices(
        ok(
            admin.post(
                APPLY,
                json=body(fake_ha, devices=[{"ha_device_id": "dev_lamp", "action": "create"}]),
            )
        )
    )
    assert again["dev_lamp"]["asset_id"] == other
    assert count(engine, Asset) == before + 1  # the hub, which is now created by default


def test_refused_choices_roll_back(
    admin: Client, property_id: str, fake_ha: FakeHa, engine: Engine
) -> None:
    ok(admin.post(APPLY, json=body(fake_ha)))
    first = devices(ok(admin.post(PREVIEW, json=body(fake_ha))))
    before = table_counts(engine)
    # Linking one HA device to another's Domus device.
    r = admin.post(
        APPLY,
        json=body(
            fake_ha,
            devices=[
                {
                    "ha_device_id": "dev_lamp",
                    "action": "link",
                    "asset_id": first["dev_hub"]["asset_id"],
                }
            ],
        ),
    )
    assert r.status_code == 409
    # An id that isn't in Home Assistant (stale preview).
    r = admin.post(APPLY, json=body(fake_ha, devices=[{"ha_device_id": "gone", "action": "skip"}]))
    assert r.status_code == 409
    # Linking to a device that doesn't exist.
    unlinked = _existing(admin, property_id, name="Spare")
    fake_ha.registries["devices"].append({"id": "dev_new", "name": "New"})
    r = admin.post(
        APPLY,
        json=body(
            fake_ha, devices=[{"ha_device_id": "dev_new", "action": "link", "asset_id": "nope"}]
        ),
    )
    assert r.status_code == 409
    assert table_counts(engine) == {**before, "asset": before["asset"] + 1}
    assert unlinked


def test_floor_to_building_mapping(
    admin: Client, property_id: str, fake_ha: FakeHa, engine: Engine
) -> None:
    garage = ok(
        admin.post(
            f"{API}/buildings",
            json={"property_id": property_id, "name": "Garage", "kind": "garage"},
        ),
        201,
    )
    preview = ok(
        admin.post(PREVIEW, json=body(fake_ha, building_for_floor={"upstairs": garage["id"]}))
    )
    floors = {f["ha_floor_id"]: f for f in preview["floors"]}
    assert floors["upstairs"]["building_id"] == garage["id"]
    ok(admin.post(APPLY, json=body(fake_ha, building_for_floor={"upstairs": garage["id"]})))
    with Session(engine) as s:
        floor = s.scalars(select(Floor).where(Floor.ha_floor_id == "upstairs")).one()
        assert floor.building_id == garage["id"]
        bedroom = s.scalars(select(Area).where(Area.ha_area_id == "bedroom")).one()
        assert (bedroom.building_id, bedroom.floor_id) == (garage["id"], floor.id)
    r = admin.post(PREVIEW, json=body(fake_ha, building_for_floor={"upstairs": "nope"}))
    assert r.status_code == 409


def test_maintainer_cannot_touch_critical_items(
    app: FastAPI, admin: Client, property_id: str, fake_ha: FakeHa, engine: Engine
) -> None:
    building = ok(admin.get(f"{API}/buildings"))["items"][0]["id"]
    kitchen = ok(
        admin.post(
            f"{API}/areas",
            json={
                "property_id": property_id,
                "building_id": building,
                "name": "Kitchen",
                "is_critical": True,
            },
        ),
        201,
    )
    alarm = _existing(
        admin,
        property_id,
        name="Old hub",
        is_critical=True,
        identifiers=[{"kind": "mac", "value": "aa:bb:cc:00:00:01"}],
    )
    maint = member_client(app, admin, property_id, "maintainer", "m@example.com")
    d = devices(ok(maint.post(PREVIEW, json=body(fake_ha))))
    assert d["dev_hub"]["status"] == "matched"
    assert d["dev_hub"]["can_apply"] is False
    assert d["dev_hub"]["action"] == "skip"
    assert d["dev_fridge"]["can_apply"] is False  # new, but in a critical Area
    assert d["dev_fridge"]["action"] == "skip"

    result = devices(ok(maint.post(APPLY, json=body(fake_ha))))
    assert result["dev_hub"]["outcome"] == "skipped"
    assert result["dev_fridge"]["outcome"] == "skipped"
    assert result["dev_lamp"]["outcome"] == "created"
    r = maint.post(
        APPLY,
        json=body(
            fake_ha, devices=[{"ha_device_id": "dev_hub", "action": "link", "asset_id": alarm}]
        ),
    )
    assert r.status_code == 409
    with Session(engine) as s:
        assert s.get(Area, kitchen["id"]).ha_area_id is None  # pyright: ignore[reportOptionalMemberAccess]
        hub_ids = s.scalars(
            select(AssetIdentifier.kind).where(AssetIdentifier.asset_id == alarm)
        ).all()
        assert "ha_device_id" not in hub_ids


def test_mac_already_on_another_device(admin: Client, property_id: str, fake_ha: FakeHa) -> None:
    # The hub's MAC is on a Domus device that is already linked to some other
    # HA device, so the hub is created without that MAC, and the user is told.
    _existing(
        admin,
        property_id,
        name="Router",
        identifiers=[
            {"kind": "mac", "value": "aa:bb:cc:00:00:01"},
            {"kind": "ha_device_id", "value": "dev_router"},
        ],
    )
    d = devices(ok(admin.post(PREVIEW, json=body(fake_ha))))
    assert d["dev_hub"]["status"] == "new"
    assert "mac" in d["dev_hub"]["note"]
    result = devices(ok(admin.post(APPLY, json=body(fake_ha))))
    hub = ok(admin.get(f"{API}/assets/{result['dev_hub']['asset_id']}"))
    assert "mac" not in {i["kind"] for i in hub["identifiers"]}
