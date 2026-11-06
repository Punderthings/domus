"""Maintenance tasks, completing them, the service history, and the iCal feed."""

from datetime import UTC, date, datetime
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import select

from domus.api.common import DEFAULT_LIMIT, apply_update, audit, bad_request, paginate, to_out
from domus.api.deps import (
    CurrentPrincipal,
    DbSession,
    PropertyContext,
    active_memberships,
    not_found,
    property_context,
    token_principal,
)
from domus.api.schemas import (
    CompleteIn,
    CompleteOut,
    EventGuestOut,
    EventOut,
    Page,
    TaskIn,
    TaskOut,
    TaskUpdate,
)
from domus.models import Area, Asset, Location, MaintenanceEvent, MaintenanceTask, Property
from domus.models.enums import AccessLevel, Role
from domus.services.access import at_least
from domus.services.ical import build_calendar
from domus.services.scheduling import Schedule, complete_task, compute_next_due, validate_schedule

router = APIRouter(prefix="/maintenance", tags=["maintenance"])
calendar_router = APIRouter(tags=["calendar"])

Limit = Annotated[int, Query(ge=1, le=200)]


def property_today(db: DbSession, property_id: str) -> date:
    prop = db.get(Property, property_id)
    try:
        tz = ZoneInfo(prop.timezone) if prop else UTC
    except ZoneInfoNotFoundError, ValueError:
        tz = UTC
    return datetime.now(tz).date()


def task_level(ctx: PropertyContext, task: MaintenanceTask) -> AccessLevel:
    db = ctx.db
    if task.asset_id is not None:
        asset = db.get(Asset, task.asset_id)
        if asset is None or asset.deleted_at is not None:
            return AccessLevel.HIDDEN
        return ctx.access.asset_level(asset)
    if task.location_id is not None:
        loc = db.get(Location, task.location_id)
        return ctx.access.location_level(loc) if loc else AccessLevel.HIDDEN
    return ctx.access.default_level()


def _get_task(db: DbSession, task_id: str) -> MaintenanceTask:
    t = db.get(MaintenanceTask, task_id)
    if t is None or t.deleted_at is not None:
        raise not_found()
    return t


def _check_target(ctx: PropertyContext, asset_id: str | None, location_id: str | None) -> None:
    """The task's asset or location must be in this property and manageable by the caller."""
    if asset_id is not None:
        asset = ctx.db.get(Asset, asset_id)
        if asset is None or asset.deleted_at is not None or asset.property_id != ctx.property_id:
            raise bad_request("asset_id not found in this property")
        ctx.require_level(ctx.access.asset_level(asset), AccessLevel.MANAGE)
    if location_id is not None:
        loc = ctx.db.get(Location, location_id)
        area = ctx.db.get(Area, loc.area_id) if loc else None
        if loc is None or area is None or area.property_id != ctx.property_id:
            raise bad_request("location_id not found in this property")
        ctx.require_level(ctx.access.area_level(area), AccessLevel.MANAGE)


def _validate(schedule: Schedule) -> None:
    try:
        validate_schedule(schedule)
    except ValueError as exc:
        raise bad_request(str(exc)) from exc


