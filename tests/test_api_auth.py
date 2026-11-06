"""Setup, login, sessions, CSRF, and personal access tokens."""

from pathlib import Path

from fastapi import FastAPI
from sqlalchemy import Engine
from tests.asgi_client import Client
from tests.conftest import ADMIN_EMAIL, PASSWORD

from domus.backup import import_source, open_source


def test_health(client: Client) -> None:
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_openapi_is_served(client: Client) -> None:
    r = client.get("/api/v1/openapi.json")
    assert r.status_code == 200
    assert "/api/v1/assets" in r.json()["paths"]


def test_first_run_setup_flow(client: Client) -> None:
    assert client.get("/api/v1/auth/setup").json() == {"needs_setup": True}
    assert client.get("/api/v1/auth/me").status_code == 401
    r = client.post(
        "/api/v1/auth/setup",
        json={
            "email": "Owner@Example.com",
            "display_name": "Owner",
            "password": PASSWORD,
            "property_name": "My Home",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email"] == "owner@example.com"
    assert [m["role"] for m in body["memberships"]] == ["admin"]
    assert "domus_session" in client.cookies
    assert "domus_csrf" in client.cookies
    session_cookie = next(c for c in r.headers_all("set-cookie") if c.startswith("domus_session"))
    assert "HttpOnly" in session_cookie
    assert "SameSite=lax" in session_cookie
    csrf_cookie = next(c for c in r.headers_all("set-cookie") if c.startswith("domus_csrf"))
    assert "HttpOnly" not in csrf_cookie

    assert client.get("/api/v1/auth/setup").json() == {"needs_setup": False}
    me = client.get("/api/v1/auth/me").json()
    assert me["display_name"] == "Owner"

    # The primary building was created with the property.
    buildings = client.get("/api/v1/buildings").json()["items"]
    assert [(b["name"], b["is_primary"]) for b in buildings] == [("House", True)]


def test_setup_only_once(admin: Client, app: FastAPI) -> None:
    r = Client(app).post(
        "/api/v1/auth/setup",
        json={
            "email": "evil@example.com",
            "display_name": "X",
            "password": PASSWORD,
            "property_name": "Y",
        },
    )
    assert r.status_code == 409


def test_setup_rejects_short_password(client: Client) -> None:
    r = client.post(
        "/api/v1/auth/setup",
        json={"email": "a@b.c", "display_name": "A", "password": "short", "property_name": "P"},
    )
    assert r.status_code == 422


def test_login_logout(admin: Client, app: FastAPI) -> None:
    c = Client(app)
    r = c.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL.upper(), "password": PASSWORD})
    assert r.status_code == 200
    assert c.get("/api/v1/auth/me").status_code == 200
    assert c.post("/api/v1/auth/logout").status_code == 204
    assert "domus_session" not in c.cookies
    assert c.get("/api/v1/auth/me").status_code == 401


def test_logout_invalidates_server_session(admin: Client, app: FastAPI) -> None:
    stolen = dict(admin.cookies)
    assert admin.post("/api/v1/auth/logout").status_code == 204
    replay = Client(app, cookies=stolen)
    assert replay.get("/api/v1/auth/me").status_code == 401


def test_wrong_password_and_unknown_user_look_the_same(admin: Client, app: FastAPI) -> None:
    c = Client(app)
    a = c.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong password!"})
    b = c.post("/api/v1/auth/login", json={"email": "nobody@x.y", "password": "wrong password!"})
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


def test_login_rate_limit(admin: Client, app: FastAPI) -> None:
    c = Client(app)
    for _ in range(5):
        r = c.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": "nope nope nope"})
        assert r.status_code == 401
    r = c.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": PASSWORD})
    assert r.status_code == 429


def test_unsafe_request_needs_csrf_header(admin: Client, property_id: str) -> None:
    admin.send_csrf = False
    body = {"property_id": property_id, "name": "smart"}
    assert admin.post("/api/v1/tags", json=body).status_code == 403
    r = admin.post("/api/v1/tags", json=body, headers={"x-csrf-token": "forged"})
    assert r.status_code == 403
    admin.send_csrf = True
    assert admin.post("/api/v1/tags", json=body).status_code == 201


def test_personal_access_tokens(admin: Client, app: FastAPI, property_id: str) -> None:
    r = admin.post("/api/v1/auth/tokens", json={"name": "ro"})
    assert r.status_code == 201
    ro = r.json()["token"]
    assert ro.startswith("domus_pat_")
    r = admin.post("/api/v1/auth/tokens", json={"name": "rw", "scopes": ["read", "write"]})
    rw = r.json()["token"]

    bearer = Client(app)
    auth = {"authorization": f"Bearer {ro}"}
    assert bearer.get("/api/v1/auth/me", headers=auth).status_code == 200
    tag = {"property_id": property_id, "name": "t"}
    assert bearer.post("/api/v1/tags", json=tag, headers=auth).status_code == 403
    # Bearer tokens need no CSRF header.
    r = bearer.post("/api/v1/tags", json=tag, headers={"authorization": f"Bearer {rw}"})
    assert r.status_code == 201
    # Tokens can't mint more tokens.
    r = bearer.post("/api/v1/auth/tokens", json={"name": "x"}, headers=auth)
    assert r.status_code == 403

    tokens = admin.get("/api/v1/auth/tokens").json()
    assert {t["name"] for t in tokens} == {"ro", "rw"}
    assert all("token" not in t for t in tokens)
    ro_id = next(t["id"] for t in tokens if t["name"] == "ro")
    assert admin.delete(f"/api/v1/auth/tokens/{ro_id}").status_code == 204
    assert bearer.get("/api/v1/auth/me", headers=auth).status_code == 401


def test_bad_bearer_token(client: Client) -> None:
    r = client.get("/api/v1/auth/me", headers={"authorization": "Bearer domus_pat_nope"})
    assert r.status_code == 401


def test_setup_after_sample_import_adopts_imported_property(
    client: Client, engine: Engine, sample_home: Path
) -> None:
    """Load the sample home first, then run setup: the Admin can see it."""
    import_source(engine, open_source(sample_home))
    r = client.post(
        "/api/v1/auth/setup",
        json={
            "email": "o@example.com",
            "display_name": "O",
            "password": PASSWORD,
            "property_name": "unused",
        },
    )
    assert r.status_code == 201, r.text
    props = client.get("/api/v1/properties").json()["items"]
    assert [p["name"] for p in props] == ["Sample Home"]
    assets = client.get("/api/v1/assets").json()["items"]
    assert len(assets) == 9
