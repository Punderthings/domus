"""Serving the built front end from the backend (domus.api.spa)."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from tests.asgi_client import Client

from domus.api.spa import CONTENT_SECURITY_POLICY, mount_spa, resolve_static

INDEX = "<!doctype html><title>Domus</title>"


@pytest.fixture
def static_dir(tmp_path: Path) -> Path:
    root = tmp_path / "static"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text(INDEX)
    (root / "assets" / "index-abc123.js").write_text("console.log(1)")
    (root / "favicon.svg").write_text("<svg/>")
    (tmp_path / "secret.txt").write_text("do not serve")
    return root


@pytest.fixture
def spa_client(static_dir: Path) -> Client:
    app = FastAPI()

    @app.get("/api/v1/ping")
    def ping() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {"pong": "yes"}

    assert mount_spa(app, static_dir)
    return Client(app)


def test_root_and_app_routes_serve_index(spa_client: Client) -> None:
    for path in ("/", "/devices", "/devices/01a1a901-5800-7012-8000-000000000012", "/login"):
        resp = spa_client.get(path)
        assert resp.status_code == 200, path
        assert resp.text == INDEX
        assert resp.header("cache-control") == "no-cache"
        assert "text/html" in (resp.header("content-type") or "")


def test_hashed_assets_are_cached_and_other_files_are_not(spa_client: Client) -> None:
    asset = spa_client.get("/assets/index-abc123.js")
    assert asset.status_code == 200
    assert asset.text == "console.log(1)"
    assert asset.header("cache-control") == "public, max-age=31536000, immutable"
    icon = spa_client.get("/favicon.svg")
    assert icon.text == "<svg/>"
    assert icon.header("cache-control") == "no-cache"


def test_security_headers(spa_client: Client) -> None:
    resp = spa_client.get("/")
    assert resp.header("content-security-policy") == CONTENT_SECURITY_POLICY
    assert "script-src 'self'" in CONTENT_SECURITY_POLICY
    assert "frame-ancestors 'none'" in CONTENT_SECURITY_POLICY
    assert resp.header("x-content-type-options") == "nosniff"


def test_api_routes_win_and_unknown_api_paths_stay_json_404(spa_client: Client) -> None:
    assert spa_client.get("/api/v1/ping").json() == {"pong": "yes"}
    missing = spa_client.get("/api/v1/nope")
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Not Found"}
    assert spa_client.get("/calendar.ics").status_code == 404


def test_path_traversal_is_refused(spa_client: Client, static_dir: Path) -> None:
    for path in ("/../secret.txt", "/assets/../../secret.txt", "/%2e%2e/secret.txt"):
        resp = spa_client.get(path)
        assert "do not serve" not in resp.text, path
    assert resolve_static(static_dir, "../secret.txt") is None
    assert resolve_static(static_dir, "/etc/passwd") is None
    assert resolve_static(static_dir, "assets") is None  # a directory, not a file
    assert resolve_static(static_dir, "favicon.svg") == (static_dir / "favicon.svg").resolve()


def test_nothing_is_mounted_without_a_build(tmp_path: Path) -> None:
    app = FastAPI()
    assert not mount_spa(app, tmp_path / "missing")
    assert Client(app).get("/").status_code == 404


def test_create_app_keeps_api_404s_as_json(client: Client) -> None:
    resp = client.get("/api/v1/does-not-exist")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Not Found"}


def test_head_requests_work(spa_client: Client) -> None:
    resp = spa_client.request("HEAD", "/devices")
    assert resp.status_code == 200
    assert resp.header("content-security-policy") == CONTENT_SECURITY_POLICY
