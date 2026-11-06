"""The ``domus`` command line interface.

Every command works with the web server stopped and without Home Assistant.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

from domus.config import get_settings

if TYPE_CHECKING:
    from domus.backup import ImportReport, VerifyResult

app = typer.Typer(help="Domus home inventory and maintenance helper.", no_args_is_help=True)
db_app = typer.Typer(help="Database commands.", no_args_is_help=True)
app.add_typer(db_app, name="db")
backup_app = typer.Typer(help="Backup archive commands.", no_args_is_help=True)
app.add_typer(backup_app, name="backup")


def _fail(message: str) -> typer.Exit:
    typer.echo(f"Error: {message}", err=True)
    return typer.Exit(code=1)


def _print_verify(result: VerifyResult) -> None:
    for warning in result.warnings:
        typer.echo(f"warning: {warning}", err=True)
    for error in result.errors:
        typer.echo(f"error: {error}", err=True)


def _print_report(report: ImportReport) -> None:
    for name, counts in report.tables.items():
        typer.echo(
            f"  {name}: {counts.inserted} inserted, {counts.updated} updated, "
            f"{counts.skipped} skipped"
        )
    total = report.total()
    typer.echo(
        f"Total: {total.inserted} inserted, {total.updated} updated, {total.skipped} skipped"
    )
    if report.dry_run:
        typer.echo("Dry run: no changes were saved.")


@backup_app.command("create")
def backup_create(
    output: Annotated[
        Path | None, typer.Option(help="Archive path (default: a dated file in backups/).")
    ] = None,
    kind: Annotated[str, typer.Option(help="Backup kind; only 'full' for now.")] = "full",
) -> None:
    """Write a full .hiotbak backup of the database and its files."""
    from domus.backup import BackupError, create_backup, default_backup_name
    from domus.db import make_engine

    if kind != "full":
        raise _fail(f"unsupported backup kind {kind!r}; only 'full' is available")
    settings = get_settings()
    dest = output or settings.backups_dir / default_backup_name()
    engine = make_engine(settings.resolved_database_url())
    try:
        result = create_backup(engine, dest, blobs_dir=settings.blobs_dir)
    except BackupError as exc:
        raise _fail(str(exc)) from exc
    finally:
        engine.dispose()
    for sha in result.missing_blobs:
        typer.echo(f"warning: blob {sha} not found in the blob store", err=True)
    typer.echo(f"Backup written to {result.path}")


@backup_app.command("verify")
def backup_verify(
    path: Annotated[Path, typer.Argument(help="A .hiotbak file or directory.")],
) -> None:
    """Check a backup's manifest, hashes, row counts, snapshot, and blobs."""
    from domus.backup import BackupError, open_source, verify

    try:
        with open_source(path, max_total_bytes=get_settings().backup_max_bytes) as source:
            result = verify(source)
    except BackupError as exc:
        raise _fail(str(exc)) from exc
    _print_verify(result)
    if not result.ok:
        raise _fail(f"{path} failed verification")
    typer.echo(f"{path} is OK ({sum(result.row_counts.values())} rows).")


@app.command()
def restore(
    path: Annotated[Path, typer.Argument(help="A .hiotbak file or directory.")],
    merge: Annotated[
        bool, typer.Option("--merge", help="Merge into the current data instead of replacing it.")
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Report what would change without saving.")
    ] = False,
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Replace without asking for confirmation.")
    ] = False,
) -> None:
    """Restore a backup. Stop the web server first."""
    from domus.backup import BackupError, restore_merge, restore_replace

    settings = get_settings()
    if not (merge or dry_run or yes):
        typer.confirm(
            "Replace ALL current data with this backup? (a safety copy is saved first)",
            abort=True,
        )
    try:
        if merge:
            result = restore_merge(settings, path, dry_run=dry_run)
        else:
            result = restore_replace(settings, path, dry_run=dry_run)
    except BackupError as exc:
        raise _fail(str(exc)) from exc
    _print_verify(result.verify)
    _print_report(result.report)
    if result.safety_backup is not None:
        typer.echo(f"Previous database saved to {result.safety_backup}")


@app.command("export")
def export_cmd(
    path: Annotated[Path, typer.Argument(help="A new or empty directory to write into.")],
) -> None:
    """Export every record as JSONL (manifest.json plus data/<table>.jsonl)."""
    from domus.backup import BackupError, export_directory
    from domus.db import make_engine

    engine = make_engine(get_settings().resolved_database_url())
    try:
        manifest = export_directory(engine, path)
    except BackupError as exc:
        raise _fail(str(exc)) from exc
    finally:
        engine.dispose()
    typer.echo(f"Exported {sum(manifest.row_counts.values())} rows to {path}")


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
