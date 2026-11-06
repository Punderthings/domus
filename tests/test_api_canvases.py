"""Uploads, floor plans, wall photos, and device pins (master plan step 9)."""

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from tests.asgi_client import Client
from tests.conftest import member_client
from tests.images import PDF, png

from domus.config import Settings

API = "/api/v1"


def pixels(data: bytes) -> tuple[tuple[int, int], Any]:
    """Size and first pixel of an image: uploads are re-encoded, so bytes change."""
    from io import BytesIO

    from PIL import Image

    with Image.open(BytesIO(data)) as img:
        return img.size, img.convert("RGB").getpixel((0, 0))


def ok(r: Any, code: int = 200) -> Any:
    assert r.status_code == code, r.text
    return r.json() if r.content else None


def upload(c: Client, data: bytes, **params: Any) -> Any:
    return c.post(f"{API}/documents", content=data, params=params)


@pytest.fixture
def home(admin: Client, property_id: str) -> dict[str, str]:
    """A floor with a living room (guests may control) and a utility room hidden from guests."""
    ids: dict[str, str] = {}
    ids["building"] = ok(admin.get(f"{API}/buildings"))["items"][0]["id"]
    ids["floor"] = ok(
        admin.post(f"{API}/floors", json={"building_id": ids["building"], "name": "Main"}), 201
    )["id"]
    for key, name in [("living", "Living Room"), ("utility", "Utility")]:
        area = ok(
            admin.post(
                f"{API}/areas",
                json={
                    "property_id": property_id,
                    "building_id": ids["building"],
                    "floor_id": ids["floor"],
                    "name": name,
                },
            ),
            201,
        )
        ids[key] = area["id"]
        loc = ok(admin.post(f"{API}/locations", json={"area_id": area["id"], "name": "Wall"}), 201)
        ids[f"{key}_loc"] = loc["id"]
    for key, name, loc in [
        ("light", "Ceiling Light", "living_loc"),
        ("pump", "Sump", "utility_loc"),
    ]:
        ids[key] = ok(
            admin.post(
                f"{API}/assets",
                json={"property_id": property_id, "name": name, "location_id": ids[loc]},
            ),
            201,
        )["id"]
    ok(
        admin.post(
            f"{API}/properties/{property_id}/access-rules",
            json={
                "scope_type": "area",
                "scope_id": ids["utility"],
                "subject_type": "role",
                "subject": "guest",
                "level": "hidden",
            },
        ),
        201,
    )
    ids["plan_doc"] = ok(
        upload(admin, png(4, 3), kind="floor_plan", filename="main.png", sensitivity="guest"), 201
    )["id"]
    return ids


@pytest.fixture
def plan(admin: Client, home: dict[str, str]) -> dict[str, Any]:
    return ok(
        admin.post(
            f"{API}/canvases",
            json={
                "document_id": home["plan_doc"],
                "scope_type": "floor",
                "scope_id": home["floor"],
                "kind": "floor_plan",
                "name": "Main floor",
            },
        ),
        201,
    )


def pin(c: Client, canvas_id: str, asset_id: str, x: float = 0.25, y: float = 0.5) -> Any:
    return c.post(
        f"{API}/placements", json={"canvas_id": canvas_id, "asset_id": asset_id, "x": x, "y": y}
    )


# --- Documents ----------------------------------------------------------------


def test_upload_and_download_image(admin: Client, settings: Settings) -> None:
    data = png()
    doc = ok(upload(admin, data, kind="photo", filename="../x/wall.png", title="Wall"), 201)
    assert doc["mime_type"] == "image/png"
    assert doc["size"] > 0
    assert doc["original_filename"] == "wall.png"
    assert doc["sensitivity"] == "resident"
    r = admin.get(doc["content_url"])
    assert r.status_code == 200
    assert pixels(r.content) == pixels(data)
    assert r.header("content-type") == "image/png"
    assert r.header("x-content-type-options") == "nosniff"
    assert "sandbox" in (r.header("content-security-policy") or "")
    assert (r.header("content-disposition") or "").startswith("inline")
    assert ok(admin.get(f"{API}/documents/{doc['id']}"))["id"] == doc["id"]
    assert list((settings.blobs_dir / ".staging").iterdir()) == []


