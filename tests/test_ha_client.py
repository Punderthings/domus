"""The Home Assistant WebSocket client, against the fake HA server."""

import socket
from contextlib import nullcontext
from typing import Any

import pytest
from tests.fake_ha import TOKEN, FakeHa

from domus.homeassistant.client import (
    HaAuthError,
    HaConnectionError,
    HaProtocolError,
    fetch_registries,
    websocket_url,
)


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("http://homeassistant.local:8123", "ws://homeassistant.local:8123/api/websocket"),
        ("https://ha.example.com/", "wss://ha.example.com/api/websocket"),
        ("  HTTP://10.0.0.5:8123  ", "ws://10.0.0.5:8123/api/websocket"),
        ("wss://ha.example.com/api/websocket", "wss://ha.example.com/api/websocket"),
        ("https://example.com/ha", "wss://example.com/ha/api/websocket"),
        ("http://[fd00::1]:8123", "ws://[fd00::1]:8123/api/websocket"),
    ],
)
def test_websocket_url(given: str, expected: str) -> None:
    assert websocket_url(given) == expected


@pytest.mark.parametrize(
    "bad",
    [
        "ftp://ha.local",
        "file:///etc/passwd",
        "homeassistant.local:8123",
        "http://",
        "http://user:pw@ha.local",
        "http://ha.local/?x=1",
        "http://ha.local/#frag",
        "http://ha.local:99999",
    ],
)
def test_websocket_url_refuses(bad: str) -> None:
    with pytest.raises(HaConnectionError):
        websocket_url(bad)


def test_fetch_reads_every_registry(fake_ha: FakeHa) -> None:
    reg = fetch_registries(fake_ha.url, TOKEN, timeout=5)
    assert [f.floor_id for f in reg.floors] == ["ground", "upstairs"]
    assert {a.area_id for a in reg.areas} == {"living_room", "kitchen", "bedroom", "garden"}
    assert reg.labels[0].name == "Lights"
    lamp = next(d for d in reg.devices if d.id == "dev_lamp")
    assert lamp.display_name == "Reading Lamp"
    assert lamp.connections == [("zigbee", "00:17:88:01:0A:0B:0C:0D")]
    assert len(reg.entities) == 5
    # The token went only into the auth message.
    assert fake_ha.received[0] == {"type": "auth", "access_token": TOKEN}
    assert [m["type"] for m in fake_ha.received[1:]] == [
        "config/floor_registry/list",
        "config/area_registry/list",
        "config/label_registry/list",
        "config/device_registry/list",
        "config/entity_registry/list",
    ]
    # Command ids are unique and increasing, as HA requires.
    ids = [m["id"] for m in fake_ha.received[1:]]
    assert ids == sorted(set(ids))


def test_bad_token(fake_ha: FakeHa) -> None:
    with pytest.raises(HaAuthError, match="rejected"):
        fetch_registries(fake_ha.url, "wrong", timeout=5)


def test_blank_token_never_connects(fake_ha: FakeHa) -> None:
    with pytest.raises(HaAuthError):
        fetch_registries(fake_ha.url, "   ", timeout=5)
    assert fake_ha.connections == 0


def test_non_admin_user(fake_ha: FakeHa) -> None:
    fake_ha.unauthorized = True
    with pytest.raises(HaAuthError, match="admin"):
        fetch_registries(fake_ha.url, TOKEN, timeout=5)


def test_not_home_assistant(fake_ha: FakeHa) -> None:
    fake_ha.not_home_assistant = True
    with pytest.raises(HaProtocolError, match="does not look like"):
        fetch_registries(fake_ha.url, TOKEN, timeout=5)


def test_bad_registry_data(fake_ha: FakeHa) -> None:
    fake_ha.registries["devices"].append({"name": "no id"})
    with pytest.raises(HaProtocolError, match="can't read"):
        fetch_registries(fake_ha.url, TOKEN, timeout=5)


def test_long_strings_are_cut_not_rejected(fake_ha: FakeHa) -> None:
    fake_ha.device("dev_fridge")["name"] = "F" * 5000
    reg = fetch_registries(fake_ha.url, TOKEN, timeout=5)
    fridge = next(d for d in reg.devices if d.id == "dev_fridge")
    assert len(fridge.display_name) == 200


def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_nothing_listening() -> None:
    with pytest.raises(HaConnectionError, match="Could not connect"):
        fetch_registries(f"http://127.0.0.1:{_closed_port()}", TOKEN, timeout=2)


class _Silent:
    """A connection that never answers."""

    def send(self, message: str) -> None:
        pass

    def recv(self, timeout: float | None = None) -> str:
        raise TimeoutError


class _Scripted:
    def __init__(self, replies: list[Any]) -> None:
        self.replies = replies

    def send(self, message: str) -> None:
        pass

    def recv(self, timeout: float | None = None) -> str:
        return self.replies.pop(0)


def test_timeout_is_a_connection_error() -> None:
    with pytest.raises(HaConnectionError, match="in time"):
        fetch_registries(
            "http://ha.invalid", TOKEN, connector=lambda url, t: nullcontext(_Silent())
        )


def test_garbage_message() -> None:
    conn = _Scripted(["not json"])
    with pytest.raises(HaProtocolError, match="not JSON"):
        fetch_registries("http://ha.invalid", TOKEN, connector=lambda url, t: nullcontext(conn))


def test_non_object_message() -> None:
    conn = _Scripted(["[1, 2]"])
    with pytest.raises(HaProtocolError):
        fetch_registries("http://ha.invalid", TOKEN, connector=lambda url, t: nullcontext(conn))


def test_unknown_command_failure() -> None:
    conn = _Scripted(
        [
            '{"type": "auth_required"}',
            '{"type": "auth_ok"}',
            '{"id": 1, "type": "result", "success": false, "error": {"code": "unknown_command"}}',
        ]
    )
    with pytest.raises(HaProtocolError, match="refused"):
        fetch_registries("http://ha.invalid", TOKEN, connector=lambda url, t: nullcontext(conn))


def test_result_not_a_list() -> None:
    conn = _Scripted(
        [
            '{"type": "auth_required"}',
            '{"type": "auth_ok"}',
            '{"id": 1, "type": "result", "success": true, "result": {}}',
        ]
    )
    with pytest.raises(HaProtocolError, match="Unexpected"):
        fetch_registries("http://ha.invalid", TOKEN, connector=lambda url, t: nullcontext(conn))


def test_auth_neither_ok_nor_invalid() -> None:
    conn = _Scripted(['{"type": "auth_required"}', '{"type": "something"}'])
    with pytest.raises(HaProtocolError, match="authentication"):
        fetch_registries("http://ha.invalid", TOKEN, connector=lambda url, t: nullcontext(conn))
