"""The search index (services/search.py) and GET /api/v1/search."""

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import Connection, Engine, delete, inspect, text
from sqlalchemy.orm import Session
from tests.asgi_client import Client
from tests.conftest import member_client, requires_postgres

from domus.api.app import create_app
from domus.backup import export_directory, import_source, open_source
from domus.backup.tables import export_tables
from domus.config import Settings
from domus.db import make_session_factory
from domus.migrate import alembic_config, upgrade
from domus.models import Asset, Product, Property
from domus.services import search
from domus.services.search import fts5_match, query_terms, tsquery_text

API = "/api/v1"


def ok(r: Any, code: int = 200) -> Any:
    assert r.status_code == code, r.text
    return r.json() if r.content else None


def clear_index(conn: Connection) -> None:
    table = "search_doc" if conn.dialect.name == "postgresql" else "search_fts"
    conn.execute(text(f"DELETE FROM {table}"))  # noqa: S608 - fixed table names


def find(c: Client, q: str, **params: Any) -> tuple[list[str], list[str]]:
    """Names of the matching (devices, areas)."""
    body = ok(c.get(f"{API}/search", params={"q": q, **params}))
    return [a["name"] for a in body["assets"]], [a["name"] for a in body["areas"]]


@pytest.fixture
def home(admin: Client, property_id: str) -> dict[str, str]:
    """Living room (public), bedroom (hidden from guests), utility room."""
    ids: dict[str, str] = {}
    building = ok(admin.get(f"{API}/buildings"))["items"][0]["id"]
    for key, name in [
        ("living", "Living Room"),
        ("bedroom", "Primary Bedroom"),
        ("utility", "Utility Closet"),
    ]:
        area = ok(
            admin.post(
                f"{API}/areas",
                json={"property_id": property_id, "building_id": building, "name": name},
            ),
            201,
        )
        ids[key] = area["id"]
        loc = ok(
            admin.post(f"{API}/locations", json={"area_id": area["id"], "name": "North wall"}),
            201,
        )
        ids[f"{key}_loc"] = loc["id"]
    ids["tag"] = ok(
        admin.post(f"{API}/tags", json={"property_id": property_id, "name": "Zigbee"}), 201
    )["id"]
    product = ok(
        admin.post(
            f"{API}/products",
            json={"manufacturer": "Ecobee", "model": "SmartThermostat Premium"},
        ),
        201,
    )
    ids["product"] = product["id"]

    def asset(key: str, name: str, loc: str, **extra: Any) -> None:
        body = {"property_id": property_id, "name": name, "location_id": ids[loc], **extra}
        ids[key] = ok(admin.post(f"{API}/assets", json=body), 201)["id"]

    asset(
        "light",
        "Living Room Lamp",
        "living_loc",
        category="lighting",
        tag_ids=[ids["tag"]],
        vendor="Hardware Barn",
        identifiers=[
            {"kind": "mac", "value": "02-00-5E-10-00-01"},
            {"kind": "serial", "value": "SN-77441"},
        ],
    )
    asset("bedlight", "Bedside Lamp", "bedroom_loc", category="lighting")
    asset(
        "thermostat",
        "Hallway climate control",
        "utility_loc",
        category="hvac",
        product_id=ids["product"],
        notes="Replaced the old Honeywell in 2024",
    )
    ok(
        admin.post(
            f"{API}/properties/{property_id}/access-rules",
            json={
                "scope_type": "area",
                "scope_id": ids["bedroom"],
                "subject_type": "role",
                "subject": "guest",
                "level": "hidden",
            },
        ),
        201,
    )
    return ids


# --- Query parsing ---------------------------------------------------------------


def test_query_terms_keep_only_letters_and_digits() -> None:
    assert query_terms('  Thermo-stat "NOT" a_b  (x) ') == ["thermo", "stat", "not", "a", "b", "x"]
    assert query_terms("Küche Øl 冷蔵庫") == ["küche", "øl", "冷蔵庫"]
    assert query_terms("!!! -- ::") == []
    assert len(query_terms(" ".join(f"w{i}" for i in range(20)))) == search.MAX_TERMS


def test_fts5_match_quotes_every_term() -> None:
    assert fts5_match(["not", "lamp"], include_private=True) == '"not"* "lamp"*'
    assert fts5_match(["lamp"], include_private=False) == '{title public_text} : ("lamp"*)'


def test_tsquery_text() -> None:
    assert tsquery_text(["ecobee", "therm"]) == "ecobee:* & therm:*"


# --- The endpoint -------------------------------------------------------------------


def test_finds_devices_by_name_prefix(admin: Client, home: dict[str, str]) -> None:
    assert sorted(find(admin, "lamp")[0]) == ["Bedside Lamp", "Living Room Lamp"]
    assert find(admin, "liv lam")[0] == ["Living Room Lamp"]
    assert find(admin, "LAMP living")[0] == ["Living Room Lamp"]


def test_title_matches_rank_first(admin: Client, home: dict[str, str]) -> None:
    devices, areas = find(admin, "living")
    # The lamp's own name says "Living"; nothing else does, but the area does.
    assert devices[0] == "Living Room Lamp"
    assert areas == ["Living Room"]


