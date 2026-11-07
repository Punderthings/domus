"""Full backups from the web UI: create, list, and download ``.hiotbak`` archives.

A backup holds every property in this install, so only a user who is an Admin
of every property may use these endpoints. Restoring stays in the CLI
(``domus restore``), because it replaces the database under the running server.
"""

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import select

from domus.api.common import audit
from domus.api.deps import CurrentPrincipal, DbSession, PropertyContext, active_memberships
from domus.api.deps import get_settings as request_settings
from domus.api.schemas import BackupOut, Page
from domus.backup import BackupError, create_backup, default_backup_name
from domus.config import Settings
from domus.models import Property
from domus.models.enums import Role

router = APIRouter(prefix="/backups", tags=["backups"])

AppSettings = Annotated[Settings, Depends(request_settings)]

# What default_backup_name() and safety backups produce; nothing else is served.
BACKUP_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}\.hiotbak$")


def _install_admin(db: DbSession, principal: CurrentPrincipal) -> list[PropertyContext]:
    """The caller's Admin context in every property, or 403 if they lack any."""
    admin_of = {
        m.property_id: m for m in active_memberships(db, principal.user.id) if m.role == Role.ADMIN
    }
    all_ids = set(db.scalars(select(Property.id).where(Property.deleted_at.is_(None))))
    if not admin_of or not all_ids <= admin_of.keys():
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Backups include every property, so only an Admin of all of them can use them",
        )
    return [PropertyContext(db, principal, admin_of[pid]) for pid in sorted(all_ids)]


def _out(path: Path) -> BackupOut:
    stat = path.stat()
    return BackupOut(
        name=path.name,
        size_bytes=stat.st_size,
        modified_at=datetime.fromtimestamp(stat.st_mtime, UTC),
    )


def _backup_path(settings: Settings, name: str) -> Path:
    """Resolve a backup by file name, refusing anything outside ``backups_dir``."""
    if not BACKUP_NAME.fullmatch(name):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    root = settings.backups_dir.resolve()
    path = (root / name).resolve()
    if path.parent != root or not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return path


@router.get("")
def list_backups(
    db: DbSession, principal: CurrentPrincipal, settings: AppSettings
) -> Page[BackupOut]:
    """Backups in the data folder's ``backups/``, newest first."""
    _install_admin(db, principal)
    root = settings.backups_dir
    files = (
        [p for p in root.iterdir() if p.is_file() and BACKUP_NAME.fullmatch(p.name)]
        if root.is_dir()
        else []
    )
    items = sorted((_out(p) for p in files), key=lambda b: (b.modified_at, b.name), reverse=True)
    return Page(items=items)


@router.post("", status_code=status.HTTP_201_CREATED)
def make_backup(
    request: Request, db: DbSession, principal: CurrentPrincipal, settings: AppSettings
) -> BackupOut:
    """Write a full backup now, the same as ``domus backup create``."""
    contexts = _install_admin(db, principal)
    dest = settings.backups_dir / default_backup_name()
    if dest.exists():
        raise HTTPException(status.HTTP_409_CONFLICT, "A backup was just made; try again")
    try:
        result = create_backup(request.app.state.engine, dest, blobs_dir=settings.blobs_dir)
    except BackupError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc
    for ctx in contexts:
        audit(ctx, "create", "backup", result.path.name)
    out = _out(result.path)
    out.missing_files = len(result.missing_blobs)
    return out


@router.get(
    "/{name}",
    response_class=FileResponse,
    responses={200: {"content": {"application/zip": {}}}},
)
def download_backup(
    name: str, db: DbSession, principal: CurrentPrincipal, settings: AppSettings
) -> FileResponse:
    """Download one backup archive."""
    contexts = _install_admin(db, principal)
    path = _backup_path(settings, name)
    for ctx in contexts:
        audit(ctx, "download", "backup", path.name)
    return FileResponse(
        path,
        media_type="application/zip",
        filename=path.name,
        headers={"Cache-Control": "no-store"},
    )
