"""Export the clients and network devices known to a local UniFi console as CSV or JSON.

A standalone helper, not part of the Domus application. It talks only to a UniFi
OS console on the local network (for example a UDM Pro), never to the UniFi
cloud (``api.ui.com``) or any other host, and it sends no telemetry. It uses only
the Python standard library.

What it reads, using a local console account (Admin or a read-only "View Only"
role is enough; the script only makes read requests apart from logging in and
out):

- clients: devices connected right now (``stat/sta``), and with
  ``--include-offline`` every client the console remembers (``rest/user``);
- devices: UniFi gear adopted by the console, such as switches and access points
  (``stat/device``).

Every field the API returns is kept. Nested values are flattened into dotted CSV
columns (``uplink.ip``); lists are written as JSON text. Fields that hold secrets
(device auth keys, Wi-Fi passphrases) are replaced with ``[REDACTED]`` unless
``--no-redact`` is given.

Local-only safeguards:

- ``--host`` must be an IP address (no DNS lookup is made) in a private
  (RFC 1918), IPv6 unique local, or link-local range. Every other address,
  including public, loopback, CGNAT, and documentation ranges, is refused.
- The connection is made directly, without any proxy from the environment, and
  the address our side of the connection uses must also be private.
- Packets are sent with a hop limit (``--max-hops``, default 1), so the console
  must be on a directly connected network: a console behind another router does
  not answer.
- Redirects are never followed.

TLS: a UniFi console normally uses a self-signed certificate. Pin it with
``--fingerprint`` (run ``--show-fingerprint`` once to see it), give a CA with
``--ca-file``, or, if you must, skip verification with ``--insecure``.

Credentials come from ``--username``/``--password``, or from a credentials file
(default ``~/unifi.txt``) of ``key = value`` lines::

    # ~/unifi.txt (chmod 600)
    host = 192.168.1.1
    username = export-bot
    password = correct horse battery staple
    fingerprint = 3a:5f:...:9c

If no password is found and a terminal is attached, the script prompts for one.
Passwords are never printed or logged.

Usage::

    uv run python scripts/unifi_export.py --show-fingerprint --host 192.168.1.1
    uv run python scripts/unifi_export.py --format csv --output unifi.csv
    uv run python scripts/unifi_export.py --kind clients --include-offline --format json

Exit status: 0 on success, 1 on any error, 2 on a usage error.
"""

import argparse
import contextlib
import csv
import datetime
import getpass
import hashlib
import hmac
import http.client
import http.cookies
import ipaddress
import json
import os
import re
import socket
import ssl
import stat
import sys
import urllib.parse
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any, Protocol, cast

DEFAULT_CREDENTIALS = Path("~") / "unifi.txt"
DEFAULT_PORT = 443
DEFAULT_TIMEOUT = 15.0
DEFAULT_MAX_HOPS = 1
# A large home network's full client list is a few MB; anything far bigger is not a console.
MAX_RESPONSE_BYTES = 64 * 1024 * 1024
USER_AGENT = "unifi-export (local)"

LOGIN_PATH = "/api/auth/login"
LOGOUT_PATH = "/api/auth/logout"
NETWORK_API = "/proxy/network/api"

CREDENTIAL_KEYS = frozenset({"host", "username", "password", "fingerprint"})
REDACTED = "[REDACTED]"
# Field names that hold secrets in UniFi API responses, such as x_authkey, x_vwirekey,
# x_aes_gcm, x_passphrase, and wlan keys. Matched anywhere in the name, case-insensitively.
SECRET_FIELD = re.compile(
    r"pass(word|phrase|wd)|secret|authkey|vwirekey|aes_gcm|psk|token|private|x_iapp_key",
    re.IGNORECASE,
)
# Columns shown first in CSV output when present; the rest follow alphabetically.
PREFERRED_COLUMNS = (
    "_kind",
    "_site",
    "_online",
    "name",
    "hostname",
    "mac",
    "ip",
    "oui",
    "model",
    "type",
    "network",
    "essid",
    "is_wired",
    "first_seen",
    "last_seen",
)
LOCAL_IPV4 = tuple(
    ipaddress.IPv4Network(n)
    for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16")
)
LOCAL_IPV6 = tuple(ipaddress.IPv6Network(n) for n in ("fc00::/7", "fe80::/10"))
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


