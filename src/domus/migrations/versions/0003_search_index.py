"""Search index tables (data-storage-backup.md 2.5).

SQLite gets an FTS5 virtual table; PostgreSQL gets a table with generated
tsvector columns and a pg_trgm index. The SQL is copied here, not imported,
so this migration keeps working when ``domus.services.search`` changes.
The index starts empty; the app fills it on startup (``search.ensure_built``).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-06
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SQLITE_UP = (
    "CREATE VIRTUAL TABLE search_fts USING fts5("
    "kind UNINDEXED, ref_id UNINDEXED, property_id UNINDEXED, "
    "title, public_text, private_text, "
    "tokenize = 'unicode61 remove_diacritics 2')",
)
SQLITE_DOWN = ("DROP TABLE IF EXISTS search_fts",)

_PUBLIC_TSV = (
    "setweight(to_tsvector('simple', title), 'A') || "
    "setweight(to_tsvector('simple', public_text), 'B')"
)
POSTGRES_UP = (
    # pg_trgm is a trusted extension (PostgreSQL 13+), so a database owner
    # without superuser rights can create it.
    "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    "CREATE TABLE search_doc ("
    "kind VARCHAR(16) NOT NULL, "
    "ref_id VARCHAR(36) NOT NULL, "
    "property_id VARCHAR(36) NOT NULL, "
    "title TEXT NOT NULL, "
    "public_text TEXT NOT NULL, "
    "private_text TEXT NOT NULL, "
    f"public_tsv TSVECTOR GENERATED ALWAYS AS ({_PUBLIC_TSV}) STORED, "
    f"all_tsv TSVECTOR GENERATED ALWAYS AS ({_PUBLIC_TSV} || "
    "setweight(to_tsvector('simple', private_text), 'C')) STORED, "
    "CONSTRAINT pk_search_doc PRIMARY KEY (kind, ref_id))",
    "CREATE INDEX ix_search_doc_property ON search_doc (property_id)",
    "CREATE INDEX ix_search_doc_public_tsv ON search_doc USING gin (public_tsv)",
    "CREATE INDEX ix_search_doc_all_tsv ON search_doc USING gin (all_tsv)",
    "CREATE INDEX ix_search_doc_title_trgm ON search_doc USING gin (title gin_trgm_ops)",
)
# The extension is left in place: other objects may use it.
POSTGRES_DOWN = ("DROP TABLE IF EXISTS search_doc",)


def _run(statements: Sequence[str]) -> None:
    for sql in statements:
        op.execute(sql)


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        _run(SQLITE_UP)
    elif dialect == "postgresql":
        _run(POSTGRES_UP)
    else:
        raise RuntimeError(f"no search index for the {dialect} database engine")


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    _run(SQLITE_DOWN if dialect == "sqlite" else POSTGRES_DOWN)
