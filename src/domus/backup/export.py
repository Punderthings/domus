"""Write tables as JSONL: one JSON object per row, rows sorted by primary key."""

import hashlib
from pathlib import Path

from sqlalchemy import Connection, Engine, Table, select

import domus
from domus.backup.codec import dumps_row, encode_row
from domus.backup.errors import BackupError
from domus.backup.manifest import FORMAT_VERSION, MANIFEST_NAME, Manifest, utc_timestamp
from domus.backup.tables import export_tables
from domus.migrate import current_revision, head_revision
from domus.models import Property

DATA_DIR = "data"


def data_name(table_name: str) -> str:
    """The archive path for one table's JSONL file."""
    return f"{DATA_DIR}/{table_name}.jsonl"


def table_for_data_name(name: str) -> str | None:
    """``data/<table>.jsonl`` -> ``<table>``, or None for any other path."""
    prefix, suffix = f"{DATA_DIR}/", ".jsonl"
    if name.startswith(prefix) and name.endswith(suffix) and name.count("/") == 1:
        return name[len(prefix) : -len(suffix)]
    return None


def require_current_schema(engine: Engine) -> str:
    """The database's Alembic revision, which must be the latest one."""
    current, head = current_revision(engine), head_revision()
    if current != head:
        raise BackupError(
            f"database schema is {current or 'empty'}, expected {head}; run 'domus db upgrade'"
        )
    return head


def write_table(conn: Connection, table: Table, path: Path) -> int:
    """Write every row of ``table`` to ``path``; return the row count."""
    query = select(table).order_by(*table.primary_key.columns)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as out:
        for row in conn.execute(query).mappings():
            out.write(dumps_row(encode_row(table, row)))
            out.write("\n")
            count += 1
    return count


def write_tables(conn: Connection, root: Path, tables: list[Table]) -> dict[str, int]:
    """Write ``root/data/<table>.jsonl`` for each table; return row counts by table."""
    (root / DATA_DIR).mkdir(parents=True, exist_ok=True)
    return {t.name: write_table(conn, t, root / data_name(t.name)) for t in tables}


def property_ids(conn: Connection) -> list[str]:
    """Every property id in the database, sorted."""
    table = Property.__table__
    return list(conn.execute(select(table.c.id).order_by(table.c.id)).scalars())


def file_digests(root: Path) -> dict[str, str]:
    """SHA-256 of every file under ``root`` except the manifest, by relative path."""
    digests: dict[str, str] = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        if rel == MANIFEST_NAME:
            continue
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            while chunk := fh.read(1024 * 1024):
                digest.update(chunk)
        digests[rel] = digest.hexdigest()
    return digests


def export_directory(engine: Engine, dest: Path) -> Manifest:
    """Write an unzipped export (``manifest.json`` plus ``data/``) to ``dest``.

    This is the ``domus export`` layout, the same as ``examples/sample-home``:
    every exportable table except the audit log, marked ``kind: partial``.
    """
    if dest.exists() and any(dest.iterdir()):
        raise BackupError(f"{dest} exists and is not empty")
    schema = require_current_schema(engine)
    dest.mkdir(parents=True, exist_ok=True)
    with engine.connect() as conn, conn.begin():
        counts = write_tables(conn, dest, export_tables(full=False))
        pids = property_ids(conn)
    manifest = Manifest(
        format_version=FORMAT_VERSION,
        app_version=domus.__version__,
        schema_version=schema,
        created_at=utc_timestamp(),
        kind="partial",
        property_ids=pids,
        row_counts=counts,
        includes_audit_log=False,
        sha256=file_digests(dest),
    )
    (dest / MANIFEST_NAME).write_bytes(manifest.to_json())
    return manifest
