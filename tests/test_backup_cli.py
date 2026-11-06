"""``domus backup``, ``domus restore``, and ``domus export`` through the Typer CLI."""

from collections.abc import Generator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from domus.cli import app
from domus.config import get_settings

runner = CliRunner()


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[Path]:
    """Point the CLI at an empty data directory."""
    path = tmp_path / "data"
    monkeypatch.setenv("DOMUS_DATA_DIR", str(path))
    monkeypatch.delenv("DOMUS_DATABASE_URL", raising=False)
    get_settings.cache_clear()
    yield path
    get_settings.cache_clear()


def test_restore_sample_home_merge_on_fresh_db(data_dir: Path, sample_home: Path) -> None:
    result = runner.invoke(app, ["restore", str(sample_home), "--merge"])
    assert result.exit_code == 0, result.output
    assert "Total: 62 inserted, 0 updated, 0 skipped" in result.output
    assert (data_dir / "domus.sqlite").exists()

    again = runner.invoke(app, ["restore", str(sample_home), "--merge", "--dry-run"])
    assert again.exit_code == 0, again.output
    assert "Total: 0 inserted, 0 updated, 62 skipped" in again.output
    assert "Dry run" in again.output


def test_backup_create_verify_restore(data_dir: Path, sample_home: Path, tmp_path: Path) -> None:
    assert runner.invoke(app, ["restore", str(sample_home), "--merge"]).exit_code == 0
    archive = tmp_path / "out.hiotbak"

    created = runner.invoke(app, ["backup", "create", "--output", str(archive)])
    assert created.exit_code == 0, created.output
    assert archive.is_file()

    checked = runner.invoke(app, ["backup", "verify", str(archive)])
    assert checked.exit_code == 0, checked.output
    assert "is OK (62 rows)" in checked.output

    restored = runner.invoke(app, ["restore", str(archive), "--yes"])
    assert restored.exit_code == 0, restored.output
    assert "Total: 62 inserted" in restored.output
    assert "Previous database saved to" in restored.output


def test_backup_create_default_path(data_dir: Path) -> None:
    assert runner.invoke(app, ["db", "upgrade"]).exit_code == 0
    result = runner.invoke(app, ["backup", "create"])
    assert result.exit_code == 0, result.output
    assert len(list((data_dir / "backups").glob("domus-*.hiotbak"))) == 1


def test_backup_create_rejects_other_kinds(data_dir: Path) -> None:
    result = runner.invoke(app, ["backup", "create", "--kind", "partial"])
    assert result.exit_code == 1
    assert "only 'full'" in result.output


def test_backup_create_needs_migrated_db(data_dir: Path) -> None:
    result = runner.invoke(app, ["backup", "create"])
    assert result.exit_code == 1
    assert "domus db upgrade" in result.output


def test_verify_reports_failure(data_dir: Path, tmp_path: Path) -> None:
    bad = tmp_path / "bad"
    bad.mkdir()
    result = runner.invoke(app, ["backup", "verify", str(bad)])
    assert result.exit_code == 1
    assert "manifest.json is missing" in result.output


def test_verify_missing_path(data_dir: Path, tmp_path: Path) -> None:
    result = runner.invoke(app, ["backup", "verify", str(tmp_path / "nope.hiotbak")])
    assert result.exit_code == 1
    assert "does not exist" in result.output


def test_full_restore_asks_for_confirmation(data_dir: Path, sample_home: Path) -> None:
    result = runner.invoke(app, ["restore", str(sample_home)], input="n\n")
    assert result.exit_code == 1
    assert not (data_dir / "domus.sqlite").exists()


def test_export_writes_jsonl_directory(data_dir: Path, sample_home: Path, tmp_path: Path) -> None:
    assert runner.invoke(app, ["restore", str(sample_home), "--merge"]).exit_code == 0
    out = tmp_path / "export"
    result = runner.invoke(app, ["export", str(out)])
    assert result.exit_code == 0, result.output
    assert "Exported 62 rows" in result.output
    assert (out / "manifest.json").is_file()
    assert (out / "data" / "asset.jsonl").is_file()
    assert runner.invoke(app, ["backup", "verify", str(out)]).exit_code == 0

    again = runner.invoke(app, ["export", str(out)])
    assert again.exit_code == 1
    assert "not empty" in again.output
