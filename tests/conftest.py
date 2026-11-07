"""Shared fixtures. Tests never use the network (AGENTS.md).

Set ``DOMUS_TEST_DATABASE_URL`` to a PostgreSQL URL (for example
``postgresql+pg8000://domus:domus@localhost/domus``) to run the suite against
Postgres instead of SQLite. Each test then gets a fresh database, created and
dropped through that URL, so the account needs the CREATEDB privilege.
"""

import os
import secrets
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI
from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from tests.asgi_client import Client
from tests.fake_ha import FakeHa, running_fake_ha

from domus.api.app import create_app
from domus.config import Settings
from domus.db import make_engine, make_session_factory
from domus.migrate import upgrade

SAMPLE_HOME = Path(__file__).resolve().parents[1] / "examples" / "sample-home"


@pytest.fixture
def sample_home() -> Path:
    """The unzipped sample dataset (read-only; copy it before changing anything)."""
    return SAMPLE_HOME


TEST_DATABASE_URL = os.environ.get("DOMUS_TEST_DATABASE_URL")


def on_postgres() -> bool:
    return bool(TEST_DATABASE_URL) and make_url(TEST_DATABASE_URL or "").get_backend_name() == (
        "postgresql"
    )


requires_sqlite = pytest.mark.skipif(on_postgres(), reason="SQLite-only behavior")
requires_postgres = pytest.mark.skipif(not on_postgres(), reason="needs DOMUS_TEST_DATABASE_URL")


@contextmanager
def postgres_database(url: str) -> Generator[str]:
    """Create an empty database next to ``url``'s; yield its URL; drop it afterwards."""
    base = make_url(url)
    name = f"domus_test_{secrets.token_hex(6)}"
    admin = create_engine(base, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.exec_driver_sql(f'CREATE DATABASE "{name}"')
        try:
            yield base.set(database=name).render_as_string(hide_password=False)
        finally:
            with admin.connect() as conn:
                conn.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    finally:
        admin.dispose()


@pytest.fixture
def database_url(tmp_path: Path) -> Generator[str]:
    """An empty database: SQLite in a temp directory, or a new Postgres database."""
    if on_postgres():
        with postgres_database(TEST_DATABASE_URL or "") as url:
            yield url
    else:
        yield f"sqlite:///{tmp_path / 'test.sqlite'}"


@pytest.fixture
def engine(database_url: str) -> Generator[Engine]:
    """A fresh, fully migrated database."""
    eng = make_engine(database_url)
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


# --- Home Assistant -----------------------------------------------------------


@pytest.fixture
def fake_ha() -> Generator[FakeHa]:
    """A fake Home Assistant WebSocket API on 127.0.0.1 (no outside network)."""
    with running_fake_ha() as ha:
        yield ha
