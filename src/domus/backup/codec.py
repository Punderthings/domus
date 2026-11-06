"""Convert rows to and from the JSONL format.

Dates are ``YYYY-MM-DD``, timestamps are ISO 8601 in UTC with a ``Z``, money
(``Numeric``) is a JSON number, and JSON columns are written as-is. Decoding
checks every value against its column type so a bad archive fails loudly.
"""

import json
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Integer,
    Numeric,
    String,
    Table,
)

from domus.backup.errors import ImportDataError
from domus.models.base import UTCDateTime


def format_datetime(value: datetime) -> str:
    """Format an aware timestamp as ISO 8601 UTC with a trailing ``Z``."""
    if value.tzinfo is None:
        raise ValueError("naive datetime cannot be exported")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def encode_value(value: object) -> object:
    """Turn one column value into its JSON form."""
    if isinstance(value, datetime):
        return format_datetime(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def column_order(table: Table) -> list[str]:
    """Key order for exported rows: primary key, timestamps, then the rest in model order.

    This matches the hand-written ``examples/sample-home`` files.
    """
    first = [c.name for c in table.primary_key.columns]
    first += [n for n in ("created_at", "updated_at") if n in table.c and n not in first]
    return first + [c.name for c in table.c if c.name not in first]


def encode_row(table: Table, row: Mapping[Any, Any]) -> dict[str, object]:
    """One row as a dict, keyed in :func:`column_order`."""
    return {name: encode_value(row[name]) for name in column_order(table)}


def dumps_row(obj: Mapping[str, object]) -> str:
    """Serialize one row as a single JSONL line (no trailing newline)."""
    return json.dumps(obj, ensure_ascii=False, allow_nan=False)


def _reject_constant(name: str) -> object:
    raise ValueError(f"{name} is not valid JSON")


def loads_row(line: str) -> dict[str, Any]:
    """Parse one JSONL line, which must be a JSON object."""
    obj: object = json.loads(line, parse_constant=_reject_constant)
    if not isinstance(obj, dict):
        raise ValueError("each line must be a JSON object")
    # JSON object keys are always strings.
    return cast(dict[str, Any], obj)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def decode_value(column: Column[Any], value: object) -> object:
    """Check ``value`` against ``column``'s type and convert it for the database."""
    if value is None:
        if not column.nullable:
            raise ValueError("may not be null")
        return None
    col_type = column.type
    if isinstance(col_type, UTCDateTime | DateTime):
        if not isinstance(value, str):
            raise ValueError("expected an ISO 8601 timestamp string")
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError("timestamp needs a UTC offset or Z")
        return parsed.astimezone(UTC)
    if isinstance(col_type, Date):
        if not isinstance(value, str):
            raise ValueError("expected a YYYY-MM-DD date string")
        return date.fromisoformat(value)
    if isinstance(col_type, Boolean):
        if not isinstance(value, bool):
            raise ValueError("expected true or false")
        return value
    if isinstance(col_type, Float):
        if not (_is_int(value) or isinstance(value, float)):
            raise ValueError("expected a number")
        return float(value)  # pyright: ignore[reportArgumentType]
    if isinstance(col_type, Numeric):
        if not (_is_int(value) or isinstance(value, float)):
            raise ValueError("expected a number")
        try:
            # repr() of a float is its shortest round-trip form: 49.99, not 49.98999...
            return Decimal(repr(value))
        except InvalidOperation as exc:
            raise ValueError("expected a number") from exc
    if isinstance(col_type, Integer):
        if not _is_int(value):
            raise ValueError("expected an integer")
        return value
    if isinstance(col_type, JSON):
        return value
    if isinstance(col_type, String):
        if not isinstance(value, str):
            raise ValueError("expected a string")
        return value
    raise ValueError(f"unsupported column type {col_type!r}")


def decode_row(table: Table, raw: Mapping[str, object], where: str) -> dict[str, object]:
    """Validate one incoming row and convert its values.

    Unknown columns are an error; missing columns are left out so the insert
    fills in the model defaults. ``where`` names the row in error messages.
    """
    unknown = sorted(set(raw) - set(table.c.keys()))
    if unknown:
        raise ImportDataError(f"{where}: unknown column(s) for {table.name}: {', '.join(unknown)}")
    missing_pk = [c.name for c in table.primary_key.columns if c.name not in raw]
    if missing_pk:
        raise ImportDataError(f"{where}: missing primary key column(s): {', '.join(missing_pk)}")
    out: dict[str, object] = {}
    for name, value in raw.items():
        try:
            out[name] = decode_value(table.c[name], value)
        except ValueError as exc:
            raise ImportDataError(f"{where}: column {name}: {exc}") from exc
    return out
