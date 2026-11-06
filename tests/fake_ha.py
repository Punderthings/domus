"""A fake Home Assistant WebSocket API server for tests.

It listens on 127.0.0.1 on a free port, in a background thread, and speaks
just enough of the HA protocol (auth, then ``config/*_registry/list``) for the
import. Nothing leaves the machine. Tests change ``FakeHa.registries`` or the
behavior flags to shape what the "Home Assistant" returns.
"""

import copy
import json
import threading
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from websockets.exceptions import ConnectionClosed
from websockets.sync.server import Server, ServerConnection, serve

TOKEN = "fake-long-lived-token"  # noqa: S105 - test fixture

COMMANDS = {
    "config/floor_registry/list": "floors",
    "config/area_registry/list": "areas",
    "config/label_registry/list": "labels",
    "config/device_registry/list": "devices",
    "config/entity_registry/list": "entities",
}


def sample_registries() -> dict[str, list[dict[str, Any]]]:
    """A small home in Home Assistant's own registry format."""
    return {
        "floors": [
            {"floor_id": "ground", "name": "Ground Floor", "level": 0, "icon": None},
            {"floor_id": "upstairs", "name": "Upstairs", "level": 1},
        ],
        "areas": [
            {"area_id": "living_room", "name": "Living Room", "floor_id": "ground"},
            {"area_id": "kitchen", "name": "Kitchen", "floor_id": "ground"},
            {"area_id": "bedroom", "name": "Bedroom", "floor_id": "upstairs"},
            {"area_id": "garden", "name": "Garden", "floor_id": None},
        ],
        "labels": [{"label_id": "lights", "name": "Lights", "color": "amber"}],
        "devices": [
            {
                "id": "dev_hub",
                "name": "Zigbee Hub",
                "manufacturer": "Acme",
                "model": "Hub 2",
                "model_id": "AH2",
                "serial_number": "HUB-0001",
                "sw_version": "1.0.0",
                "hw_version": "rev A",
                "area_id": "living_room",
                "connections": [["mac", "AA-BB-CC-00-00-01"]],
                "identifiers": [["zha", "hub"]],
                "labels": [],
                "entry_type": None,
                "disabled_by": None,
                "via_device_id": None,
                "config_entries": ["abc"],
            },
            {
                "id": "dev_lamp",
                "name": "Hue color lamp",
                "name_by_user": "Reading Lamp",
                "manufacturer": "Signify",
                "model": "LCA001",
                "serial_number": None,
                "sw_version": "1.104.2",
                "area_id": "living_room",
                "connections": [["zigbee", "00:17:88:01:0A:0B:0C:0D"]],
                "identifiers": [["hue", "lamp-1"]],
                "labels": ["lights"],
                "via_device_id": "dev_hub",
            },
            {
                "id": "dev_fridge",
                "name": "Fridge",
                "manufacturer": "Coolco",
                "model": "CF-500",
                "serial_number": "SN-12345",
                "area_id": "kitchen",
                "connections": [],
                "identifiers": [["coolco", "f1"]],
            },
            {
                "id": "dev_thermostat",
                "name": "Bedroom Thermostat",
                "manufacturer": "Warmly",
                "model": "T9",
                "area_id": "bedroom",
                "connections": [["mac", "aa:bb:cc:00:00:09"]],
            },
            {
                "id": "dev_sun",
                "name": "Sun",
                "entry_type": "service",
                "identifiers": [["sun", "x"]],
            },
        ],
        "entities": [
            {"entity_id": "light.reading_lamp", "device_id": "dev_lamp", "platform": "hue"},
            {"entity_id": "sensor.fridge_temp", "device_id": "dev_fridge", "platform": "coolco"},
            {"entity_id": "climate.bedroom", "device_id": "dev_thermostat", "platform": "warmly"},
            {"entity_id": "sun.sun", "device_id": "dev_sun", "platform": "sun"},
            {"entity_id": "sensor.orphan", "device_id": None},
        ],
    }


@dataclass
class FakeHa:
    url: str
    registries: dict[str, list[dict[str, Any]]] = field(default_factory=sample_registries)
    token: str = TOKEN
    # Answer every registry command with "unauthorized" (a non-admin HA user).
    unauthorized: bool = False
    # Don't send the HA greeting at all (some other WebSocket server).
    not_home_assistant: bool = False
    connections: int = 0
    received: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])

    def handle(self, ws: ServerConnection) -> None:
        self.connections += 1
        try:
            if self.not_home_assistant:
                ws.send(json.dumps({"type": "hello"}))
                ws.recv(timeout=5)
                return
            ws.send(json.dumps({"type": "auth_required", "ha_version": "2026.11.0"}))
            auth = json.loads(ws.recv(timeout=5))
            self.received.append(auth)
            if auth.get("type") != "auth" or auth.get("access_token") != self.token:
                ws.send(json.dumps({"type": "auth_invalid", "message": "Invalid access token"}))
                return
            ws.send(json.dumps({"type": "auth_ok", "ha_version": "2026.11.0"}))
            while True:
                msg = json.loads(ws.recv(timeout=5))
                self.received.append(msg)
                # A stray event first, as a real HA can interleave messages.
                ws.send(json.dumps({"id": 999, "type": "event", "event": {}}))
                key = COMMANDS.get(msg.get("type"))
                if self.unauthorized:
                    reply: dict[str, Any] = {
                        "id": msg["id"],
                        "type": "result",
                        "success": False,
                        "error": {"code": "unauthorized", "message": "Unauthorized"},
                    }
                elif key is None:
                    reply = {
                        "id": msg["id"],
                        "type": "result",
                        "success": False,
                        "error": {"code": "unknown_command", "message": "Unknown command"},
                    }
                else:
                    reply = {
                        "id": msg["id"],
                        "type": "result",
                        "success": True,
                        "result": copy.deepcopy(self.registries[key]),
                    }
                ws.send(json.dumps(reply))
        except ConnectionClosed, TimeoutError:
            return

    def device(self, device_id: str) -> dict[str, Any]:
        return next(d for d in self.registries["devices"] if d["id"] == device_id)


@contextmanager
def running_fake_ha() -> Generator[FakeHa]:
    holder: dict[str, FakeHa] = {}

    def handler(ws: ServerConnection) -> None:
        holder["ha"].handle(ws)

    server: Server = serve(handler, "127.0.0.1", 0)
    port = server.socket.getsockname()[1]
    holder["ha"] = FakeHa(url=f"http://127.0.0.1:{port}")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield holder["ha"]
    finally:
        server.shutdown()
        thread.join(timeout=5)
