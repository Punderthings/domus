"""A small, synchronous Home Assistant WebSocket API client.

Only the read-only registry commands the import needs are sent. The token is
used for this one connection and is never logged, stored, or put in an error
message. See https://developers.home-assistant.io/docs/api/websocket/.
"""

import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any, Protocol, cast
from urllib.parse import urlsplit, urlunsplit

from pydantic import ValidationError
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidURI
from websockets.sync.client import connect as ws_connect

from domus.homeassistant.registry import HaRegistries

# Registries can be large on a big install; this caps one message, not the total.
MAX_MESSAGE_BYTES = 32 * 1024 * 1024
DEFAULT_TIMEOUT = 15.0

# Field name in HaRegistries -> HA WebSocket command.
REGISTRY_COMMANDS: dict[str, str] = {
    "floors": "config/floor_registry/list",
    "areas": "config/area_registry/list",
    "labels": "config/label_registry/list",
    "devices": "config/device_registry/list",
    "entities": "config/entity_registry/list",
}


class HaError(Exception):
    """A Home Assistant problem with a message that is safe to show the user."""


class HaConnectionError(HaError):
    pass


class HaAuthError(HaError):
    pass


class HaProtocolError(HaError):
    pass


class Connection(Protocol):
    """The part of ``websockets.sync.client.ClientConnection`` this module uses."""

    def send(self, message: str) -> None: ...
    def recv(self, timeout: float | None = None) -> str | bytes: ...


Connector = Callable[[str, float], AbstractContextManager[Connection]]


def _default_connector(url: str, timeout: float) -> AbstractContextManager[Connection]:
    return ws_connect(
        url,
        open_timeout=timeout,
        close_timeout=timeout,
        max_size=MAX_MESSAGE_BYTES,
        # HA is normally on the local network; don't route it through HTTP(S)_PROXY.
        proxy=None,
        user_agent_header="Domus",
    )


def websocket_url(base_url: str) -> str:
    """Turn the HA address a user types into its WebSocket API URL.

    Accepts ``http(s)://host:port`` (what HA shows) or ``ws(s)://``; refuses
    credentials, queries, and other schemes.
    """
    try:
        parts = urlsplit(base_url.strip())
        _ = parts.port  # raises ValueError on a bad port
    except ValueError as exc:
        raise HaConnectionError("The Home Assistant address is not a valid URL") from exc
    scheme = {"http": "ws", "https": "wss", "ws": "ws", "wss": "wss"}.get(parts.scheme.lower())
    if scheme is None or not parts.hostname:
        raise HaConnectionError("Use an http:// or https:// Home Assistant address")
    if parts.username is not None or parts.password is not None:
        raise HaConnectionError("Don't put a user name or password in the address")
    if parts.query or parts.fragment:
        raise HaConnectionError("The Home Assistant address can't have a query or fragment")
    path = parts.path.rstrip("/")
    if not path.endswith("/api/websocket"):
        path = f"{path}/api/websocket"
    return urlunsplit((scheme, parts.netloc, path, "", ""))


def _recv_json(conn: Connection, timeout: float) -> dict[str, Any]:
    raw = conn.recv(timeout=timeout)
    try:
        msg = json.loads(raw)
    except ValueError as exc:
        raise HaProtocolError("Home Assistant sent a message that is not JSON") from exc
    if not isinstance(msg, dict):
        raise HaProtocolError("Home Assistant sent an unexpected message")
    return cast(dict[str, Any], msg)


def _authenticate(conn: Connection, token: str, timeout: float) -> None:
    hello = _recv_json(conn, timeout)
    if hello.get("type") != "auth_required":
        raise HaProtocolError("This address does not look like a Home Assistant server")
    conn.send(json.dumps({"type": "auth", "access_token": token}))
    reply = _recv_json(conn, timeout)
    if reply.get("type") == "auth_invalid":
        raise HaAuthError("Home Assistant rejected the access token")
    if reply.get("type") != "auth_ok":
        raise HaProtocolError("Home Assistant did not finish authentication")


def _command(conn: Connection, msg_id: int, command: str, timeout: float) -> list[Any]:
    conn.send(json.dumps({"id": msg_id, "type": command}))
    while True:
        msg = _recv_json(conn, timeout)
        if msg.get("id") != msg_id or msg.get("type") != "result":
            continue  # events or pings for something else
        if not msg.get("success"):
            error = msg.get("error")
            code = cast(dict[str, Any], error).get("code") if isinstance(error, dict) else None
            if code == "unauthorized":
                raise HaAuthError(
                    "This Home Assistant user can't read the registries (use an admin)"
                )
            raise HaProtocolError(f"Home Assistant refused {command!r}")
        result = msg.get("result")
        if not isinstance(result, list):
            raise HaProtocolError(f"Unexpected reply to {command!r}")
        return cast(list[Any], result)


def fetch_registries(
    base_url: str,
    token: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    connector: Connector = _default_connector,
) -> HaRegistries:
    """Connect, authenticate, and read the floor, area, label, device, and entity registries."""
    url = websocket_url(base_url)
    if not token.strip():
        raise HaAuthError("An access token is required")
    try:
        with connector(url, timeout) as conn:
            _authenticate(conn, token, timeout)
            data: dict[str, list[Any]] = {}
            for msg_id, (name, command) in enumerate(REGISTRY_COMMANDS.items(), start=1):
                data[name] = _command(conn, msg_id, command, timeout)
        return HaRegistries.model_validate(data)
    except ValidationError as exc:
        raise HaProtocolError("Home Assistant sent registry data Domus can't read") from exc
    except InvalidURI as exc:
        raise HaConnectionError("The Home Assistant address is not a valid URL") from exc
    except InvalidHandshake as exc:
        raise HaConnectionError(
            "That address answered, but not as a Home Assistant WebSocket API"
        ) from exc
    except ConnectionClosed as exc:
        raise HaConnectionError("Home Assistant closed the connection") from exc
    except TimeoutError as exc:
        raise HaConnectionError("Home Assistant did not answer in time") from exc
    except OSError as exc:
        raise HaConnectionError("Could not connect to Home Assistant at that address") from exc