def test_pdf_is_served_as_attachment(admin: Client) -> None:
    doc = ok(upload(admin, PDF, kind="manual", filename="manual.pdf"), 201)
    r = admin.get(doc["content_url"])
    assert r.header("content-type") == "application/pdf"
    assert (r.header("content-disposition") or "").startswith("attachment")


def test_same_bytes_share_one_blob(admin: Client, settings: Settings) -> None:
    a = ok(upload(admin, png()), 201)
    b = ok(upload(admin, png()), 201)
    assert a["id"] != b["id"]
    blobs = [p for p in settings.blobs_dir.rglob("*") if p.is_file()]
    assert len(blobs) == 1


def test_fake_image_is_refused(admin: Client) -> None:
    r = upload(admin, b"\x89PNG\r\n\x1a\n" + b"junk" * 10)
    assert r.status_code == 422


@pytest.mark.parametrize(
    "data", [b"<svg xmlns='http://www.w3.org/2000/svg'><script/></svg>", b"hello", b""]
)
def test_unsupported_types_are_refused(admin: Client, data: bytes) -> None:
    r = upload(admin, data, filename="evil.png")
    assert r.status_code == 415


def test_upload_size_limit(tmp_path: Path, engine: Any) -> None:
    from domus.api.app import create_app

    settings = Settings(data_dir=tmp_path / "small", cookie_secure=False, upload_max_bytes=64)
    c = Client(create_app(settings, engine))
    ok(
        c.post(
            f"{API}/auth/setup",
            json={
                "email": "a@example.com",
                "display_name": "A",
                "password": "correct horse battery",
                "property_name": "Home",
                "timezone": "UTC",
            },
        ),
        201,
    )
    assert upload(c, png(100, 100) + b"\x00" * 64).status_code == 413
    assert list((settings.blobs_dir / ".staging").iterdir()) == []


def test_guest_cannot_upload_or_read_resident_documents(
    app: FastAPI, admin: Client, property_id: str
) -> None:
    doc = ok(upload(admin, PDF, kind="receipt"), 201)
    guest = member_client(app, admin, property_id, "guest", "guest@example.com")
    assert upload(guest, png()).status_code == 403
    assert guest.get(f"{API}/documents/{doc['id']}").status_code == 404
    assert guest.get(doc["content_url"]).status_code == 404


def test_resident_cannot_upload_admin_only(app: FastAPI, admin: Client, property_id: str) -> None:
    resident = member_client(app, admin, property_id, "resident", "res@example.com")
    assert upload(resident, PDF, sensitivity="admin").status_code == 403
    doc = ok(upload(resident, PDF), 201)
    assert resident.delete(f"{API}/documents/{doc['id']}").status_code == 204
    assert resident.get(f"{API}/documents/{doc['id']}").status_code == 404


def test_upload_needs_csrf(admin: Client) -> None:
    admin.send_csrf = False
    assert upload(admin, png()).status_code == 403


# --- Canvases -----------------------------------------------------------------


def test_floor_plan_round_trip(admin: Client, home: dict[str, str], plan: dict[str, Any]) -> None:
    assert plan["access"] == "manage"
    assert plan["image_url"] == f"/api/v1/canvases/{plan['id']}/image?v={home['plan_doc']}"
    r = admin.get(plan["image_url"])
    assert r.status_code == 200
    assert pixels(r.content) == pixels(png(4, 3))
    listed = ok(
        admin.get(f"{API}/canvases", params={"scope_type": "floor", "scope_id": home["floor"]})
    )
    assert [c["id"] for c in listed["items"]] == [plan["id"]]
    assert ok(admin.get(f"{API}/canvases", params={"kind": "wall_photo"}))["items"] == []


