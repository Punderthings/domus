"""Checks for uploaded files (master plan section 5, data-storage-backup.md 3.3).

The type of an upload comes from its first bytes, never from the client's
``Content-Type`` or file name, and only the types in ``UPLOAD_MIME_TYPES`` are
accepted.
"""

from pathlib import Path

from domus.models.enums import UPLOAD_MIME_TYPES

SNIFF_BYTES = 16


def sniff_mime(head: bytes) -> str | None:
    """The MIME type for a file starting with ``head``, or None if it is not allowed."""
    found: str | None = None
    if head.startswith(b"\xff\xd8\xff"):
        found = "image/jpeg"
    elif head.startswith(b"\x89PNG\r\n\x1a\n"):
        found = "image/png"
    elif head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        found = "image/webp"
    elif head[:6] in (b"GIF87a", b"GIF89a"):
        found = "image/gif"
    elif head.startswith(b"%PDF-"):
        found = "application/pdf"
    return found if found in UPLOAD_MIME_TYPES else None


def sniff_file(path: Path) -> str | None:
    with path.open("rb") as fh:
        return sniff_mime(fh.read(SNIFF_BYTES))


def safe_filename(name: str | None) -> str | None:
    """Keep only the last path part of a client-supplied name, without control characters."""
    if not name:
        return None
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = "".join(ch for ch in base if ch.isprintable() and ch not in '"').strip()
    return cleaned[:300] or None
