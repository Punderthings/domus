"""Restore a backup: merge it in, or replace the database (data-storage-backup.md 4.3).

Both paths verify the archive first and refuse it on any error. A full
restore on SQLite builds a new database beside the live one, imports the JSONL
into it, and only then swaps the file with ``os.replace``, so a failure at any
step leaves the current data untouched. Run restores with the web server
stopped.
"""

import secrets
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine, func, select

from domus.backup.archive import create_backup
from domus.backup.blobs import install_blobs
from domus.backup.errors import RestoreError
from domus.backup.importer import ImportReport, import_source
from domus.backup.manifest import utc_timestamp
from domus.backup.source import BackupSource, open_source
from domus.backup.sqlite import checkpoint, sqlite_file, vacuum_into
from domus.backup.verify import VerifyResult, verify
from domus.config import Settings
from domus.db import make_engine
from domus.migrate import current_revision, head_revision, upgrade
from domus.models import Base


@dataclass
class RestoreResult:
    report: ImportReport
    verify: VerifyResult
    # Where the pre-restore copy of the old database went (full restore only).
    safety_backup: Path | None = None


def _verified(source: BackupSource) -> VerifyResult:
    result = verify(source)
    if not result.ok:
        raise RestoreError("backup failed verification:\n  " + "\n  ".join(result.errors))
    return result


def _sidecars(path: Path) -> list[Path]:
    return [path.with_name(path.name + suffix) for suffix in ("-wal", "-shm", "-journal")]


def _is_empty(engine: Engine) -> bool:
    with engine.connect() as conn:
        for table in Base.metadata.sorted_tables:
            if conn.execute(select(func.count()).select_from(table)).scalar_one():
                return False
    return True


def safety_backup(settings: Settings, db_path: Path) -> Path | None:
    """Copy the current SQLite database to ``backups_dir`` before it is replaced.

    A database at the latest schema gets a full ``.hiotbak``; anything else gets
    a raw ``VACUUM INTO`` copy. Returns None when there is no database yet.
    """
    if not db_path.exists():
        return None
    stamp = utc_timestamp().replace("-", "").replace(":", "")
    engine = make_engine(f"sqlite:///{db_path}")
    try:
        if current_revision(engine) == head_revision():
            dest = settings.backups_dir / f"domus-pre-restore-{stamp}.hiotbak"
            return create_backup(engine, dest, blobs_dir=settings.blobs_dir).path
        dest = settings.backups_dir / f"domus-pre-restore-{stamp}.sqlite"
        vacuum_into(engine, dest)
        return dest
    finally:
        engine.dispose()


def restore_merge(settings: Settings, path: Path, *, dry_run: bool = False) -> RestoreResult:
    """Merge a backup or export into the current database (migrating it first)."""
    with open_source(path, max_total_bytes=settings.backup_max_bytes) as source:
        checked = _verified(source)
        engine = make_engine(settings.resolved_database_url())
        try:
            upgrade(engine)
            report = import_source(engine, source, dry_run=dry_run)
        finally:
            engine.dispose()
        if not dry_run:
            install_blobs(source, settings.blobs_dir)
    return RestoreResult(report=report, verify=checked)


def _replace_sqlite(
    settings: Settings, source: BackupSource, db_path: Path, *, dry_run: bool
) -> tuple[ImportReport, Path | None]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_db = db_path.with_name(f".{db_path.name}.restore-{secrets.token_hex(4)}")
    try:
        engine = make_engine(f"sqlite:///{tmp_db}")
        try:
            upgrade(engine)
            report = import_source(engine, source)
            checkpoint(engine)
        finally:
            engine.dispose()
        if dry_run:
            report.dry_run = True
            return report, None
        saved = safety_backup(settings, db_path)
        # A stale write-ahead log must never be replayed into the new file.
        for sidecar in _sidecars(db_path):
            sidecar.unlink(missing_ok=True)
        tmp_db.replace(db_path)
        install_blobs(source, settings.blobs_dir)
        return report, saved
    finally:
        for leftover in [tmp_db, *_sidecars(tmp_db)]:
            leftover.unlink(missing_ok=True)


def restore_replace(settings: Settings, path: Path, *, dry_run: bool = False) -> RestoreResult:
    """Replace the current database with the backup's contents.

    On SQLite the old database is saved to ``backups_dir`` first. On other
    engines the target must be empty; restoring over existing data is refused.
    """
    url = settings.resolved_database_url()
    with open_source(path, max_total_bytes=settings.backup_max_bytes) as source:
        checked = _verified(source)
        db_path = sqlite_file(url)
        if db_path is not None:
            report, saved = _replace_sqlite(settings, source, db_path, dry_run=dry_run)
            return RestoreResult(report=report, verify=checked, safety_backup=saved)
        if url.startswith("sqlite"):
            raise RestoreError("cannot replace an in-memory SQLite database")
        engine = make_engine(url)
        try:
            upgrade(engine)
            if not _is_empty(engine):
                raise RestoreError(
                    "the target database is not empty; a full restore on this engine "
                    "needs an empty database (or use --merge)"
                )
            report = import_source(engine, source, dry_run=dry_run)
        finally:
            engine.dispose()
        if not dry_run:
            install_blobs(source, settings.blobs_dir)
    return RestoreResult(report=report, verify=checked)