def test_canvas_needs_an_image_in_this_property(admin: Client, home: dict[str, str]) -> None:
    pdf = ok(upload(admin, PDF), 201)
    body = {"scope_type": "floor", "scope_id": home["floor"], "kind": "floor_plan"}
    r = admin.post(f"{API}/canvases", json={**body, "document_id": pdf["id"]})
    assert r.status_code == 422
    r = admin.post(f"{API}/canvases", json={**body, "document_id": "nope"})
    assert r.status_code == 422
    r = admin.post(
        f"{API}/canvases", json={**body, "document_id": home["plan_doc"], "scope_id": "nope"}
    )
    assert r.status_code == 422


def test_wall_photo_on_an_area(admin: Client, home: dict[str, str]) -> None:
    photo = ok(upload(admin, png(), kind="wall_photo"), 201)
    c = ok(
        admin.post(
            f"{API}/canvases",
            json={
                "document_id": photo["id"],
                "scope_type": "area",
                "scope_id": home["living"],
                "kind": "wall_photo",
                "name": "Switches by the door",
            },
        ),
        201,
    )
    p = ok(pin(admin, c["id"], home["light"], 0.9, 0.1), 201)
    assert p["asset_name"] == "Ceiling Light"


def test_replacing_the_image_keeps_pins(
    admin: Client, home: dict[str, str], plan: dict[str, Any]
) -> None:
    p = ok(pin(admin, plan["id"], home["light"], 0.1, 0.2), 201)
    new_doc = ok(upload(admin, png(8, 6, (0, 0, 255)), kind="floor_plan"), 201)
    updated = ok(admin.patch(f"{API}/canvases/{plan['id']}", json={"document_id": new_doc["id"]}))
    assert updated["image_url"].endswith(new_doc["id"])
    assert pixels(admin.get(updated["image_url"]).content) == ((8, 6), (0, 0, 255))
    pins = ok(admin.get(f"{API}/canvases/{plan['id']}/placements"))["items"]
    assert [(q["id"], q["x"], q["y"]) for q in pins] == [(p["id"], 0.1, 0.2)]
    r = admin.patch(f"{API}/canvases/{plan['id']}", json={"document_id": None})
    assert r.status_code == 422


def test_delete_canvas_removes_its_pins(
    admin: Client, home: dict[str, str], plan: dict[str, Any]
) -> None:
    ok(pin(admin, plan["id"], home["light"]), 201)
    assert len(ok(admin.get(f"{API}/placements", params={"asset_id": home["light"]}))["items"]) == 1
    assert admin.delete(f"{API}/canvases/{plan['id']}").status_code == 204
    assert admin.get(f"{API}/canvases/{plan['id']}").status_code == 404
    assert ok(admin.get(f"{API}/placements", params={"asset_id": home["light"]}))["items"] == []


# --- Placements ---------------------------------------------------------------


def test_place_and_drag_a_pin(admin: Client, home: dict[str, str], plan: dict[str, Any]) -> None:
    p = ok(pin(admin, plan["id"], home["light"]), 201)
    assert (p["x"], p["y"], p["shape"], p["access"]) == (0.25, 0.5, "point", "manage")
    moved = ok(admin.patch(f"{API}/placements/{p['id']}", json={"x": 1, "y": 0, "label": "L1"}))
    assert (moved["x"], moved["y"], moved["label"]) == (1, 0, "L1")
    assert admin.patch(f"{API}/placements/{p['id']}", json={"x": None}).status_code == 422
    assert pin(admin, plan["id"], home["light"]).status_code == 409
    assert admin.delete(f"{API}/placements/{p['id']}").status_code == 204
    assert ok(pin(admin, plan["id"], home["light"]), 201)["id"] != p["id"]


@pytest.mark.parametrize(("x", "y"), [(-0.01, 0.5), (0.5, 1.01), (2, 2)])
def test_pins_must_be_normalized(
    admin: Client, home: dict[str, str], plan: dict[str, Any], x: float, y: float
) -> None:
    assert pin(admin, plan["id"], home["light"], x, y).status_code == 422


