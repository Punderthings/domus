"""Helpers shared by the routers: pagination, audit logging, and updates."""

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy import Select
from sqlalchemy.orm import InstrumentedAttribute, Session

from domus.api.deps import PropertyContext
from domus.models import AuditLog
from domus.models.base import Base, IdMixin
from domus.models.enums import AccessLevel

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def paginate[M: IdMixin](
    db: Session,
    stmt: Select[M],
    id_column: InstrumentedAttribute[str],
    *,
    limit: int,
    cursor: str | None,
    level_of: Callable[[M], AccessLevel],
) -> tuple[list[tuple[M, AccessLevel]], str | None]:
    """Keyset pagination by id (UUIDv7, so time-ordered) that skips hidden rows.

    Rows the caller cannot see are filtered after the query, so this reads in
    chunks until the page is full.
    """
    limit = max(1, min(limit, MAX_LIMIT))
    out: list[tuple[M, AccessLevel]] = []
    after: str | None = cursor
    chunk = limit + 1
    while len(out) <= limit:
        q = stmt.order_by(id_column).limit(chunk)
        if after is not None:
            q = q.where(id_column > after)
        rows = list(db.scalars(q))
        for row in rows:
            level = level_of(row)
            if level is not AccessLevel.HIDDEN:
                out.append((row, level))
                if len(out) > limit:
                    break
        if len(rows) < chunk:
            break
        after = rows[-1].id
    if len(out) > limit:
        out = out[:limit]
        return out, out[-1][0].id
    return out, None


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if value is None or isinstance(value, bool | int | float | str):
        return value
    return str(value)


def audit(
    ctx: PropertyContext,
    action: str,
    target_type: str,
    target_id: str,
    diff: dict[str, Any] | None = None,
) -> None:
    ctx.db.add(
        AuditLog(
            at=datetime.now(UTC),
            user_id=ctx.user_id,
            property_id=ctx.property_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            diff={k: _jsonable(v) for k, v in diff.items()} if diff else None,
        )
    )


def apply_update(
    obj: Base, changes: BaseModel, *, user_id: str, exclude: set[str] | None = None
) -> dict[str, Any]:
    """Set the explicitly sent fields on ``obj``; return {field: [old, new]} for the audit log."""
    diff: dict[str, Any] = {}
    for key, value in changes.model_dump(exclude_unset=True, exclude=exclude).items():
        old = getattr(obj, key)
        if old != value:
            setattr(obj, key, value)
            diff[key] = [_jsonable(old), _jsonable(value)]
    if diff:
        obj.updated_by = user_id  # pyright: ignore[reportAttributeAccessIssue]
    return diff


def bad_request(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)


def access_str(level: AccessLevel) -> str:
    return level.value


def to_out[S: BaseModel](schema: type[S], obj: object, **extra: Any) -> S:
    """Build a response model from an ORM row plus computed fields such as ``access``."""
    data = {
        name: getattr(obj, name)
        for name in schema.model_fields
        if name not in extra and hasattr(obj, name)
    }
    data.update(extra)
    return schema.model_validate(data)
