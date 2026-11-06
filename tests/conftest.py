"""Shared fixtures. Tests never use the network (AGENTS.md)."""

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi import FastAPI
from sqlalchemy import Engine
from sqlalchemy.orm import Session
from tests.asgi_client import Client

from domus.api.app import create_app
from domus.config import Settings
from domus.db import make_engine, make_session_factory
from domus.migrate import upgrade

SAMPLE_HOME = Path(__file__).resolve().parents[1] / "examples" / "sample-home"


@pytest.fixture
def sample_home() -> Path:
    """The unzipped sample dataset (read-only; copy it before changing anything)."""
    return SAMPLE_HOME


@pytest.fixture
def engine(tmp_path: Path) -> Generator[Engine]:
    """A fresh, fully migrated SQLite database in a temp directory."""
    eng = make_engine(f"sqlite:///{tmp_path / 'test.sqlite'}")
    upgrade(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine: Engine) -> Generator[Session]:
    factory = make_session_factory(engine)
    with factory() as s:
        yield s


# --- API fixtures -------------------------------------------------------------

ADMIN_EMAIL = "admin@example.com"
PASSWORD = "correct horse battery"  # noqa: S105 - test fixture


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data", cookie_secure=False)


@pytest.fixture
def app(settings: Settings, engine: Engine) -> FastAPI:
    return create_app(settings, engine)


@pytest.fixture
def client(app: FastAPI) -> Client:
    return Client(app)


@pytest.fixture
def admin(client: Client) -> Client:
    """A client logged in as the first Admin of a fresh property."""
    r = client.post(
        "/api/v1/auth/setup",
        json={
            "email": ADMIN_EMAIL,
            "display_name": "Admin",
            "password": PASSWORD,
            "property_name": "Test Home",
            "timezone": "America/New_York",
        },
    )
    assert r.status_code == 201, r.text
    return client


@pytest.fixture
def property_id(admin: Client) -> str:
    return admin.get("/api/v1/auth/me").json()["memberships"][0]["property_id"]


def member_client(app: FastAPI, admin: Client, property_id: str, role: str, email: str) -> Client:
    """Add a member with ``role`` and return a client logged in as them."""
    r = admin.post(
        f"/api/v1/properties/{property_id}/members",
        json={"email": email, "display_name": role.title(), "password": PASSWORD, "role": role},
    )
    assert r.status_code == 201, r.text
    c = Client(app)
    r = c.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    c.membership_id = r.json()["memberships"][0]["id"]
    return c