class UniFiError(Exception):
    """A problem the user can act on; its message is shown without a traceback."""


# ---------------------------------------------------------------------------
# Address checks


def is_local_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True only for RFC 1918, IPv4 link-local, IPv6 unique local, and IPv6 link-local addresses.

    An explicit list, because ``ipaddress.is_private`` also covers documentation,
    benchmarking, and loopback ranges, which are not a home network.
    """
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return is_local_address(address.ipv4_mapped)
    if isinstance(address, ipaddress.IPv4Address):
        return any(address in net for net in LOCAL_IPV4)
    plain = ipaddress.IPv6Address(address.packed)  # drop any zone such as %eth0
    return any(plain in net for net in LOCAL_IPV6)


def parse_console_address(value: str) -> str:
    """Return ``value`` as a normalized IP literal, or raise if it is not a local address.

    Hostnames are refused so that no DNS query is ever made. An IPv6 link-local
    address may carry a zone, such as ``fe80::1%eth0``.
    """
    text = value.strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        raise UniFiError(
            f"--host must be the console's IP address, such as 192.168.1.1, not {value!r}. "
            "Hostnames are not accepted, so that no DNS lookup is made."
        ) from None
    if not is_local_address(address):
        raise UniFiError(
            f"{address} is not a private or link-local address; this tool only talks to a "
            "UniFi console on the local network."
        )
    return str(address)


# ---------------------------------------------------------------------------
# Credentials


@dataclass(frozen=True)
class Credentials:
    """Settings read from a credentials file. The password never appears in ``repr``."""

    host: str | None = None
    username: str | None = None
    password: str | None = field(default=None, repr=False)
    fingerprint: str | None = None


def check_file_permissions(path: Path, warn: Callable[[str], None]) -> None:
    """Warn when a credentials file can be read by other users or is owned by someone else."""
    if os.name != "posix":
        return
    info = path.stat()
    if info.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        warn(
            f"warning: {path} is readable by other users "
            f"(mode {stat.filemode(info.st_mode)}); run: chmod 600 {path}"
        )
    if info.st_uid != os.getuid():
        warn(f"warning: {path} is owned by another user")


def parse_credentials(text: str, source: str) -> Credentials:
    """Parse ``key = value`` lines; blank lines and ``#`` comments are ignored."""
    values: dict[str, str] = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        key = key.strip().lower()
        if not sep or key not in CREDENTIAL_KEYS:
            # Never echo the line itself: it may be a password typed without its key.
            raise UniFiError(
                f"{source} line {number}: expected 'key = value' with key one of "
                f"{', '.join(sorted(CREDENTIAL_KEYS))}"
            )
        values[key] = value.strip()
    return Credentials(
        host=values.get("host") or None,
        username=values.get("username") or None,
        password=values.get("password") or None,
        fingerprint=values.get("fingerprint") or None,
    )


def load_credentials(path: Path, *, required: bool, warn: Callable[[str], None]) -> Credentials:
    """Read a credentials file. A missing file is an error only when ``required``."""
    path = path.expanduser()
    if not path.exists():
        if required:
            raise UniFiError(f"credentials file {path} does not exist")
        return Credentials()
    check_file_permissions(path, warn)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise UniFiError(f"cannot read {path}: {exc.strerror}") from None
    return parse_credentials(text, str(path))


# ---------------------------------------------------------------------------
# TLS


def normalize_fingerprint(value: str) -> str:
    """Return a SHA-256 fingerprint as 64 lowercase hex digits, accepting ``aa:bb`` form."""
    digits = re.sub(r"[\s:]", "", value).lower()
    if digits.startswith("sha256"):
        digits = digits.removeprefix("sha256").lstrip("/=")
    if not re.fullmatch(r"[0-9a-f]{64}", digits):
        raise UniFiError("--fingerprint must be a SHA-256 fingerprint: 64 hex digits")
    return digits


def format_fingerprint(digits: str) -> str:
    """Format 64 hex digits as colon-separated uppercase pairs."""
    return ":".join(digits[i : i + 2] for i in range(0, len(digits), 2)).upper()


