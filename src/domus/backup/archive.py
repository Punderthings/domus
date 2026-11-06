"""Write a full ``.hiotbak`` backup archive (data-storage-backup.md 4.1).

Layout::

    manifest.json        format and schema versions, row counts, SHA-256 of every file
    data/<table>.jsonl   engine-neutral export, the source of truth for restore
    db/domus.sqlite      consistent snapshot (SQLite only)
    blobs/<sha256>       every referenced blob found in the blob store

On SQLite the JSONL is read from the snapshot, so both views are of the same
moment. The archive is written to a temporary file and renamed into place.
"""

import os
import secrets
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import Engine, create_engine, select

import domus
from domus.backup.blobs import archive_name, blob_path
from domus.backup.export import file_digests, property_ids, require_current_schema, write_tables
from domus.backup.manifest import FORMAT_VERSION, MANIFEST_NAME, Manifest, utc_timestamp
from domus.backup.sqlite import integrity_check, is_sqlite, read_only_url, vacuum_into
from domus.backup.tables import export_tables
from domus.backup.verify import SNAPSHOT_NAME
from domus.models import Blob


@dataclass
class BackupResult:
    path: Path
    manifest: Manifest
    # Blobs the database refers to that were not found in the blob store.
    missing_blobs: list[str] = field(default_factory=list[str])


def default_backup_name() -> str:
    """``domus-YYYYMMDDTHHMMSSZ.hiotbak``."""
    stamp = utc_timestamp().replace("-", "").replace(":", "")
    return f"domus-{stamp}.hiotbak"


def _copy_blobs(engine: Engine, blobs_dir: Path, staging: Path) -> list[str]:
    """Copy each blob the database lists into ``staging/blobs``; return those not found."""
    with engine.connect() as conn:
        shas = list(conn.execute(select(Blob.__table__.c.sha256).order_by("sha256")).scalars())
    missing: list[str] = []
    for sha in shas:
        try:
            src = blob_path(blobs_dir, sha)
        except ValueError:
            missing.append(sha)
            continue
        if not src.is_file():
            missing.append(sha)
            continue
        dest = staging / archive_name(sha)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
    return missing


def _write_zip(staging: Path, manifest: Manifest, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(f".{output.name}.{secrets.token_hex(4)}.partial")
    try:
        with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(MANIFEST_NAME, manifest.to_json())
            for rel in sorted(manifest.sha256):
                zf.write(staging / rel, rel)
        os.replace(partial, output)
    finally:
        partial.unlink(missing_ok=True)


def create_backup(engine: Engine, output: Path, *, blobs_dir: Path) -> BackupResult:
    """Write a full backup of the database behind ``engine`` to ``output``."""
    schema = require_current_schema(engine)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix=".backup-") as tmp:
        staging = Path(tmp) / "archive"
        staging.mkdir()
        read_engine = engine
        if is_sqlite(engine):
            snapshot = staging / SNAPSHOT_NAME
            vacuum_into(engine, snapshot)
            integrity_check(snapshot)
            read_engine = create_engine(read_only_url(snapshot))
        try:
            with read_engine.connect() as conn, conn.begin():
                counts = write_tables(conn, staging, export_tables(full=True))
                pids = property_ids(conn)
            missing = _copy_blobs(read_engine, blobs_dir, staging)
        finally:
            if read_engine is not engine:
                read_engine.dispose()
        manifest = Manifest(
            format_version=FORMAT_VERSION,
            app_version=domus.__version__,
            schema_version=schema,
            created_at=utc_timestamp(),
            kind="full",
            property_ids=pids,
            row_counts=counts,
            includes_audit_log=True,
            sha256=file_digests(staging),
        )
        _write_zip(staging, manifest, output)
    return BackupResult(path=output, manifest=manifest, missing_blobs=missing)
