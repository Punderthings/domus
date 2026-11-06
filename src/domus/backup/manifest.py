"""The ``manifest.json`` at the root of every backup or export (data-storage-backup.md 4.1)."""

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

from domus.backup.errors import ArchiveError

MANIFEST_NAME = "manifest.json"
FORMAT_VERSION = 1
SUPPORTED_FORMAT_VERSIONS = frozenset({FORMAT_VERSION})
KINDS = frozenset({"full", "partial", "handover"})


def utc_timestamp(when: datetime | None = None) -> str:
    """``when`` (default now) as ``YYYY-MM-DDTHH:MM:SSZ``."""
    moment = (when or datetime.now(UTC)).astimezone(UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class Manifest:
    """What an archive holds. ``sha256`` maps each archive path to its hex digest."""

    format_version: int
    app_version: str | None
    schema_version: str | None
    created_at: str
    kind: str
    property_ids: list[str]
    row_counts: dict[str, int]
    includes_audit_log: bool
    includes_secrets: bool = False
    encrypted: bool = False
    sha256: dict[str, str] = field(default_factory=dict[str, str])

    def to_json(self) -> bytes:
        """The manifest as pretty-printed UTF-8 JSON with a trailing newline."""
        return (json.dumps(asdict(self), indent=2, ensure_ascii=False) + "\n").encode()


def _get(obj: dict[str, Any], key: str, kind: type | tuple[type, ...], *, optional: bool) -> Any:
    if key not in obj:
        if optional:
            return None
        raise ArchiveError(f"manifest is missing {key!r}")
    value = obj[key]
    if value is None and optional:
        return None
    if not isinstance(value, kind) or (isinstance(value, bool) and kind is int):
        raise ArchiveError(f"manifest field {key!r} has the wrong type")
    return value


def _str_map(obj: object, key: str) -> dict[str, Any]:
    if obj is None:
        return {}
    if not isinstance(obj, dict):
        raise ArchiveError(f"manifest field {key!r} must be an object")
    # JSON object keys are always strings.
    return cast(dict[str, Any], obj)


def parse_manifest(data: bytes) -> Manifest:
    """Parse and type-check a manifest. Unknown extra fields are ignored."""
    try:
        raw: object = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArchiveError(f"manifest.json is not valid JSON: {exc}") from exc
    if raw is None:
        raise ArchiveError("manifest.json must be a JSON object")
    obj = _str_map(raw, "manifest.json")

    counts: dict[str, int] = {}
    for table, n in _str_map(obj.get("row_counts"), "row_counts").items():
        if not isinstance(n, int) or isinstance(n, bool) or n < 0:
            raise ArchiveError(f"row_counts[{table!r}] must be a non-negative integer")
        counts[table] = n
    digests: dict[str, str] = {}
    for path, digest in _str_map(obj.get("sha256"), "sha256").items():
        if not isinstance(digest, str):
            raise ArchiveError(f"sha256[{path!r}] must be a string")
        digests[path] = digest.lower()
    ids: object = obj.get("property_ids") or []
    if not isinstance(ids, list) or not all(isinstance(p, str) for p in cast(list[object], ids)):
        raise ArchiveError("property_ids must be a list of strings")

    return Manifest(
        format_version=_get(obj, "format_version", int, optional=False),
        app_version=_get(obj, "app_version", str, optional=True),
        schema_version=_get(obj, "schema_version", str, optional=True),
        created_at=_get(obj, "created_at", str, optional=False),
        kind=_get(obj, "kind", str, optional=False),
        property_ids=list(cast(list[str], ids)),
        row_counts=counts,
        includes_audit_log=bool(_get(obj, "includes_audit_log", bool, optional=True)),
        includes_secrets=bool(_get(obj, "includes_secrets", bool, optional=True)),
        encrypted=bool(_get(obj, "encrypted", bool, optional=True)),
        sha256=digests,
    )
