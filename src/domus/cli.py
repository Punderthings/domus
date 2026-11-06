"""The ``domus`` command line interface.

Every command works with the web server stopped and without Home Assistant.
"""

from typing import Annotated

import typer

from domus.config import get_settings

app = typer.Typer(help="Domus home inventory and maintenance helper.", no_args_is_help=True)
db_app = typer.Typer(help="Database commands.", no_args_is_help=True)
app.add_typer(db_app, name="db")


@db_app.command("upgrade")
def db_upgrade() -> None:
    """Create or migrate the database to the latest schema."""
    from domus.db import make_engine
    from domus.migrate import upgrade

    settings = get_settings()
    engine = make_engine(settings.resolved_database_url())
    upgrade(engine)
    engine.dispose()
    typer.echo("Database is up to date.")


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Interface to listen on.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="TCP port.")] = 8000,
) -> None:
    """Run the web server (migrates the database first)."""
    import uvicorn

    uvicorn.run("domus.api.app:create_app", factory=True, host=host, port=port)


def main() -> None:
    app()
