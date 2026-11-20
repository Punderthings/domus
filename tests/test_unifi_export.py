"""Tests for scripts/unifi_export.py. The console is faked; nothing touches the network."""

import csv
import hashlib
import importlib.util
import io
import json
import os
import socket
import ssl
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "unifi_export.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("unifi_export", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ue = _load()

PASSWORD = "s3cret-Pa55"  # noqa: S105 - a test value
CERT = b"fake DER certificate"
CERT_SHA = hashlib.sha256(CERT).hexdigest()
SITES = "/proxy/network/api/self/sites"
STA = "/proxy/network/api/s/default/stat/sta"
USERS = "/proxy/network/api/s/default/rest/user"
DEVICES = "/proxy/network/api/s/default/stat/device"


def ok(data: list[dict[str, Any]]) -> Any:
    return ue.Response(200, {}, json.dumps({"meta": {"rc": "ok"}, "data": data}).encode())


def login_ok() -> Any:
    return ue.Response(
        200,
        {"set-cookie": ["TOKEN=abc123; Path=/; Secure; HttpOnly"], "x-csrf-token": ["csrf-1"]},
        b"{}",
    )


class FakeTransport:
    """Answers requests from a route table and records what was sent."""

    def __init__(self, routes: Mapping[tuple[str, str], Any]) -> None:
        self.routes = dict(routes)
        self.sent: list[tuple[str, str, bytes | None, dict[str, str]]] = []
        self.closed = False

    def request(
        self, method: str, path: str, body: bytes | None, headers: Mapping[str, str]
    ) -> Any:
        self.sent.append((method, path, body, dict(headers)))
        route = self.routes.get((method, path))
        if route is None:
            return ue.Response(404, {}, b"")
        if isinstance(route, Exception):
            raise route
        return route

    def close(self) -> None:
        self.closed = True


CLIENTS = [
    {
        "mac": "AA:BB:CC:00:00:01",
        "hostname": '=HYPERLINK("http://evil")',
        "ip": "192.168.1.20",
        "is_wired": False,
        "signal": -61,
        "essid": "home",
    },
    {"mac": "aa:bb:cc:00:00:02", "name": "Printer", "ip": "192.168.1.30", "is_wired": True},
]
KNOWN = [
    {"mac": "aa:bb:cc:00:00:01", "name": "Phone", "use_fixedip": True, "fixed_ip": "192.168.1.20"},
    {"mac": "aa:bb:cc:00:00:09", "name": "Old laptop"},
]
DEVICE_LIST = [
    {
        "mac": "f0:9f:c2:00:00:01",
        "model": "UDMPRO",
        "name": "Gateway",
        "x_authkey": "deadbeef",
        "uplink": {"ip": "203.0.113.5", "speed": 1000},
        "port_table": [{"port_idx": 1}],
        "config_network": {"type": "dhcp", "x_passphrase": "wifi-pass"},
    }
]


def console_routes() -> dict[tuple[str, str], Any]:
    return {
        ("POST", ue.LOGIN_PATH): login_ok(),
        ("POST", ue.LOGOUT_PATH): ue.Response(200, {}, b""),
        ("GET", SITES): ok([{"name": "default", "desc": "Default"}]),
        ("GET", STA): ok([dict(c) for c in CLIENTS]),
        ("GET", USERS): ok([dict(c) for c in KNOWN]),
        ("GET", DEVICES): ok([dict(d) for d in DEVICE_LIST]),
    }