def certificate_fingerprint(der: bytes) -> str:
    """SHA-256 of a DER certificate, as lowercase hex."""
    return hashlib.sha256(der).hexdigest()


@dataclass(frozen=True)
class TLSPolicy:
    """How the console's certificate is checked.

    Exactly one of these applies: a pinned SHA-256 ``fingerprint``, a ``ca_file``
    to verify against, ``insecure`` (no check), or else the system trust store.
    ``server_name`` is the name checked against the certificate when verifying
    against a CA; it is never looked up in DNS.
    """

    fingerprint: str | None = None
    ca_file: Path | None = None
    insecure: bool = False
    server_name: str | None = None

    def context(self) -> ssl.SSLContext:
        """Build the SSL context for this policy. TLS 1.2 is the minimum."""
        if self.fingerprint or self.insecure:
            # The fingerprint is compared after the handshake, in verify_peer.
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        elif self.ca_file is not None:
            ctx = ssl.create_default_context(cafile=str(self.ca_file))
        else:
            ctx = ssl.create_default_context()
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        return ctx

    def verify_peer(self, der: bytes | None) -> None:
        """Check a pinned fingerprint against the certificate the server presented."""
        if not self.fingerprint:
            return
        if der is None:
            raise UniFiError("the console presented no certificate")
        actual = certificate_fingerprint(der)
        if not hmac.compare_digest(actual, self.fingerprint):
            raise UniFiError(
                "the console's certificate does not match --fingerprint "
                f"(it presented {format_fingerprint(actual)}). If the console's certificate "
                "was replaced on purpose, update the fingerprint; otherwise something else "
                "may be answering at that address."
            )


# ---------------------------------------------------------------------------
# Transport: one direct HTTPS connection to the console's IP address


@dataclass
class Response:
    """An HTTP response: status, headers (names lowercased), and body."""

    status: int
    headers: dict[str, list[str]]
    body: bytes

    def header(self, name: str) -> str | None:
        values = self.headers.get(name.lower())
        return values[0] if values else None


class Transport(Protocol):
    """Sends one HTTP request to the console."""

    def request(
        self, method: str, path: str, body: bytes | None, headers: Mapping[str, str]
    ) -> Response: ...

    def close(self) -> None: ...


def open_socket(address: str, port: int, timeout: float, max_hops: int) -> socket.socket:
    """Connect a TCP socket to ``address`` with a hop limit, and check our own address.

    ``address`` must already be a validated IP literal, so no DNS lookup happens.
    """
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        if family == socket.AF_INET:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_TTL, max_hops)
        else:
            sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_UNICAST_HOPS, max_hops)
        sock.connect((address, port))
        local = str(sock.getsockname()[0])
        if not is_local_address(ipaddress.ip_address(local)):
            raise UniFiError(
                f"this computer reached {address} from {local}, which is not a local "
                "address; run this tool from the console's local network"
            )
    except BaseException:
        sock.close()
        raise
    return sock


SocketOpener = Callable[[str, int, float, int], socket.socket]


class _ConsoleConnection(http.client.HTTPSConnection):
    """An HTTPS connection to a fixed IP that applies a TLSPolicy and a hop limit.

    http.client never consults proxy environment variables and never follows
    redirects, which is what we want here.
    """

    def __init__(
        self,
        address: str,
        port: int,
        *,
        policy: TLSPolicy,
        timeout: float,
        max_hops: int,
        opener: SocketOpener,
    ) -> None:
        self._tls_context = policy.context()
        super().__init__(address, port, timeout=timeout, context=self._tls_context)
        self._policy = policy
        self._address = address
        self._timeout_s = timeout
        self._max_hops = max_hops
        self._opener = opener

    def connect(self) -> None:
        raw = self._opener(self._address, self.port, self._timeout_s, self._max_hops)
        try:
            server_name = self._policy.server_name or self._address.split("%")[0]
            tls = self._tls_context.wrap_socket(raw, server_hostname=server_name)
        except BaseException:
            raw.close()
            raise
        try:
            self._policy.verify_peer(tls.getpeercert(binary_form=True))
        except BaseException:
            tls.close()
            raise
        self.sock = tls


