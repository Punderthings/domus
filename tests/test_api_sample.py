"""Loading the sample home from the web interface (POST /api/v1/sample-data)."""

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session
from tests.asgi_client import Client
from tests.conftest import PASSWORD, member_client

from domus.api.app import create_app
from domus.config import Settings
from domus.models import Asset, AuditLog, Membership, Property
from domus.services.sample import (
    CHECKOUT_DIR,
    SampleDataError,
    load_sample,
    sample_dir,
    sample_property_id,
)

URL = "/api/v1/sample-data"
SAMPLE_ID = "01a1a901-5800-7001-8000-000000000001"


def _setup(client: Client, email: str = "admin@example.com") -> Client:
    r = client.post(
        "/api/v1/auth/setup",
        json={
            "email": email,
            "display_name": "Admin",
            "password": PASSWORD,
            "property_name": "Test Home",
        },
    )
    assert r.status_code == 201, r.text
    return client


def _property_ids(client: Client) -> set[str]:
    return {m["property_id"] for m in client.get("/api/v1/auth/me").json()["memberships"]}


def test_checkout_dataset_is_found(settings: Settings, sample_home: Path) -> None:
    assert sample_home == CHECKOUT_DIR
    assert sample_dir(settings) == sample_home
    assert sample_property_id(sample_home) == SAMPLE_ID


def test_status_before_loading(admin: Client) -> None:
    r = admin.get(URL)
    assert r.status_code == 200
    assert r.json() == {"available": True, "loaded": False, "property_id": SAMPLE_ID}


def test_admin_loads_sample_as_second_property(
    admin: Client, property_id: str, engine: Engine, sample_home: Path
) -> None:
    r = admin.post(URL)
    assert r.status_code == 201, r.text
    assert r.json() == {"available": True, "loaded": True, "property_id": SAMPLE_ID}

    assert _property_ids(admin) == {property_id, SAMPLE_ID}
    names = {p["name"] for p in admin.get("/api/v1/properties").json()["items"]}
    assert names == {"Test Home", "Sample Home"}
    assets = admin.get("/api/v1/assets", params={"property_id": SAMPLE_ID}).json()["items"]
    manifest = json.loads((sample_home / "manifest.json").read_text())
    assert len(assets) == manifest["row_counts"]["asset"]
    # The Admin's own property is untouched.
    assert admin.get("/api/v1/assets", params={"property_id": property_id}).json()["items"] == []

    with Session(engine) as s:
        m = s.scalar(select(Membership).where(Membership.property_id == SAMPLE_ID))
        assert m is not None and m.role == "admin"
        log = s.scalar(select(AuditLog).where(AuditLog.action == "load_sample"))
        assert log is not None and log.property_id == SAMPLE_ID

    assert admin.get(URL).json()["loaded"] is True


def test_loading_twice_is_refused(admin: Client, engine: Engine) -> None:
    assert admin.post(URL).status_code == 201
    r = admin.post(URL)
    assert r.status_code == 409
    with Session(engine) as s:
        count = s.scalar(
            select(func.count()).select_from(Membership).where(Membership.property_id == SAMPLE_ID)
        )
    assert count == 1


def test_another_admin_cannot_claim_a_loaded_sample(
    admin: Client, app: FastAPI, property_id: str
) -> None:
    assert admin.post(URL).status_code == 201
    # A second Admin of the first property, who isn't a member of Sample Home.
    other = member_client(app, admin, property_id, "admin", "other@example.com")
    assert other.get(URL).json()["loaded"] is True
    assert other.post(URL).status_code == 409
    assert SAMPLE_ID not in _property_ids(other)


@pytest.mark.parametrize("role", ["maintainer", "resident", "guest"])
def test_non_admins_are_refused(admin: Client, app: FastAPI, property_id: str, role: str) -> None:
    member = member_client(app, admin, property_id, role, f"{role}@example.com")
    assert member.get(URL).status_code == 403
    assert member.post(URL).status_code == 403
    assert admin.get(URL).json()["loaded"] is False


def test_requires_sign_in(client: Client) -> None:
    assert client.get(URL).status_code == 401
    assert client.post(URL).status_code == 401


def test_post_needs_csrf_token(admin: Client) -> None:
    admin.send_csrf = False
    assert admin.post(URL).status_code == 403
    admin.send_csrf = True
    assert admin.get(URL).json()["loaded"] is False


def test_unclaimed_sample_can_be_claimed(
    admin: Client, engine: Engine, settings: Settings, sample_home: Path
) -> None:
    # As after `domus restore examples/sample-home --merge` on an install with an Admin.
    load_sample(engine, sample_home, settings)
    assert admin.get(URL).json()["loaded"] is False
    r = admin.post(URL)
    assert r.status_code == 201, r.text
    assert SAMPLE_ID in _property_ids(admin)


def test_deleted_sample_is_not_revived(admin: Client, engine: Engine) -> None:
    assert admin.post(URL).status_code == 201
    with Session(engine) as s:
        prop = s.get(Property, SAMPLE_ID)
        assert prop is not None
        prop.deleted_at = datetime.now(UTC)
        s.execute(delete(Membership).where(Membership.property_id == SAMPLE_ID))
        s.commit()
    assert admin.get(URL).json()["loaded"] is True
    assert admin.post(URL).status_code == 409


def test_install_without_dataset(engine: Engine, tmp_path: Path) -> None:
    empty = tmp_path / "no-sample"
    empty.mkdir()
    settings = Settings(data_dir=tmp_path / "data", cookie_secure=False, sample_data_dir=empty)
    client = _setup(Client(create_app(settings, engine)))
    assert client.get(URL).json() == {"available": False, "loaded": False, "property_id": None}
    r = client.post(URL)
    assert r.status_code == 404
    with Session(engine) as s:
        assert s.scalar(select(func.count()).select_from(Asset)) == 0


def test_configured_dataset_dir_is_used(engine: Engine, tmp_path: Path, sample_home: Path) -> None:
    copy = tmp_path / "sample-copy"
    shutil.copytree(sample_home, copy)
    settings = Settings(data_dir=tmp_path / "data", cookie_secure=False, sample_data_dir=copy)
    assert sample_dir(settings) == copy
    client = _setup(Client(create_app(settings, engine)))
    assert client.post(URL).status_code == 201


def test_dataset_with_two_properties_is_rejected(tmp_path: Path, sample_home: Path) -> None:
    copy = tmp_path / "sample-copy"
    shutil.copytree(sample_home, copy)
    manifest = json.loads((copy / "manifest.json").read_text())
    manifest["property_ids"].append("01a1a901-5800-7001-8000-0000000000ff")
    (copy / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(SampleDataError, match="exactly one property"):
        sample_property_id(copy)


def test_broken_dataset_is_a_server_error(
    engine: Engine, tmp_path: Path, sample_home: Path
) -> None:
    copy = tmp_path / "sample-copy"
    shutil.copytree(sample_home, copy)
    (copy / "data" / "asset.jsonl").write_text("{not json\n")
    settings = Settings(data_dir=tmp_path / "data", cookie_secure=False, sample_data_dir=copy)
    client = _setup(Client(create_app(settings, engine)))
    r = client.post(URL)
    assert r.status_code == 500
    assert "sample dataset" in r.json()["detail"]
    with Session(engine) as s:
        assert s.get(Property, SAMPLE_ID) is None
