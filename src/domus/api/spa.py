"""Serve the built front end (src/frontend, built into ``domus/static``).

Real files (``/assets/...``, ``/favicon.svg``) are served as they are; any other
GET outside the API returns ``index.html``, so the browser app's own routes
(``/devices/<id>``) work on reload. Unknown ``/api/...`` paths still get the
API's JSON 404. Nothing is served when the front end hasn't been built.
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from starlette.responses import FileResponse

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# Vite inlines no scripts, so only self-hosted scripts run. Mantine sets inline
# style attributes, which needs 'unsafe-inline' for styles only.
CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)

# Paths the app owns that must never fall back to index.html.
RESERVED_PREFIXES = ("api/", "calendar.ics")


def _headers(cache: str) -> dict[str, str]:
    return {
        "Cache-Control": cache,
        "Content-Security-Policy": CONTENT_SECURITY_POLICY,
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "same-origin",
    }


def resolve_static(static_dir: Path, path: str) -> Path | None:
    """Return the file for a URL path inside ``static_dir``, or None.

    Rejects anything that would escape the directory, such as ``../`` or an
    absolute path, and anything that isn't a regular file.
    """
    root = static_dir.resolve()
    candidate = (root / path).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        return None
    return candidate


def mount_spa(app: FastAPI, static_dir: Path = STATIC_DIR) -> bool:
    """Add the front end routes to ``app``. Call after every API router.

    Returns False, and adds nothing, when ``static_dir`` has no ``index.html``.
    """
    index = static_dir / "index.html"
    if not index.is_file():
        return False

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def spa(path: str) -> FileResponse:  # pyright: ignore[reportUnusedFunction]
        if path.startswith(RESERVED_PREFIXES):
            raise HTTPException(status_code=404, detail="Not Found")
        file = resolve_static(static_dir, path) if path else None
        if file is not None and file != index.resolve():
            # Vite puts a content hash in every file name under assets/.
            immutable = path.startswith("assets/")
            cache = "public, max-age=31536000, immutable" if immutable else "no-cache"
            return FileResponse(file, headers=_headers(cache))
        return FileResponse(index, headers=_headers("no-cache"))

    return True