class HTTPSTransport:
    """The real transport: a keep-alive HTTPS connection to the console."""

    def __init__(
        self,
        address: str,
        port: int,
        policy: TLSPolicy,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        max_hops: int = DEFAULT_MAX_HOPS,
        opener: SocketOpener = open_socket,
    ) -> None:
        self._conn = _ConsoleConnection(
            address, port, policy=policy, timeout=timeout, max_hops=max_hops, opener=opener
        )

    def request(
        self, method: str, path: str, body: bytes | None, headers: Mapping[str, str]
    ) -> Response:
        self._conn.request(method, path, body=body, headers=dict(headers))
        resp = self._conn.getresponse()
        data = resp.read(MAX_RESPONSE_BYTES + 1)
        if len(data) > MAX_RESPONSE_BYTES:
            self.close()
            raise UniFiError(f"response to {path} is larger than {MAX_RESPONSE_BYTES} bytes")
        collected: dict[str, list[str]] = {}
        for name, value in resp.getheaders():
            collected.setdefault(name.lower(), []).append(value)
        return Response(resp.status, collected, data)

    def close(self) -> None:
        self._conn.close()


def fetch_fingerprint(
    address: str,
    port: int,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    max_hops: int = DEFAULT_MAX_HOPS,
    opener: SocketOpener = open_socket,
) -> str:
    """Complete a TLS handshake without verification and return the certificate's SHA-256.

    No HTTP request is sent and no credentials are used.
    """
    policy = TLSPolicy(insecure=True)
    raw = opener(address, port, timeout, max_hops)
    with policy.context().wrap_socket(raw, server_hostname=address.split("%")[0]) as tls:
        der = tls.getpeercert(binary_form=True)
    if der is None:
        raise UniFiError("the console presented no certificate")
    return certificate_fingerprint(der)


# ---------------------------------------------------------------------------
# UniFi API client (classic local Network API behind UniFi OS)