def test_finds_by_product_notes_tag_category_and_place(admin: Client, home: dict[str, str]) -> None:
    assert find(admin, "ecobee")[0] == ["Hallway climate control"]
    assert find(admin, "smartthermostat")[0] == ["Hallway climate control"]
    assert find(admin, "honeywell")[0] == ["Hallway climate control"]
    assert find(admin, "zigbee")[0] == ["Living Room Lamp"]
    assert find(admin, "hvac")[0] == ["Hallway climate control"]
    assert find(admin, "utility closet")[0] == ["Hallway climate control"]


def test_finds_areas(admin: Client, home: dict[str, str]) -> None:
    devices, areas = find(admin, "primary")
    assert areas == ["Primary Bedroom"]
    assert devices == ["Bedside Lamp"]  # found through its area's name


def test_members_find_identifiers_and_vendor(admin: Client, home: dict[str, str]) -> None:
    assert find(admin, "02:00:5e:10")[0] == ["Living Room Lamp"]
    assert find(admin, "SN-77441")[0] == ["Living Room Lamp"]
    assert find(admin, "hardware barn")[0] == ["Living Room Lamp"]


def test_guest_never_matches_private_fields(
    app: FastAPI, admin: Client, home: dict[str, str], property_id: str
) -> None:
    guest = member_client(app, admin, property_id, "guest", "guest@example.com")
    assert find(guest, "02:00:5e:10") == ([], [])
    assert find(guest, "77441") == ([], [])
    assert find(guest, "hardware") == ([], [])
    body = ok(guest.get(f"{API}/search", params={"q": "living lamp"}))
    assert [a["name"] for a in body["assets"]] == ["Living Room Lamp"]
    # Guest results use the guest schema.
    assert "vendor" not in body["assets"][0]
    assert "purchase_price" not in body["assets"][0]


def test_guest_never_sees_hidden_items(
    app: FastAPI, admin: Client, home: dict[str, str], property_id: str
) -> None:
    guest = member_client(app, admin, property_id, "guest", "guest@example.com")
    assert find(guest, "lamp")[0] == ["Living Room Lamp"]
    assert find(guest, "bedroom") == ([], [])
    assert find(guest, "bedside") == ([], [])


def test_results_carry_access(
    app: FastAPI, admin: Client, home: dict[str, str], property_id: str
) -> None:
    resident = member_client(app, admin, property_id, "resident", "res@example.com")
    body = ok(resident.get(f"{API}/search", params={"q": "living"}))
    assert body["assets"][0]["access"] == "control"
    assert body["areas"][0]["access"] == "control"
    assert body["query"] == "living"


def test_limit(admin: Client, home: dict[str, str]) -> None:
    body = ok(admin.get(f"{API}/search", params={"q": "lamp", "limit": 1}))
    assert len(body["assets"]) == 1


@pytest.mark.parametrize(
    "q",
    [
        "!!!",
        '"',
        "NOT",
        "lamp OR",
        "NEAR(lamp",
        "{title} : x",
        "a* b^ c-",
        "'; DROP TABLE asset; --",
        "\\",
        "%_",
    ],
)
def test_query_syntax_is_never_interpreted(admin: Client, home: dict[str, str], q: str) -> None:
    r = admin.get(f"{API}/search", params={"q": q})
    assert r.status_code == 200, r.text
    assert find(admin, "lamp")[0]  # and the index still works


def test_query_validation(admin: Client, home: dict[str, str]) -> None:
    assert admin.get(f"{API}/search", params={"q": ""}).status_code == 422
    assert admin.get(f"{API}/search", params={"q": "x" * 201}).status_code == 422
    assert admin.get(f"{API}/search", params={"q": "x", "limit": 51}).status_code == 422
    assert admin.get(f"{API}/search").status_code == 422


def test_requires_login(client: Client) -> None:
    assert client.get(f"{API}/search", params={"q": "x"}).status_code == 401


def test_requires_membership(admin: Client, home: dict[str, str]) -> None:
    r = admin.get(f"{API}/search", params={"q": "lamp", "property_id": "nope"})
    assert r.status_code == 404


# --- Keeping the index in sync --------------------------------------------------------


def test_index_follows_asset_changes(admin: Client, home: dict[str, str]) -> None:
    ok(admin.patch(f"{API}/assets/{home['light']}", json={"name": "Reading Light"}))
    assert find(admin, "reading")[0] == ["Reading Light"]
    assert "Living Room Lamp" not in find(admin, "lamp")[0]

    ok(admin.patch(f"{API}/assets/{home['light']}", json={"tag_ids": []}))
    assert find(admin, "zigbee")[0] == []

    ok(admin.patch(f"{API}/assets/{home['light']}", json={"tag_ids": [home["tag"]]}))
    assert find(admin, "zigbee")[0] == ["Reading Light"]

    ok(admin.patch(f"{API}/assets/{home['light']}", json={"location_id": home["utility_loc"]}))
    assert "Reading Light" in find(admin, "utility")[0]

    ok(admin.delete(f"{API}/assets/{home['light']}"), 204)
    assert find(admin, "reading")[0] == []


