from pathlib import Path

from sqlalchemy import Engine, inspect, text

from domus.db import make_engine
from domus.migrate import current_revision, head_revision, upgrade
from domus.models import Base
from domus.services.search import include_in_migrations


def test_upgrade_creates_every_model_table(engine: Engine) -> None:
    tables = set(inspect(engine).get_table_names())
    assert set(Base.metadata.tables) <= tables
    assert current_revision(engine) == head_revision()


def test_upgrade_is_idempotent(engine: Engine) -> None:
    upgrade(engine)
    assert current_revision(engine) == head_revision()


def test_migration_matches_models(engine: Engine) -> None:
    """Autogenerate against the migrated DB finds nothing: models and migrations agree."""
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext

    with engine.connect() as conn:
        ctx = MigrationContext.configure(
            conn,
            opts={"compare_type": True, "include_name": include_in_migrations},
        )
        diff = compare_metadata(ctx, Base.metadata)
    assert diff == []


def test_sqlite_pragmas(engine: Engine) -> None:
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert conn.execute(text("PRAGMA busy_timeout")).scalar() == 5000


def test_make_engine_creates_parent_dir(tmp_path: Path) -> None:
    db = tmp_path / "nested" / "dir" / "x.sqlite"
    eng = make_engine(f"sqlite:///{db}")
    with eng.connect():
        pass
    eng.dispose()
    assert db.parent.is_dir()