class UniFiClient:
    """Logs in to a UniFi OS console and reads Network application data."""

    def __init__(self, transport: Transport) -> None:
        self._transport = transport
        self._cookies: dict[str, str] = {}
        self._csrf: str | None = None

    def _headers(self, *, json_body: bool = False) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
        if json_body:
            headers["Content-Type"] = "application/json"
        if self._cookies:
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self._cookies.items())
        if self._csrf:
            headers["X-CSRF-Token"] = self._csrf
        return headers

    def _remember(self, response: Response) -> None:
        for raw in response.headers.get("set-cookie", []):
            jar = http.cookies.SimpleCookie()
            try:
                jar.load(raw)
            except http.cookies.CookieError:
                continue
            for name, morsel in jar.items():
                self._cookies[name] = morsel.value
        token = response.header("x-updated-csrf-token") or response.header("x-csrf-token")
        if token:
            self._csrf = token

    def _send(self, method: str, path: str, payload: Any = None) -> Response:
        body = None if payload is None else json.dumps(payload).encode()
        response = self._transport.request(
            method, path, body, self._headers(json_body=body is not None)
        )
        self._remember(response)
        return response

    def login(self, username: str, password: str) -> None:
        """Start a session. Raises UniFiError without ever including the password."""
        response = self._send(
            "POST", LOGIN_PATH, {"username": username, "password": password, "remember": False}
        )
        if response.status == 200 and self._cookies:
            return
        if response.status in (400, 401, 403):
            raise UniFiError(
                "login failed: check the username and password, and use a local console "
                "account (UniFi cloud accounts with two-factor sign-in cannot log in here)"
            )
        if response.status == 429:
            raise UniFiError("login refused: too many attempts; wait a few minutes")
        if response.status == 404:
            raise UniFiError(
                "login endpoint not found: this tool supports UniFi OS consoles "
                "such as the UDM Pro, UDM, UCG, and Cloud Key Gen2+"
            )
        raise UniFiError(f"login failed: HTTP {response.status}")

    def logout(self) -> None:
        """End the session; failures are ignored because the export is already done."""
        if not self._cookies:
            return
        with contextlib.suppress(OSError, http.client.HTTPException, UniFiError):
            self._send("POST", LOGOUT_PATH)
        self._cookies.clear()
        self._csrf = None

    def get_data(self, path: str) -> list[dict[str, Any]]:
        """GET a Network API path and return its ``data`` list of objects."""
        response = self._send("GET", path)
        if response.status == 401:
            raise UniFiError(f"{path}: not logged in or session expired")
        if response.status == 403:
            raise UniFiError(f"{path}: this account may not read Network application data")
        if response.status != 200:
            raise UniFiError(f"{path}: HTTP {response.status}")
        try:
            parsed: Any = json.loads(response.body)
        except UnicodeDecodeError, json.JSONDecodeError:
            raise UniFiError(f"{path}: response is not JSON") from None
        if not isinstance(parsed, dict):
            raise UniFiError(f"{path}: unexpected response shape")
        document = cast(dict[str, Any], parsed)
        meta: Any = document.get("meta")
        if isinstance(meta, dict):
            meta_map = cast(dict[str, Any], meta)
            if meta_map.get("rc", "ok") != "ok":
                raise UniFiError(f"{path}: API error {meta_map.get('msg', 'error')}")
        data: Any = document.get("data", [])
        if not isinstance(data, list):
            raise UniFiError(f"{path}: unexpected response shape")
        items = cast(list[Any], data)
        return [cast(dict[str, Any], item) for item in items if isinstance(item, dict)]

    @staticmethod
    def _site_path(site: str, endpoint: str) -> str:
        return f"{NETWORK_API}/s/{urllib.parse.quote(site, safe='')}/{endpoint}"

    def sites(self) -> list[dict[str, Any]]:
        return self.get_data(f"{NETWORK_API}/self/sites")

    def clients(self, site: str, *, include_offline: bool) -> list[dict[str, Any]]:
        """Connected clients; with ``include_offline``, also every known client.

        Each record gets ``_online``. When a client is both known and connected,
        the live record's fields win and the known record fills in the rest
        (such as a user-set name or a fixed IP).
        """
        active = self.get_data(self._site_path(site, "stat/sta"))
        for record in active:
            record["_online"] = True
        if not include_offline:
            return active
        merged: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for record in self.get_data(self._site_path(site, "rest/user")):
            key = str(record.get("mac", "")).lower() or f"#{len(order)}"
            merged[key] = {**record, "_online": False}
            order.append(key)
        for record in active:
            key = str(record.get("mac", "")).lower() or f"#{len(order)}"
            if key not in merged:
                order.append(key)
            merged[key] = {**merged.get(key, {}), **record}
        return [merged[key] for key in order]

    def devices(self, site: str) -> list[dict[str, Any]]:
        return self.get_data(self._site_path(site, "stat/device"))


# ---------------------------------------------------------------------------
# Shaping and writing records


def redact(value: Any) -> Any:
    """Return a copy of ``value`` with secret-looking fields replaced by ``[REDACTED]``."""
    if isinstance(value, dict):
        return {
            str(k): (REDACTED if SECRET_FIELD.search(str(k)) else redact(v))  # pyright: ignore[reportUnknownArgumentType]
            for k, v in value.items()  # pyright: ignore[reportUnknownVariableType]
        }
    if isinstance(value, list):
        return [redact(item) for item in value]  # pyright: ignore[reportUnknownVariableType]
    return value


