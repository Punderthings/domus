"""A minimal synchronous ASGI test client.

Starlette's TestClient needs httpx, which pulls in certifi (MPL-2.0). Shane's
rule is to avoid MPL when a permissive alternative exists, so the tests drive
the ASGI app directly with anyio (MIT, already a Starlette dependency).
Nothing here opens a socket.
"""

import json as jsonlib
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from typing import Any
from urllib.parse import urlencode

import anyio
from starlette.types import ASGIApp, Message


@dataclass
class Response:
    status_code: int
    headers: list[tuple[str, str]]
    content: bytes

    @property
    def text(self) -> str:
        return self.content.decode()

    def json(self) -> Any:
        return jsonlib.loads(self.content)

    def header(self, name: str) -> str | None:
        name = name.lower()
        for k, v in self.headers:
            if k == name:
                return v
        return None

    def headers_all(self, name: str) -> list[str]:
        return [v for k, v in self.headers if k == name.lower()]


@dataclass
class Client:
    app: ASGIApp
    cookies: dict[str, str] = field(default_factory=dict[str, str])
    headers: dict[str, str] = field(default_factory=dict[str, str])
    client_host: str = "127.0.0.1"
    send_csrf: bool = True
    membership_id: str | None = None

    def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Response:
        body = b"" if json is None else jsonlib.dumps(json).encode()
        hdrs = {**self.headers, **(headers or {})}
        if json is not None:
            hdrs.setdefault("content-type", "application/json")
        if self.cookies:
            hdrs["cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
            if self.send_csrf and "domus_csrf" in self.cookies:
                hdrs.setdefault("x-csrf-token", self.cookies["domus_csrf"])
        query = urlencode({k: v for k, v in (params or {}).items() if v is not None}, doseq=True)
        scope: dict[str, Any] = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method.upper(),
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": query.encode(),
            "root_path": "",
            "headers": [(k.lower().encode(), v.encode()) for k, v in hdrs.items()]
            + [(b"content-length", str(len(body)).encode()), (b"host", b"testserver")],
            "client": (self.client_host, 50000),
            "server": ("testserver", 80),
        }
        status = 500
        out_headers: list[tuple[str, str]] = []
        chunks: list[bytes] = []
        sent = False

        async def receive() -> Message:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            await anyio.sleep_forever()
            return {"type": "http.disconnect"}  # pragma: no cover

        async def send(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                out_headers.extend((k.decode(), v.decode()) for k, v in message["headers"])
            elif message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))

        async def run() -> None:
            await self.app(scope, receive, send)

        anyio.run(run)
        resp = Response(status, out_headers, b"".join(chunks))
        self._store_cookies(resp)
        return resp

    def _store_cookies(self, resp: Response) -> None:
        for raw in resp.headers_all("set-cookie"):
            jar: SimpleCookie = SimpleCookie()
            jar.load(raw)
            for name, morsel in jar.items():
                if morsel["max-age"] == "0" or not morsel.value or morsel.value == '""':
                    self.cookies.pop(name, None)
                else:
                    self.cookies[name] = morsel.value

    def get(self, path: str, **kw: Any) -> Response:
        return self.request("GET", path, **kw)

    def post(self, path: str, **kw: Any) -> Response:
        return self.request("POST", path, **kw)

    def patch(self, path: str, **kw: Any) -> Response:
        return self.request("PATCH", path, **kw)

    def delete(self, path: str, **kw: Any) -> Response:
        return self.request("DELETE", path, **kw)
