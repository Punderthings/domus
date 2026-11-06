"""Which tables a backup carries, and in what order (data-storage-backup.md 4.1)."""

from sqlalchemy import Table

from domus.models import Base

# Login sessions are never exported or imported.
NEVER_EXPORTED = frozenset({"auth_session"})
# API tokens are secrets: left out of every export, and refused on import so an
# archive cannot plant a token someone else knows.
SECRET_TABLES = frozenset({"api_token"})
# The audit log is only carried by full backups.
AUDIT_TABLES = frozenset({"audit_log"})

NOT_IMPORTABLE = NEVER_EXPORTED | SECRET_TABLES


def ordered_tables() -> list[Table]:
    """Every table, parents before children, so inserts never break a foreign key."""
    return list(Base.metadata.sorted_tables)


def export_tables(*, include_audit_log: bool) -> list[Table]:
    """The tables an export writes, in foreign-key-safe order."""
    skip = NOT_IMPORTABLE if include_audit_log else NOT_IMPORTABLE | AUDIT_TABLES
    return [t for t in ordered_tables() if t.name not in skip]


def importable_table(name: str) -> Table | None:
    """The table called ``name`` if a backup may carry it, otherwise None."""
    if name in NOT_IMPORTABLE:
        return None
    return Base.metadata.tables.get(name)
