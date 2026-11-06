"""SQLite-only helpers: consistent snapshots and integrity checks."""

import sqlite3
from contextlib import closing
from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.engine import make_url

from domus.backup.errors import BackupError


def sqlite_file(url: str) -> Path | None:
    """The database file behind a SQLite URL, or None for other engines or ``:memory:``."""
    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite":
        return None
    if not parsed.database or parsed.database == ":memory:":
        return None
    return Path(parsed.database)


def is_sqlite(engine: Engine) -> bool:
    return engine.dialect.name == "sqlite"


def vacuum_into(engine: Engine, dest: Path) -> None:
    """Write a consistent copy of the live database to ``dest`` (which must not exist)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with engine.connect() as conn:
        auto = conn.execution_options(isolation_level="AUTOCOMMIT")
        auto.exec_driver_sql("VACUUM INTO ?", (str(dest),))


def integrity_check(path: Path) -> None:
    """Open ``path`` read-only and raise BackupError unless ``PRAGMA integrity_check`` is ok."""
    uri = f"{path.resolve().as_uri()}?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True)) as conn:
            rows = conn.execute("PRAGMA integrity_check").fetchall()
    except sqlite3.DatabaseError as exc:
        raise BackupError(f"{path.name} is not a valid SQLite database: {exc}") from exc
    if [tuple(r) for r in rows] != [("ok",)]:
        detail = "; ".join(str(r[0]) for r in rows[:5])
        raise BackupError(f"{path.name} failed integrity_check: {detail}")


def read_only_url(path: Path) -> str:
    """A SQLAlchemy URL that opens ``path`` read-only, leaving the file unchanged."""
    return f"sqlite:///{path.resolve().as_uri()}?mode=ro&uri=true"


def checkpoint(engine: Engine) -> None:
    """Fold the write-ahead log into the main file so it can be moved on its own."""
    with engine.connect() as conn:
        auto = conn.execution_options(isolation_level="AUTOCOMMIT")
        auto.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