@router.get("/tasks")
def list_tasks(
    db: DbSession,
    principal: CurrentPrincipal,
    property_id: str | None = None,
    asset_id: str | None = None,
    due_before: date | None = None,
    active: bool | None = True,
    limit: Limit = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> Page[TaskOut]:
    """Tasks in the property. ``due_before`` is exclusive; overdue tasks are included."""
    ctx = property_context(db, principal, property_id)
    stmt = select(MaintenanceTask).where(
        MaintenanceTask.property_id == ctx.property_id, MaintenanceTask.deleted_at.is_(None)
    )
    if asset_id is not None:
        stmt = stmt.where(MaintenanceTask.asset_id == asset_id)
    if due_before is not None:
        stmt = stmt.where(MaintenanceTask.next_due < due_before)
    if active is not None:
        stmt = stmt.where(MaintenanceTask.active.is_(active))
    rows, nxt = paginate(
        db,
        stmt,
        MaintenanceTask.id,
        limit=limit,
        cursor=cursor,
        level_of=lambda t: task_level(ctx, t),
    )
    return Page(items=[to_out(TaskOut, t, access=lv.value) for t, lv in rows], next_cursor=nxt)


@router.get("/tasks/{task_id}")
def get_task(task_id: str, db: DbSession, principal: CurrentPrincipal) -> TaskOut:
    task = _get_task(db, task_id)
    ctx = property_context(db, principal, task.property_id)
    level = task_level(ctx, task)
    ctx.require_level(level, AccessLevel.VIEW)
    return to_out(TaskOut, task, access=level.value)


@router.post("/tasks", status_code=status.HTTP_201_CREATED)
def create_task(body: TaskIn, db: DbSession, principal: CurrentPrincipal) -> TaskOut:
    ctx = property_context(db, principal, body.property_id)
    ctx.require_role(Role.MAINTAINER)
    _check_target(ctx, body.asset_id, body.location_id)
    schedule = Schedule(
        schedule_kind=body.schedule_kind,
        interval_value=body.interval_value,
        interval_unit=body.interval_unit,
        rrule=body.rrule,
        anchor_date=body.anchor_date,
    )
    _validate(schedule)
    task = MaintenanceTask(**body.model_dump(), created_by=ctx.user_id, updated_by=ctx.user_id)
    if task.next_due is None:
        task.next_due = compute_next_due(schedule, None, property_today(db, ctx.property_id))
    db.add(task)
    db.flush()
    audit(ctx, "create", "maintenance_task", task.id, {"title": task.title})
    return to_out(TaskOut, task, access=task_level(ctx, task).value)


@router.patch("/tasks/{task_id}")
def update_task(
    task_id: str, body: TaskUpdate, db: DbSession, principal: CurrentPrincipal
) -> TaskOut:
    task = _get_task(db, task_id)
    ctx = property_context(db, principal, task.property_id)
    ctx.require_role(Role.MAINTAINER)
    ctx.require_level(task_level(ctx, task), AccessLevel.MANAGE)
    diff = apply_update(task, body, user_id=ctx.user_id)
    _validate(Schedule.of(task))
    schedule_fields = {"schedule_kind", "interval_value", "interval_unit", "rrule", "anchor_date"}
    if diff.keys() & schedule_fields and "next_due" not in body.model_fields_set:
        task.next_due = compute_next_due(task, None, property_today(db, ctx.property_id))
    if diff:
        audit(ctx, "update", "maintenance_task", task.id, diff)
    return to_out(TaskOut, task, access=task_level(ctx, task).value)


@router.post("/tasks/{task_id}/complete")
def complete(
    task_id: str, body: CompleteIn, db: DbSession, principal: CurrentPrincipal
) -> CompleteOut:
    """Log work on a task (done, skipped, partial, failed) and reschedule it."""
    task = _get_task(db, task_id)
    ctx = property_context(db, principal, task.property_id)
    ctx.require_role(Role.RESIDENT)
    level = task_level(ctx, task)
    ctx.require_level(level, AccessLevel.VIEW)
    try:
        event = complete_task(
            db,
            task,
            performed_on=body.performed_on,
            outcome=body.outcome,
            cost=body.cost,
            currency=body.currency,
            notes=body.notes,
            performed_by=ctx.user_id,
        )
    except ValueError as exc:
        raise bad_request(str(exc)) from exc
    event.created_by = event.updated_by = ctx.user_id
    task.updated_by = ctx.user_id
    audit(ctx, "complete", "maintenance_task", task.id, {"outcome": body.outcome})
    return CompleteOut(
        event=EventOut.model_validate(event), task=to_out(TaskOut, task, access=level.value)
    )


@router.get("/events")
def list_events(
    db: DbSession,
    principal: CurrentPrincipal,
    property_id: str | None = None,
    task_id: str | None = None,
    asset_id: str | None = None,
    limit: Limit = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> Page[EventOut | EventGuestOut]:
    """The service history. Guests see dates and outcomes, never costs or notes."""
    ctx = property_context(db, principal, property_id)
    stmt = (
        select(MaintenanceEvent)
        .outerjoin(MaintenanceTask, MaintenanceTask.id == MaintenanceEvent.task_id)
        .outerjoin(Asset, Asset.id == MaintenanceEvent.asset_id)
        .where(
            MaintenanceEvent.deleted_at.is_(None),
            (MaintenanceTask.property_id == ctx.property_id)
            | (Asset.property_id == ctx.property_id),
        )
    )
    if task_id is not None:
        stmt = stmt.where(MaintenanceEvent.task_id == task_id)
    if asset_id is not None:
        stmt = stmt.where(MaintenanceEvent.asset_id == asset_id)

    def level_of(e: MaintenanceEvent) -> AccessLevel:
        if e.asset_id is not None:
            asset = db.get(Asset, e.asset_id)
            return ctx.access.asset_level(asset) if asset else AccessLevel.HIDDEN
        task = db.get(MaintenanceTask, e.task_id) if e.task_id else None
        return task_level(ctx, task) if task else ctx.access.default_level()

    rows, nxt = paginate(
        db, stmt, MaintenanceEvent.id, limit=limit, cursor=cursor, level_of=level_of
    )
    schema = EventGuestOut if ctx.is_guest else EventOut
    return Page(items=[schema.model_validate(e) for e, _ in rows], next_cursor=nxt)


@calendar_router.get(
    "/calendar.ics",
    response_class=Response,
    responses={200: {"content": {"text/calendar": {}}}},
)
def calendar_feed(
    db: DbSession, token: Annotated[str, Query(max_length=200)], property_id: str | None = None
) -> Response:
    """Upcoming maintenance as an iCalendar feed, for phone and desktop calendars.

    Calendar apps can't send headers, so the feed takes a personal access
    token with the ``calendar`` scope in the URL. It shows only what that
    token's owner can see.
    """
    now = datetime.now(UTC)
    principal = token_principal(db, token, now)
    if principal is None or "calendar" not in principal.scopes:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "A calendar token is required")
    if property_id is None and len(active_memberships(db, principal.user.id)) != 1:
        raise bad_request("property_id is required for this account")
    ctx = property_context(db, principal, property_id)
    prop = db.get(Property, ctx.property_id)
    if prop is None:
        raise not_found()
    tasks = [
        t
        for t in db.scalars(
            select(MaintenanceTask).where(
                MaintenanceTask.property_id == ctx.property_id,
                MaintenanceTask.deleted_at.is_(None),
                MaintenanceTask.active.is_(True),
                MaintenanceTask.next_due.is_not(None),
            )
        )
        if at_least(task_level(ctx, t), AccessLevel.VIEW)
    ]
    asset_ids = {t.asset_id for t in tasks if t.asset_id}
    names = {a.id: a.name for a in db.scalars(select(Asset).where(Asset.id.in_(asset_ids)))}
    body = build_calendar(prop, tasks, now=now, asset_names=names)
    return Response(
        body,
        media_type="text/calendar; charset=utf-8",
        headers={"Cache-Control": "private, max-age=300", "Referrer-Policy": "no-referrer"},
    )