def flatten(record: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten nested objects into dotted keys; lists become JSON text."""
    flat: dict[str, Any] = {}
    for key, value in record.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(flatten(value, f"{name}."))  # pyright: ignore[reportUnknownArgumentType]
        elif isinstance(value, list):
            flat[name] = json.dumps(value, sort_keys=True, separators=(",", ":"))
        else:
            flat[name] = value
    return flat


def csv_cell(value: Any) -> str:
    """Render a value for CSV, neutralizing text a spreadsheet would run as a formula.

    Client hostnames come from the clients themselves, so they are untrusted.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    text = str(value)
    if text.startswith(FORMULA_PREFIXES):
        return "'" + text
    return text


def column_order(rows: Iterable[Mapping[str, Any]]) -> list[str]:
    """Preferred columns first (when present), then every other column alphabetically."""
    seen: set[str] = set()
    for row in rows:
        seen.update(row)
    first = [c for c in PREFERRED_COLUMNS if c in seen]
    return first + sorted(seen.difference(first))


def write_csv(records: Sequence[Mapping[str, Any]], out: IO[str]) -> None:
    rows = [flatten(r) for r in records]
    columns = column_order(rows)
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([csv_cell(row.get(c)) for c in columns])


def write_json(records: Sequence[Mapping[str, Any]], out: IO[str], *, console: str) -> None:
    document = {
        "generated_at": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        "console": console,
        "records": list(records),
    }
    json.dump(document, out, indent=2, sort_keys=True, ensure_ascii=False)
    out.write("\n")


def open_output(path: Path) -> IO[str]:
    """Open ``path`` for writing, readable only by the owner (the export lists the network)."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    return os.fdopen(fd, "w", encoding="utf-8", newline="")


# ---------------------------------------------------------------------------
# Command line


def collect(
    client: UniFiClient, *, sites: Sequence[str], kind: str, include_offline: bool
) -> list[dict[str, Any]]:
    """Read the requested records from each site, tagging each with ``_kind`` and ``_site``."""
    known = {str(s.get("name")): s for s in client.sites()}
    wanted = list(sites) or list(known)
    missing = [s for s in wanted if s not in known]
    if missing:
        raise UniFiError(
            f"unknown site(s): {', '.join(missing)}; known sites: {', '.join(known) or 'none'}"
        )
    records: list[dict[str, Any]] = []
    for site in wanted:
        if kind in ("clients", "all"):
            for record in client.clients(site, include_offline=include_offline):
                records.append({"_kind": "client", "_site": site, **record})
        if kind in ("devices", "all"):
            for record in client.devices(site):
                records.append({"_kind": "device", "_site": site, **record})
    return records


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Export clients and UniFi devices from a UniFi OS console on the local network "
            "as CSV or JSON. Talks only to the console's private IP address."
        )
    )
    parser.add_argument("--host", help="console IP address (or 'host' in the credentials file)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="HTTPS port (443)")
    parser.add_argument("--username", help="local console account")
    parser.add_argument(
        "--password",
        help="password; prefer the credentials file or the prompt, since command lines "
        "can be seen by other users and saved in shell history",
    )
    parser.add_argument(
        "--credentials",
        type=Path,
        help=f"credentials file of 'key = value' lines (default {DEFAULT_CREDENTIALS})",
    )
    tls = parser.add_mutually_exclusive_group()
    tls.add_argument("--fingerprint", help="pin the console's SHA-256 certificate fingerprint")
    tls.add_argument("--ca-file", type=Path, help="verify the console against this CA (PEM)")
    tls.add_argument(
        "--insecure", action="store_true", help="do not verify the console's certificate"
    )
    parser.add_argument(
        "--tls-name", help="name to check in the certificate with --ca-file (no DNS lookup)"
    )
    parser.add_argument(
        "--show-fingerprint",
        action="store_true",
        help="print the console's certificate fingerprint and exit (sends no credentials)",
    )
    parser.add_argument(
        "--site",
        action="append",
        default=[],
        help="site name, such as 'default'; repeat for several (default: every site)",
    )
    parser.add_argument(
        "--kind", choices=("clients", "devices", "all"), default="all", help="what to export"
    )
    parser.add_argument(
        "--include-offline",
        action="store_true",
        help="also export clients the console knows but that are not connected now",
    )
    parser.add_argument("--format", choices=("csv", "json"), default="csv")
    parser.add_argument("--output", type=Path, help="file to write (default: standard output)")
    parser.add_argument(
        "--no-redact", action="store_true", help="keep secret fields such as device auth keys"
    )
    parser.add_argument(
        "--max-hops",
        type=int,
        default=DEFAULT_MAX_HOPS,
        help="router hops allowed to the console (default 1: same network as the console)",
    )
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="seconds")
    return parser


TransportFactory = Callable[[str, int, TLSPolicy, float, int], Transport]


def _default_transport(
    address: str, port: int, policy: TLSPolicy, timeout: float, max_hops: int
) -> Transport:
    return HTTPSTransport(address, port, policy, timeout=timeout, max_hops=max_hops)


def _default_fingerprint(address: str, port: int, timeout: float, max_hops: int) -> str:
    return fetch_fingerprint(address, port, timeout=timeout, max_hops=max_hops)


def _describe_connection_error(exc: Exception, address: str, max_hops: int) -> str:
    if isinstance(exc, ssl.SSLCertVerificationError):
        return (
            f"cannot verify the console's certificate ({exc.verify_message}). UniFi consoles "
            "usually use a self-signed certificate: run with --show-fingerprint, check the "
            "value, then pass it with --fingerprint (or put it in the credentials file)."
        )
    if not isinstance(exc, ssl.SSLError):
        return (
            f"cannot connect to {address}: {exc}. Check the address and that this computer "
            f"is on the console's local network (hop limit {max_hops}; see --max-hops)."
        )
    return f"connection to {address} failed: {exc}"


def main(
    argv: Sequence[str] | None = None,
    *,
    transport_factory: TransportFactory = _default_transport,
    fingerprint_fetcher: Callable[[str, int, float, int], str] | None = None,
    prompt: Callable[[str], str] = getpass.getpass,
    stdin_isatty: Callable[[], bool] = sys.stdin.isatty,
    stdout: IO[str] | None = None,
    stderr: IO[str] | None = None,
) -> int:
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    args = build_parser().parse_args(argv)

    def warn(message: str) -> None:
        print(message, file=err)

    target_text = "the console"
    try:
        if not 1 <= args.max_hops <= 255:
            raise UniFiError("--max-hops must be between 1 and 255")
        if not 0 < args.port < 65536:
            raise UniFiError("--port must be between 1 and 65535")
        creds_path: Path = args.credentials or DEFAULT_CREDENTIALS
        creds = load_credentials(creds_path, required=args.credentials is not None, warn=warn)

        host = args.host or creds.host
        if not host:
            raise UniFiError("give the console's IP address with --host or in the credentials file")
        address = parse_console_address(host)
        target_text = address

        if args.show_fingerprint:
            fetch = fingerprint_fetcher or _default_fingerprint
            digits = fetch(address, args.port, args.timeout, args.max_hops)
            print(f"SHA-256 fingerprint of {address}:{args.port}", file=out)
            print(format_fingerprint(digits), file=out)
            return 0

        fingerprint = args.fingerprint
        if fingerprint is None and args.ca_file is None and not args.insecure:
            fingerprint = creds.fingerprint
        if args.insecure:
            warn("warning: --insecure: the console's certificate is not checked")
        if args.ca_file is not None and not args.ca_file.is_file():
            raise UniFiError(f"--ca-file {args.ca_file} does not exist")
        policy = TLSPolicy(
            fingerprint=normalize_fingerprint(fingerprint) if fingerprint else None,
            ca_file=args.ca_file,
            insecure=args.insecure,
            server_name=args.tls_name,
        )

        username = args.username or creds.username
        if not username:
            raise UniFiError(f"give a username with --username or in {creds_path.expanduser()}")
        # The file's password belongs to the file's username, so it is not used with another.
        password = args.password
        if not password and username == (creds.username or username):
            password = creds.password
        if not password:
            if not stdin_isatty():
                raise UniFiError("no password given and no terminal to prompt on")
            password = prompt(f"Password for {username} on {address}: ")

        transport = transport_factory(address, args.port, policy, args.timeout, args.max_hops)
        client = UniFiClient(transport)
        try:
            client.login(username, password)
            records = collect(
                client, sites=args.site, kind=args.kind, include_offline=args.include_offline
            )
        finally:
            client.logout()
            transport.close()

        if not args.no_redact:
            records = [redact(r) for r in records]
        target = open_output(args.output) if args.output else out
        try:
            if args.format == "csv":
                write_csv(records, target)
            else:
                write_json(records, target, console=address)
        finally:
            if target is not out:
                target.close()
        counts = {k: sum(1 for r in records if r["_kind"] == k) for k in ("client", "device")}
        warn(f"exported {counts['client']} clients and {counts['device']} devices")
        return 0
    except UniFiError as exc:
        warn(f"error: {exc}")
        return 1
    except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
        warn(f"error: {_describe_connection_error(exc, target_text, args.max_hops)}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