def test_pin_needs_a_device_in_this_property(
    admin: Client, home: dict[str, str], plan: dict[str, Any]
) -> None:
    assert pin(admin, plan["id"], "missing").status_code == 422
    ok(admin.delete(f"{API}/assets/{home['pump']}"), 204)
    assert pin(admin, plan["id"], home["pump"]).status_code == 422


def test_guest_sees_plan_but_not_hidden_pins(
    app: FastAPI, admin: Client, home: dict[str, str], plan: dict[str, Any], property_id: str
) -> None:
    ok(pin(admin, plan["id"], home["light"]), 201)
    hidden = ok(pin(admin, plan["id"], home["pump"], 0.8, 0.8), 201)
    guest = member_client(app, admin, property_id, "guest", "guest@example.com")
    g_plan = ok(guest.get(f"{API}/canvases/{plan['id']}"))
    assert g_plan["access"] == "view"
    assert guest.get(g_plan["image_url"]).status_code == 200
    pins = ok(guest.get(f"{API}/canvases/{plan['id']}/placements"))["items"]
    assert [p["asset_name"] for p in pins] == ["Ceiling Light"]
    assert all(p["access"] == "view" for p in pins)
    assert guest.patch(f"{API}/placements/{pins[0]['id']}", json={"x": 0}).status_code == 403
    assert guest.patch(f"{API}/placements/{hidden['id']}", json={"x": 0}).status_code == 403
    assert guest.get(f"{API}/placements", params={"asset_id": home["pump"]}).status_code == 404


def test_resident_views_but_cannot_edit_pins(
    app: FastAPI, admin: Client, home: dict[str, str], plan: dict[str, Any], property_id: str
) -> None:
    resident = member_client(app, admin, property_id, "resident", "res@example.com")
    assert ok(resident.get(f"{API}/canvases/{plan['id']}"))["access"] == "control"
    assert pin(resident, plan["id"], home["light"]).status_code == 403
    assert resident.delete(f"{API}/canvases/{plan['id']}").status_code == 403


def test_maintainer_manages_pins(
    app: FastAPI, admin: Client, home: dict[str, str], plan: dict[str, Any], property_id: str
) -> None:
    m = member_client(app, admin, property_id, "maintainer", "m@example.com")
    p = ok(pin(m, plan["id"], home["light"]), 201)
    ok(m.patch(f"{API}/placements/{p['id']}", json={"y": 0.75}))


def test_hidden_building_hides_its_floor_plan(
    app: FastAPI, admin: Client, home: dict[str, str], plan: dict[str, Any], property_id: str
) -> None:
    ok(
        admin.post(
            f"{API}/properties/{property_id}/access-rules",
            json={
                "scope_type": "building",
                "scope_id": home["building"],
                "subject_type": "role",
                "subject": "guest",
                "level": "hidden",
            },
        ),
        201,
    )
    guest = member_client(app, admin, property_id, "guest", "guest@example.com")
    assert guest.get(f"{API}/canvases/{plan['id']}").status_code == 404
    assert guest.get(plan["image_url"]).status_code == 404
    assert ok(guest.get(f"{API}/canvases"))["items"] == []


def test_non_member_gets_404(app: FastAPI, plan: dict[str, Any]) -> None:
    stranger = Client(app)
    assert stranger.get(f"{API}/canvases/{plan['id']}").status_code == 401


def test_full_backup_carries_canvases_pins_and_images(
    admin: Client,
    home: dict[str, str],
    plan: dict[str, Any],
    engine: Any,
    settings: Settings,
    tmp_path: Path,
) -> None:
    from domus.backup.archive import create_backup

    ok(pin(admin, plan["id"], home["light"]), 201)
    result = create_backup(engine, tmp_path / "b.zip", blobs_dir=settings.blobs_dir)
    assert result.missing_blobs == []
    assert result.manifest.row_counts["canvas"] == 1
    assert result.manifest.row_counts["placement"] == 1