@pytest.fixture(autouse=True)
def _no_home_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Never read the real ~/unifi.txt."""
    monkeypatch.setattr(ue, "DEFAULT_CREDENTIALS", tmp_path / "absent-unifi.txt")


# ---------------------------------------------------------------------------
# Address checks


@pytest.mark.parametrize(
    "value",
    [
        "192.168.1.1",
        "10.0.0.1",
        "172.16.5.4",
        "169.254.10.1",
        "fd00::1",
        "fe80::1%eth0",
        "[fd00::1]",
    ],
)
def test_local_addresses_accepted(value: str) -> None:
    assert ue.parse_console_address(value)


@pytest.mark.parametrize(
    "value",
    [
        "8.8.8.8",
        "127.0.0.1",
        "::1",
        "100.64.1.1",  # CGNAT
        "224.0.0.1",
        "0.0.0.0",  # noqa: S104 - a test value
        "255.255.255.255",
        "240.0.0.1",
        "2001:4860:4860::8888",
        "::ffff:8.8.8.8",
        "203.0.113.5",  # documentation range
        "198.18.0.1",  # benchmarking range
        "2001:db8::1",
        "fec0::1",  # deprecated site-local
    ],
)
def test_non_local_addresses_refused(value: str) -> None:
    with pytest.raises(ue.UniFiError, match="not a private"):
        ue.parse_console_address(value)


@pytest.mark.parametrize(
    "value", ["unifi.local", "https://192.168.1.1", "192.168.1.1:443", "api.ui.com", ""]
)
def test_hostnames_and_urls_refused(value: str) -> None:
    with pytest.raises(ue.UniFiError, match="IP address"):
        ue.parse_console_address(value)


def test_ipv4_mapped_private_is_local() -> None:
    assert ue.parse_console_address("::ffff:192.168.1.1")


# ---------------------------------------------------------------------------
# Credentials


def test_parse_credentials() -> None:
    creds = ue.parse_credentials(
        f"# comment\n\nhost = 192.168.1.1\nUsername=admin\npassword = {PASSWORD}\n"
        "fingerprint = aa:bb\n",
        "f",
    )
    assert creds.host == "192.168.1.1"
    assert creds.username == "admin"
    assert creds.password == PASSWORD
    assert creds.fingerprint == "aa:bb"
    assert PASSWORD not in repr(creds)


def test_password_with_equals_sign_kept_whole() -> None:
    creds = ue.parse_credentials("password = a=b=c\n", "f")
    assert creds.password == "a=b=c"  # noqa: S105 - a test value


@pytest.mark.parametrize("line", [PASSWORD, "token = x"])
def test_bad_credential_line_not_echoed(line: str) -> None:
    with pytest.raises(ue.UniFiError) as info:
        ue.parse_credentials(f"username = a\n{line}\n", "creds.txt")
    assert "line 2" in str(info.value)
    assert line not in str(info.value)


def test_missing_optional_credentials_file(tmp_path: Path) -> None:
    creds = ue.load_credentials(tmp_path / "none.txt", required=False, warn=print)
    assert creds == ue.Credentials()


def test_missing_required_credentials_file(tmp_path: Path) -> None:
    with pytest.raises(ue.UniFiError, match="does not exist"):
        ue.load_credentials(tmp_path / "none.txt", required=True, warn=print)


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
def test_open_permissions_warn(tmp_path: Path) -> None:
    path = tmp_path / "unifi.txt"
    path.write_text("username = a\n")
    warnings: list[str] = []
    path.chmod(0o644)
    ue.load_credentials(path, required=True, warn=warnings.append)
    assert any("chmod 600" in w for w in warnings)
    warnings.clear()
    path.chmod(0o600)
    ue.load_credentials(path, required=True, warn=warnings.append)
    assert warnings == []


# ---------------------------------------------------------------------------
# TLS


@pytest.mark.parametrize(
    "value", [CERT_SHA, CERT_SHA.upper(), ue.format_fingerprint(CERT_SHA), f"sha256/{CERT_SHA}"]
)
def test_normalize_fingerprint(value: str) -> None:
    assert ue.normalize_fingerprint(value) == CERT_SHA


@pytest.mark.parametrize("value", ["abc", CERT_SHA[:-1] + "z", CERT_SHA + "00"])
def test_bad_fingerprint(value: str) -> None:
    with pytest.raises(ue.UniFiError, match="64 hex"):
        ue.normalize_fingerprint(value)


def test_verify_peer() -> None:
    policy = ue.TLSPolicy(fingerprint=CERT_SHA)
    policy.verify_peer(CERT)
    with pytest.raises(ue.UniFiError, match="does not match"):
        policy.verify_peer(b"other certificate")
    with pytest.raises(ue.UniFiError, match="no certificate"):
        policy.verify_peer(None)
    ue.TLSPolicy().verify_peer(None)  # nothing pinned, nothing to check


def test_tls_contexts(tmp_path: Path) -> None:
    pinned = ue.TLSPolicy(fingerprint=CERT_SHA).context()
    assert pinned.verify_mode == ssl.CERT_NONE
    assert pinned.minimum_version == ssl.TLSVersion.TLSv1_2
    default = ue.TLSPolicy().context()
    assert default.verify_mode == ssl.CERT_REQUIRED
    assert default.check_hostname


# ---------------------------------------------------------------------------
# Sockets and the HTTPS connection, with fakes in place of the network


class FakeSocket:
    def __init__(self, family: int, kind: int, local: str = "192.168.1.50") -> None:
        self.family = family
        self.options: list[tuple[int, int, int]] = []
        self.connected: tuple[Any, ...] | None = None
        self.closed = False
        self.local = local

    def settimeout(self, value: float) -> None:
        self.timeout = value

    def setsockopt(self, level: int, option: int, value: int) -> None:
        self.options.append((level, option, value))

    def connect(self, address: tuple[Any, ...]) -> None:
        self.connected = address

    def getsockname(self) -> tuple[Any, ...]:
        return (self.local, 50000)

    def close(self) -> None:
        self.closed = True


def test_open_socket_sets_hop_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    made: list[FakeSocket] = []

    def factory(family: int, kind: int) -> FakeSocket:
        made.append(FakeSocket(family, kind))
        return made[-1]

    monkeypatch.setattr(ue.socket, "socket", factory)
    ue.open_socket("192.168.1.1", 443, 5.0, 1)
    assert made[0].options == [(socket.IPPROTO_IP, socket.IP_TTL, 1)]
    assert made[0].connected == ("192.168.1.1", 443)
    ue.open_socket("fd00::1", 443, 5.0, 2)
    assert made[1].family == socket.AF_INET6
    assert made[1].options == [(socket.IPPROTO_IPV6, socket.IPV6_UNICAST_HOPS, 2)]


def test_open_socket_refuses_non_local_source(monkeypatch: pytest.MonkeyPatch) -> None:
    made: list[FakeSocket] = []

    def factory(family: int, kind: int) -> FakeSocket:
        made.append(FakeSocket(family, kind, local="198.51.100.7"))
        return made[-1]

    monkeypatch.setattr(ue.socket, "socket", factory)
    with pytest.raises(ue.UniFiError, match="not a local"):
        ue.open_socket("192.168.1.1", 443, 5.0, 1)
    assert made[0].closed


class FakeTLS:
    def __init__(self, der: bytes | None) -> None:
        self.der = der
        self.closed = False

    def getpeercert(self, binary_form: bool = False) -> bytes | None:
        return self.der

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> FakeTLS:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class FakeContext:
    def __init__(self, tls: FakeTLS) -> None:
        self.tls = tls
        self.server_hostname: str | None = None

    def wrap_socket(self, sock: Any, server_hostname: str | None = None) -> FakeTLS:
        self.server_hostname = server_hostname
        return self.tls


def _connection(policy: Any, tls: FakeTLS) -> tuple[Any, FakeContext, list[tuple[Any, ...]]]:
    calls: list[tuple[Any, ...]] = []

    def opener(address: str, port: int, timeout: float, hops: int) -> Any:
        calls.append((address, port, timeout, hops))
        return FakeSocket(socket.AF_INET, socket.SOCK_STREAM)

    conn = ue._ConsoleConnection(  # pyright: ignore[reportPrivateUsage]
        "192.168.1.1", 443, policy=policy, timeout=3.0, max_hops=1, opener=opener
    )
    fake = FakeContext(tls)
    conn._tls_context = fake  # pyright: ignore[reportPrivateUsage]
    return conn, fake, calls


def test_connection_accepts_pinned_certificate() -> None:
    tls = FakeTLS(CERT)
    conn, ctx, calls = _connection(ue.TLSPolicy(fingerprint=CERT_SHA), tls)
    conn.connect()
    assert conn.sock is tls
    assert calls == [("192.168.1.1", 443, 3.0, 1)]
    assert ctx.server_hostname == "192.168.1.1"


def test_connection_rejects_other_certificate() -> None:
    tls = FakeTLS(b"impostor")
    conn, _, _ = _connection(ue.TLSPolicy(fingerprint=CERT_SHA), tls)
    with pytest.raises(ue.UniFiError, match="does not match"):
        conn.connect()
    assert tls.closed


def test_connection_uses_tls_name() -> None:
    conn, ctx, _ = _connection(ue.TLSPolicy(server_name="udm.home.arpa"), FakeTLS(CERT))
    conn.connect()
    assert ctx.server_hostname == "udm.home.arpa"


def test_fetch_fingerprint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ue.TLSPolicy, "context", lambda self: FakeContext(FakeTLS(CERT)))  # pyright: ignore[reportUnknownLambdaType, reportUnknownArgumentType]

    def opener(address: str, port: int, timeout: float, hops: int) -> Any:
        return FakeSocket(socket.AF_INET, socket.SOCK_STREAM)

    assert ue.fetch_fingerprint("192.168.1.1", 443, opener=opener) == CERT_SHA


# ---------------------------------------------------------------------------
# API client


def test_login_keeps_session_and_never_sends_password_elsewhere() -> None:
    transport = FakeTransport(console_routes())
    client = ue.UniFiClient(transport)
    client.login("admin", PASSWORD)
    method, path, body, _ = transport.sent[0]
    assert (method, path) == ("POST", ue.LOGIN_PATH)
    assert body is not None
    assert json.loads(body) == {"username": "admin", "password": PASSWORD, "remember": False}
    client.sites()
    headers = transport.sent[1][3]
    assert headers["Cookie"] == "TOKEN=abc123"
    assert headers["X-CSRF-Token"] == "csrf-1"
    client.logout()
    assert transport.sent[-1][1] == ue.LOGOUT_PATH
    for _, _, sent_body, sent_headers in transport.sent[1:]:
        assert PASSWORD not in (sent_body or b"").decode()
        assert PASSWORD not in json.dumps(sent_headers)


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (401, "login failed"),
        (403, "login failed"),
        (429, "too many"),
        (404, "not found"),
        (500, "HTTP 500"),
    ],
)
def test_login_failures(status: int, message: str) -> None:
    transport = FakeTransport({("POST", ue.LOGIN_PATH): ue.Response(status, {}, b"")})
    with pytest.raises(ue.UniFiError, match=message) as info:
        ue.UniFiClient(transport).login("admin", PASSWORD)
    assert PASSWORD not in str(info.value)


def test_login_without_cookie_fails() -> None:
    transport = FakeTransport({("POST", ue.LOGIN_PATH): ue.Response(200, {}, b"{}")})
    with pytest.raises(ue.UniFiError, match="login failed"):
        ue.UniFiClient(transport).login("admin", PASSWORD)


def test_updated_csrf_token_is_used() -> None:
    routes = console_routes()
    routes[("GET", SITES)] = ue.Response(
        200, {"x-updated-csrf-token": ["csrf-2"]}, json.dumps({"data": []}).encode()
    )
    transport = FakeTransport(routes)
    client = ue.UniFiClient(transport)
    client.login("admin", PASSWORD)
    client.sites()
    client.logout()
    assert transport.sent[-1][3]["X-CSRF-Token"] == "csrf-2"


def test_logout_ignores_errors() -> None:
    routes = console_routes()
    routes[("POST", ue.LOGOUT_PATH)] = OSError("gone")
    client = ue.UniFiClient(FakeTransport(routes))
    client.login("admin", PASSWORD)
    client.logout()


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (ue.Response(401, {}, b""), "session expired"),
        (ue.Response(403, {}, b""), "may not read"),
        (ue.Response(502, {}, b""), "HTTP 502"),
        (ue.Response(200, {}, b"<html>"), "not JSON"),
        (ue.Response(200, {}, b"[]"), "unexpected"),
        (ue.Response(200, {}, b'{"data": {}}'), "unexpected"),
        (
            ue.Response(200, {}, b'{"meta": {"rc": "error", "msg": "api.err.NoSiteContext"}}'),
            "NoSiteContext",
        ),
    ],
)
def test_get_data_errors(response: Any, message: str) -> None:
    client = ue.UniFiClient(FakeTransport({("GET", SITES): response}))
    with pytest.raises(ue.UniFiError, match=message):
        client.sites()


def test_get_data_skips_non_objects() -> None:
    body = json.dumps({"data": [{"name": "default"}, "junk", 3]}).encode()
    client = ue.UniFiClient(FakeTransport({("GET", SITES): ue.Response(200, {}, body)}))
    assert client.sites() == [{"name": "default"}]


def test_site_name_is_quoted() -> None:
    transport = FakeTransport({})
    with pytest.raises(ue.UniFiError):
        ue.UniFiClient(transport).devices("../../api/auth")
    assert transport.sent[0][1] == "/proxy/network/api/s/..%2F..%2Fapi%2Fauth/stat/device"


def test_clients_online_only() -> None:
    clients = ue.UniFiClient(FakeTransport(console_routes())).clients(
        "default", include_offline=False
    )
    assert [c["mac"] for c in clients] == ["AA:BB:CC:00:00:01", "aa:bb:cc:00:00:02"]
    assert all(c["_online"] for c in clients)


def test_clients_with_offline_are_merged() -> None:
    clients = ue.UniFiClient(FakeTransport(console_routes())).clients(
        "default", include_offline=True
    )
    by_mac = {c["mac"].lower(): c for c in clients}
    assert len(clients) == 3
    phone = by_mac["aa:bb:cc:00:00:01"]
    assert phone["_online"] is True
    assert phone["name"] == "Phone"  # from the known-client record
    assert phone["signal"] == -61  # from the live record
    assert by_mac["aa:bb:cc:00:00:09"]["_online"] is False
    assert by_mac["aa:bb:cc:00:00:02"]["_online"] is True


# ---------------------------------------------------------------------------
# Shaping records


def test_redact() -> None:
    redacted = ue.redact(DEVICE_LIST[0])
    assert redacted["x_authkey"] == ue.REDACTED
    assert redacted["config_network"]["x_passphrase"] == ue.REDACTED
    assert redacted["config_network"]["type"] == "dhcp"
    assert redacted["uplink"] == DEVICE_LIST[0]["uplink"]
    assert ue.redact([{"wpa_psk": "x"}]) == [{"wpa_psk": ue.REDACTED}]
    assert DEVICE_LIST[0]["x_authkey"] == "deadbeef"  # the input is not changed


def test_flatten() -> None:
    flat = ue.flatten({"a": 1, "b": {"c": {"d": None}}, "e": [1, {"f": 2}]})
    assert flat == {"a": 1, "b.c.d": None, "e": '[1,{"f":2}]'}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ""),
        (True, "true"),
        (False, "false"),
        (-61, "-61"),
        (1.5, "1.5"),
        ("phone", "phone"),
        ("=1+1", "'=1+1"),
        ("+cmd", "'+cmd"),
        ("-x", "'-x"),
        ("@SUM(A1)", "'@SUM(A1)"),
        ("\tx", "'\tx"),
    ],
)
def test_csv_cell(value: Any, expected: str) -> None:
    assert ue.csv_cell(value) == expected


def test_column_order() -> None:
    assert ue.column_order([{"zeta": 1, "mac": 2}, {"_kind": 3, "alpha": 4}]) == [
        "_kind",
        "mac",
        "alpha",
        "zeta",
    ]


# ---------------------------------------------------------------------------
# Command line


def write_creds(tmp_path: Path, extra: str = "") -> Path:
    path = tmp_path / "unifi.txt"
    path.write_text(f"host = 192.168.1.1\nusername = admin\npassword = {PASSWORD}\n{extra}")
    path.chmod(0o600)
    return path


class Harness:
    def __init__(self, routes: dict[tuple[str, str], Any] | None = None) -> None:
        self.transport = FakeTransport(routes if routes is not None else console_routes())
        self.factory_args: tuple[Any, ...] | None = None
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()
        self.prompts: list[str] = []
        self.tty = True

    def factory(self, address: str, port: int, policy: Any, timeout: float, hops: int) -> Any:
        self.factory_args = (address, port, policy, timeout, hops)
        return self.transport

    def prompt(self, text: str) -> str:
        self.prompts.append(text)
        return PASSWORD

    def run(self, *argv: str, **kwargs: Any) -> int:
        return ue.main(
            list(argv),
            transport_factory=self.factory,
            prompt=self.prompt,
            stdin_isatty=lambda: self.tty,
            stdout=self.stdout,
            stderr=self.stderr,
            **kwargs,
        )


def test_main_csv_to_file(tmp_path: Path) -> None:
    creds = write_creds(tmp_path, f"fingerprint = {ue.format_fingerprint(CERT_SHA)}\n")
    out = tmp_path / "out.csv"
    h = Harness()
    assert h.run("--credentials", str(creds), "--output", str(out)) == 0
    assert h.factory_args is not None
    address, port, policy, _, hops = h.factory_args
    assert (address, port, hops) == ("192.168.1.1", 443, 1)
    assert policy.fingerprint == CERT_SHA
    rows = list(csv.DictReader(out.read_text().splitlines()))
    assert [r["_kind"] for r in rows] == ["client", "client", "device"]
    assert rows[0]["hostname"].startswith("'=")
    assert rows[0]["signal"] == "-61"
    assert rows[2]["x_authkey"] == ue.REDACTED
    assert rows[2]["config_network.x_passphrase"] == ue.REDACTED
    assert rows[2]["uplink.ip"] == "203.0.113.5"
    assert list(rows[0])[:3] == ["_kind", "_site", "_online"]
    if os.name == "posix":
        assert out.stat().st_mode & 0o777 == 0o600
    assert "exported 2 clients and 1 devices" in h.stderr.getvalue()
    assert h.transport.closed
    assert h.transport.sent[-1][1] == ue.LOGOUT_PATH
    assert PASSWORD not in h.stderr.getvalue() + h.stdout.getvalue() + out.read_text()


def test_main_json_no_redact(tmp_path: Path) -> None:
    h = Harness()
    code = h.run(
        "--credentials", str(write_creds(tmp_path)), "--insecure", "--format", "json",
        "--kind", "devices", "--no-redact",
    )  # fmt: skip
    assert code == 0
    document = json.loads(h.stdout.getvalue())
    assert document["console"] == "192.168.1.1"
    assert [r["_kind"] for r in document["records"]] == ["device"]
    assert document["records"][0]["x_authkey"] == "deadbeef"
    assert "--insecure" in h.stderr.getvalue()
    assert h.factory_args is not None
    assert h.factory_args[2].insecure


def test_main_include_offline(tmp_path: Path) -> None:
    h = Harness()
    code = h.run(
        "--credentials", str(write_creds(tmp_path)), "--insecure", "--format", "json",
        "--kind", "clients", "--include-offline", "--site", "default",
    )  # fmt: skip
    assert code == 0
    assert len(json.loads(h.stdout.getvalue())["records"]) == 3


def test_main_unknown_site(tmp_path: Path) -> None:
    h = Harness()
    code = h.run("--credentials", str(write_creds(tmp_path)), "--insecure", "--site", "lab")
    assert code == 1
    assert "unknown site(s): lab" in h.stderr.getvalue()
    assert h.transport.sent[-1][1] == ue.LOGOUT_PATH


def test_main_prompts_for_password(tmp_path: Path) -> None:
    h = Harness()
    code = h.run(
        "--credentials", str(tmp_path / "none.txt"), "--host", "192.168.1.1",
        "--username", "admin", "--insecure",
    )  # fmt: skip
    assert code == 1  # a file named with --credentials must exist
    assert "does not exist" in h.stderr.getvalue()
    h = Harness()
    code = h.run("--host", "192.168.1.1", "--username", "admin", "--insecure")
    assert code == 0, h.stderr.getvalue()
    assert h.prompts == ["Password for admin on 192.168.1.1: "]


def test_main_file_password_not_used_for_other_user(tmp_path: Path) -> None:
    h = Harness()
    code = h.run("--credentials", str(write_creds(tmp_path)), "--insecure", "--username", "bob")
    assert code == 0
    assert h.prompts == ["Password for bob on 192.168.1.1: "]


def test_main_no_tty_no_password(tmp_path: Path) -> None:
    h = Harness()
    h.tty = False
    code = h.run("--host", "192.168.1.1", "--username", "admin", "--insecure")
    assert code == 1
    assert "no terminal" in h.stderr.getvalue()


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--host", "8.8.8.8"], "not a private"),
        (["--host", "unifi.local"], "IP address"),
        (["--max-hops", "0"], "--max-hops"),
        (["--port", "0"], "--port"),
        (["--fingerprint", "nope"], "64 hex"),
        (["--ca-file", "/nonexistent/ca.pem"], "does not exist"),
    ],
)
def test_main_usage_errors(tmp_path: Path, args: list[str], message: str) -> None:
    h = Harness()
    assert h.run("--credentials", str(write_creds(tmp_path)), *args) == 1
    assert message in h.stderr.getvalue()
    assert h.transport.sent == []


def test_main_needs_host(tmp_path: Path) -> None:
    creds = tmp_path / "c.txt"
    creds.write_text("username = a\n")
    creds.chmod(0o600)
    h = Harness()
    assert h.run("--credentials", str(creds)) == 1
    assert "--host" in h.stderr.getvalue()


def test_main_show_fingerprint(tmp_path: Path) -> None:
    h = Harness()
    seen: list[tuple[Any, ...]] = []

    def fetch(address: str, port: int, timeout: float, hops: int) -> str:
        seen.append((address, port, hops))
        return CERT_SHA

    code = h.run("--host", "192.168.1.1", "--show-fingerprint", fingerprint_fetcher=fetch)
    assert code == 0
    assert ue.format_fingerprint(CERT_SHA) in h.stdout.getvalue()
    assert seen == [("192.168.1.1", 443, 1)]
    assert h.transport.sent == []


def test_main_certificate_error_suggests_pinning(tmp_path: Path) -> None:
    error = ssl.SSLCertVerificationError("self-signed certificate")
    error.verify_message = "self-signed certificate"
    h = Harness({("POST", ue.LOGIN_PATH): error})
    assert h.run("--credentials", str(write_creds(tmp_path))) == 1
    assert "--show-fingerprint" in h.stderr.getvalue()


def test_main_connection_error_mentions_hops(tmp_path: Path) -> None:
    h = Harness({("POST", ue.LOGIN_PATH): TimeoutError("timed out")})
    assert h.run("--credentials", str(write_creds(tmp_path)), "--insecure") == 1
    assert "--max-hops" in h.stderr.getvalue()
    assert h.transport.closed


def test_tls_options_are_exclusive(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        Harness().run("--insecure", "--fingerprint", CERT_SHA)
