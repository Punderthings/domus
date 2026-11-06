"""Alembic environment. Run through ``domus.migrate``, not the alembic CLI."""

from alembic import context

from domus.models import Base
from domus.services.search import include_in_migrations

config = context.config
target_metadata = Base.metadata


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is None:
        from domus.db import make_engine

        engine = make_engine(config.get_main_option("sqlalchemy.url") or "")
        with engine.connect() as conn:
            _run(conn)
        engine.dispose()
    else:
        _run(connection)


def _run(connection: object) -> None:
    context.configure(
        connection=connection,  # pyright: ignore[reportArgumentType]
        target_metadata=target_metadata,
        render_as_batch=True,  # SQLite needs batch mode for ALTER TABLE
        compare_type=True,
        include_name=include_in_migrations,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("offline migrations are not supported")
run_migrations_online()
