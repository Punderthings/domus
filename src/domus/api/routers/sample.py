"""Load the sample home from the web interface. Admin only.

The sample home is added as its own property, next to the caller's, and the
caller becomes its Admin. It can be loaded once: when Sample Home already has
members, nobody else can claim it this way. A Sample Home with no members (for
example one imported with ``domus restore --merge`` after setup) can be claimed.
"""

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from domus.api.deps import CurrentPrincipal, DbSession, Principal, active_memberships
from domus.api.routers.auth import SettingsDep
from domus.api.schemas import SampleDataStatus
from domus.models import AuditLog, Membership, Property
from domus.models.enums import Role
from domus.services.sample import SampleDataError, load_sample, sample_dir, sample_property_id

router = APIRouter(tags=["sample"])


def _require_admin(db: Session, principal: Principal) -> None:
    """The caller must be an Admin of at least one property."""
    if not any(m.role == Role.ADMIN.value for m in active_memberships(db, principal.user.id)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Requires the admin role")


def _member_count(db: Session, property_id: str) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(Membership)
            .where(Membership.property_id == property_id, Membership.deleted_at.is_(None))
        )
        or 0
    )


def _is_taken(db: Session, property_id: str) -> bool:
    prop = db.get(Property, property_id)
    if prop is None:
        return False
    return prop.deleted_at is not None or _member_count(db, property_id) > 0


@router.get("/sample-data")
def sample_data_status(
    db: DbSession, principal: CurrentPrincipal, settings: SettingsDep
) -> SampleDataStatus:
    """Whether this install ships the sample home, and whether it is already loaded."""
    _require_admin(db, principal)
    path = sample_dir(settings)
    if path is None:
        return SampleDataStatus(available=False, loaded=False, property_id=None)
    try:
        property_id = sample_property_id(path)
    except SampleDataError:
        return SampleDataStatus(available=False, loaded=False, property_id=None)
    return SampleDataStatus(
        available=True, loaded=_is_taken(db, property_id), property_id=property_id
    )


@router.post("/sample-data", status_code=status.HTTP_201_CREATED)
def load_sample_data(
    request: Request, db: DbSession, principal: CurrentPrincipal, settings: SettingsDep
) -> SampleDataStatus:
    """Add the sample home as a new property, with the caller as its Admin."""
    _require_admin(db, principal)
    path = sample_dir(settings)
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This install has no sample data")
    try:
        property_id = sample_property_id(path)
    except SampleDataError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc
    if _is_taken(db, property_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "The sample home is already loaded")
    # The import writes on its own connection; end this session's transaction
    # first so SQLite never sees two writers from one request.
    db.commit()
    try:
        load_sample(request.app.state.engine, path, settings)
    except SampleDataError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc
    # Another Admin may have claimed it while the import ran.
    if _member_count(db, property_id) > 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "The sample home is already loaded")
    db.add_all(
        [
            Membership(
                user_id=principal.user.id,
                property_id=property_id,
                role=Role.ADMIN.value,
                created_by=principal.user.id,
            ),
            AuditLog(
                user_id=principal.user.id,
                property_id=property_id,
                action="load_sample",
                target_type="property",
                target_id=property_id,
            ),
        ]
    )
    try:
        db.flush()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "The sample home is already loaded") from exc
    return SampleDataStatus(available=True, loaded=True, property_id=property_id)
