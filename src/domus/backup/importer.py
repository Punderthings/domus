"""Merge JSONL rows into a database (data-storage-backup.md 4.3, "Merge import").

Rows are upserted by primary key, parents before children. An incoming row
is inserted when its key is new, replaces the stored row when its
``updated_at`` is newer, and is skipped otherwise (so importing the same data
twice changes nothing). Columns an incoming row leaves out get the model
defaults on insert and keep their stored value on update. The whole import is
one transaction; a dry run reports the counts and rolls back.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, Engine, Table, and_, insert, select, update
from sqlalchemy.exc import IntegrityError

from domus.backup.codec import decode_row, loads_row
from domus.backup.errors import ImportDataError
from domus.backup.export import data_name, table_for_data_name
from domus.backup.source import BackupSource
from domus.backup.tables import importable_table, ordered_tables
from domus.services import search

Key = tuple[Any, ...]


@dataclass
class TableCounts:
    inserted: int = 0
    updated: int = 0
    skipped: int = 0


@dataclass
class ImportReport:
    """Per-table counts. ``dry_run`` means nothing was committed."""

    dry_run: bool = False
    tables: dict[str, TableCounts] = field(default_factory=dict[str, TableCounts])

    def total(self) -> TableCounts:
        out = TableCounts()
        for c in self.tables.values():
            out.inserted += c.inserted
            out.updated += c.updated
            out.skipped += c.skipped
        return out


def _read_rows(source: BackupSource, table: Table) -> list[dict[str, object]]:
    name = data_name(table.name)
    rows: list[dict[str, object]] = []
    seen: set[Key] = set()
    pk_names = [c.name for c in table.primary_key.columns]
    for lineno, line in enumerate(source.iter_lines(name), start=1):
        if not line.strip():
            continue
        where = f"{name} line {lineno}"
        try:
            raw = loads_row(line)
        except ValueError as exc:
            raise ImportDataError(f"{where}: {exc}") from exc
        row = decode_row(table, raw, where)
        key = tuple(row[n] for n in pk_names)
        if key in seen:
            raise ImportDataError(f"{where}: duplicate primary key {key}")
        seen.add(key)
        rows.append(row)
    return rows


def _parents_first(table: Table, rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Order rows so a self-referencing parent (asset.parent_asset_id) comes first."""
    self_refs = [fk.parent.name for fk in table.foreign_keys if fk.column.table is table]
    if not self_refs or len(table.primary_key.columns) != 1:
        return rows
    pk = next(iter(table.primary_key.columns)).name
    batch = {row[pk] for row in rows}
    placed: set[object] = set()
    ordered: list[dict[str, object]] = []
    pending = rows
    while pending:
        waiting: list[dict[str, object]] = []
        for row in pending:
            parents = ({row.get(col) for col in self_refs} & batch) - {row[pk]}
            if parents <= placed:
                ordered.append(row)
                placed.add(row[pk])
            else:
                waiting.append(row)
        if len(waiting) == len(pending):
            raise ImportDataError(f"{table.name}: circular parent references")
        pending = waiting
    return ordered


def _existing(conn: Connection, table: Table) -> dict[Key, datetime | None]:
    """Stored primary keys and their ``updated_at`` (None for tables without one)."""
    pk_cols = list(table.primary_key.columns)
    has_updated = "updated_at" in table.c
    cols = [*pk_cols, table.c.updated_at] if has_updated else pk_cols
    out: dict[Key, datetime | None] = {}
    for row in conn.execute(select(*cols)):
        values = tuple(row)
        if has_updated:
            out[values[:-1]] = values[-1]
        else:
            out[values] = None
    return out


def _is_newer(incoming: object, stored: datetime | None) -> bool:
    return isinstance(incoming, datetime) and stored is not None and incoming > stored


def _import_table(conn: Connection, table: Table, rows: list[dict[str, object]]) -> TableCounts:
    counts = TableCounts()
    pk_cols = list(table.primary_key.columns)
    existing = _existing(conn, table)
    for row in _parents_first(table, rows):
        key = tuple(row[c.name] for c in pk_cols)
        try:
            if key not in existing:
                conn.execute(insert(table).values(row))
                counts.inserted += 1
            elif _is_newer(row.get("updated_at"), existing[key]):
                match = and_(*(c == v for c, v in zip(pk_cols, key, strict=True)))
                changes = {k: v for k, v in row.items() if k not in {c.name for c in pk_cols}}
                conn.execute(update(table).where(match).values(changes))
                counts.updated += 1
            else:
                counts.skipped += 1
        except IntegrityError as exc:
            raise ImportDataError(f"{table.name} row {key}: {exc.orig}") from exc
    return counts


def source_tables(source: BackupSource) -> list[Table]:
    """The tables with a data file in ``source``, parents first. Unknown tables are an error."""
    present: set[str] = set()
    for name in source.names():
        table_name = table_for_data_name(name)
        if table_name is None:
            continue
        if importable_table(table_name) is None:
            raise ImportDataError(f"{name}: table {table_name} cannot be imported")
        present.add(table_name)
    return [t for t in ordered_tables() if t.name in present]


def import_source(engine: Engine, source: BackupSource, *, dry_run: bool = False) -> ImportReport:
    """Merge every data file in ``source`` into the database in one transaction."""
    tables = source_tables(source)
    report = ImportReport(dry_run=dry_run)
    with engine.connect() as conn:
        tx = conn.begin()
        try:
            for table in tables:
                report.tables[table.name] = _import_table(conn, table, _read_rows(source, table))
        except BaseException:
            tx.rollback()
            raise
        if dry_run:
            tx.rollback()
        else:
            # Core inserts bypass the ORM listener, so re-index everything.
            search.rebuild(conn)
            tx.commit()
    return report