def test_index_follows_identifier_changes(admin: Client, home: dict[str, str]) -> None:
    row = ok(
        admin.post(
            f"{API}/assets/{home['thermostat']}/identifiers",
            json={"kind": "serial", "value": "TH-90210"},
        ),
        201,
    )
    assert find(admin, "th 90210")[0] == ["Hallway climate control"]
    ok(admin.delete(f"{API}/assets/{home['thermostat']}/identifiers/{row['id']}"), 204)
    assert find(admin, "90210")[0] == []


def test_index_follows_area_rename(admin: Client, home: dict[str, str]) -> None:
    ok(admin.patch(f"{API}/areas/{home['utility']}", json={"name": "Mechanical Room"}))
    devices, areas = find(admin, "mechanical")
    assert areas == ["Mechanical Room"]
    assert devices == ["Hallway climate control"]
    assert find(admin, "closet") == ([], [])


def test_index_follows_product_change(engine: Engine, admin: Client, home: dict[str, str]) -> None:
    factory = make_session_factory(engine)
    with factory() as s:
        product = s.get(Product, home["product"])
        assert product is not None
        product.manufacturer = "Acme"
        s.commit()
    assert find(admin, "acme")[0] == ["Hallway climate control"]
    assert find(admin, "ecobee")[0] == []


def test_rollback_leaves_the_index_alone(
    engine: Engine, admin: Client, home: dict[str, str]
) -> None:
    factory = make_session_factory(engine)
    with factory() as s:
        asset = s.get(Asset, home["thermostat"])
        assert asset is not None
        asset.name = "Never saved"
        s.flush()
        s.rollback()
        s.commit()  # nothing pending: must not index the rolled-back name
    assert find(admin, "never") == ([], [])
    assert find(admin, "hallway")[0] == ["Hallway climate control"]


def test_search_is_scoped_to_one_property(
    engine: Engine, session: Session, home: dict[str, str], property_id: str
) -> None:
    other = Property(name="Cabin")
    session.add(other)
    session.commit()
    with engine.connect() as conn:
        mine = search.search(conn, property_id, "lamp", include_private=True, limit=10)
        theirs = search.search(conn, other.id, "lamp", include_private=True, limit=10)
    assert {h.ref_id for h in mine} == {home["light"], home["bedlight"]}
    assert theirs == []


def test_startup_fills_an_empty_index(
    engine: Engine, settings: Settings, admin: Client, home: dict[str, str]
) -> None:
    with engine.begin() as conn:
        clear_index(conn)
        assert search.is_empty(conn)
    create_app(settings, engine)
    with engine.connect() as conn:
        assert not search.is_empty(conn)
    assert find(admin, "ecobee")[0] == ["Hallway climate control"]


def test_import_rebuilds_the_index(
    tmp_path: Path, engine: Engine, admin: Client, home: dict[str, str], property_id: str
) -> None:
    out = tmp_path / "export"
    export_directory(engine, out)
    # Wipe the index, then merge the same data back in: the import re-indexes.
    with engine.begin() as conn:
        clear_index(conn)
    with open_source(out) as source:
        import_source(engine, source)
    assert find(admin, "ecobee")[0] == ["Hallway climate control"]


def test_dry_run_import_does_not_touch_the_index(
    tmp_path: Path, engine: Engine, admin: Client, home: dict[str, str]
) -> None:
    out = tmp_path / "export"
    export_directory(engine, out)
    with engine.begin() as conn:
        clear_index(conn)
    with open_source(out) as source:
        import_source(engine, source, dry_run=True)
    with engine.connect() as conn:
        assert search.is_empty(conn)


def test_rebuild_drops_rows_that_are_gone(
    engine: Engine, home: dict[str, str], property_id: str
) -> None:
    with engine.begin() as conn:
        conn.execute(delete(Asset).where(Asset.id == home["bedlight"]))
        search.rebuild(conn)
        hits = search.search(conn, property_id, "bedside", include_private=True, limit=5)
    assert hits == []


def test_empty_query_terms_return_nothing(engine: Engine, home: dict[str, str]) -> None:
    with engine.connect() as conn:
        assert search.search(conn, "x", "--", include_private=True, limit=5) == []


def test_backups_never_carry_the_index() -> None:
    names = {t.name for t in export_tables(full=True)}
    assert not any(search.is_search_table(n) for n in names)


def test_migration_downgrade_and_upgrade(engine: Engine) -> None:
    from alembic import command

    cfg = alembic_config()
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.downgrade(cfg, "0002")
    table = "search_doc" if engine.dialect.name == "postgresql" else "search_fts"
    assert table not in inspect(engine).get_table_names()
    upgrade(engine)
    assert table in inspect(engine).get_table_names()


@requires_postgres
def test_postgres_finds_near_misses_in_titles(admin: Client, home: dict[str, str]) -> None:
    assert find(admin, "hallwya")[0] == ["Hallway climate control"]
