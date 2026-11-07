"""Backups from the web UI: only an Admin of every property may make or fetch them."""

import io
import os
import zipfile

from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session
from tests.asgi_client import Client
from tests.conftest import member_client

from domus.config import Settings
from domus.models import AuditLog, Membership, Property, User


def test_admin_makes_lists_and_downloads_a_backup(admin: Client, settings: Settings) -> None:
    assert admin.get("/api/v1/backups").json() == {"items": [], "next_cursor": None}

    r = admin.post("/api/v1/backups")
    assert r.status_code == 201, r.text
    made = r.json()
    assert made["name"].startswith("domus-")
    assert made["name"].endswith(".hiotbak")
    assert made["size_bytes"] > 0
    assert made["missing_files"] == 0
    assert (settings.backups_dir / made["name"]).is_file()

    listed = admin.get("/api/v1/backups").json()["items"]
    assert [b["name"] for b in listed] == [made["name"]]
    assert listed[0]["missing_files"] is None

    r = admin.get(f"/api/v1/backups/{made['name']}")
    assert r.status_code == 200
    assert r.header("content-type") == "application/zip"
    assert r.header("cache-control") == "no-store"
    assert made["name"] in (r.header("content-disposition") or "")
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        assert "manifest.json" in zf.namelist()


def test_backup_actions_are_audited(admin: Client, session: Session) -> None:
    name = admin.post("/api/v1/backups").json()["name"]
    admin.get(f"/api/v1/backups/{name}")
    rows = session.scalars(select(AuditLog).where(AuditLog.target_type == "backup")).all()
    assert sorted(r.action for r in rows) == ["create", "download"]
    assert {r.target_id for r in rows} == {name}


def test_list_skips_other_files_and_sorts_newest_first(admin: Client, settings: Settings) -> None:
    settings.backups_dir.mkdir(parents=True)
    old = settings.backups_dir / "domus-pre-restore-20260101T000000Z.hiotbak"
    old.write_bytes(b"x")
    (settings.backups_dir / "domus-pre-restore-20260101T000000Z.sqlite").write_bytes(b"x")
    (settings.backups_dir / ".domus-x.hiotbak.abcd.partial").write_bytes(b"x")
    new = admin.post("/api/v1/backups").json()["name"]
    os.utime(old, (1_700_000_000, 1_700_000_000))
    names = [b["name"] for b in admin.get("/api/v1/backups").json()["items"]]
    assert names == [new, old.name]


def test_download_refuses_unknown_and_unsafe_names(admin: Client, settings: Settings) -> None:
    settings.backups_dir.mkdir(parents=True)
    (settings.data_dir / "secret.hiotbak").write_bytes(b"x")
    for name in [
        "missing.hiotbak",
        "..%2Fsecret.hiotbak",
        "domus.sqlite",
        ".hidden.hiotbak",
    ]:
        assert admin.get(f"/api/v1/backups/{name}").status_code == 404, name


def test_non_admins_cannot_use_backups(app: FastAPI, admin: Client, property_id: str) -> None:
    name = admin.post("/api/v1/backups").json()["name"]
    maint = member_client(app, admin, property_id, "maintainer", "m@example.com")
    for r in [
        maint.get("/api/v1/backups"),
        maint.post("/api/v1/backups"),
        maint.get(f"/api/v1/backups/{name}"),
    ]:
        assert r.status_code == 403
    assert Client(app).get("/api/v1/backups").status_code == 401


def test_admin_of_only_some_properties_is_refused(
    admin: Client, session: Session, property_id: str
) -> None:
    """A backup holds every property, so an Admin of one must not download another's data."""
    other = Property(name="Neighbor's house")
    session.add(other)
    session.commit()
    assert admin.get("/api/v1/backups").status_code == 403

    user = session.scalars(select(User)).one()
    session.add(Membership(user_id=user.id, property_id=other.id, role="admin"))
    session.commit()
    assert admin.get("/api/v1/backups").status_code == 200


def test_making_a_backup_needs_the_csrf_header(admin: Client) -> None:
    admin.send_csrf = False
    assert admin.post("/api/v1/backups").status_code == 403
