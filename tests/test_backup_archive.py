""".hiotbak create, verify, and restore (data-storage-backup.md 4.1-4.3)."""

import hashlib
import json
import shutil
import zipfile
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, func, insert, select

from domus.backup import (
    ArchiveError,
    RestoreError,
    create_backup,
    export_directory,
    import_source,
    open_source,
    restore_merge,
    restore_replace,
    verify,
)
from domus.backup.blobs import blob_path
from domus.config import Settings
from domus.db import make_engine
from domus.migrate import head_revision, upgrade
from domus.models import Base


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data")


@pytest.fixture
def live(settings: Settings, sample_home: Path) -> Generator[Engine]:
    """The app's own SQLite database, loaded with the sample home."""
    eng = make_engine(settings.resolved_database_url())
    upgrade(eng)
    with open_source(sample_home) as source:
        import_source(eng, source)
    yield eng
    eng.dispose()


def _counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as conn:
        return {
            t.name: conn.execute(select(func.count()).select_from(t)).scalar_one()
            for t in Base.metadata.sorted_tables
        }


def _data_files(export_dir: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted((export_dir / "data").iterdir())}


def _wipe(settings: Settings) -> None:
    db = settings.sqlite_path
    for p in [db, db.with_name(db.name + "-wal"), db.with_name(db.name + "-shm")]:
        p.unlink(missing_ok=True)


def _rezip(src: Path, dest: Path, replace: dict[str, bytes]) -> None:
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dest, "w") as zout:
        for info in zin.infolist():
            zout.writestr(info.filename, replace.get(info.filename, zin.read(info.filename)))


def _add_blob(engine: Engine, settings: Settings, content: bytes, *, store: bool) -> str:
    sha = hashlib.sha256(content).hexdigest()
    with engine.begin() as conn:
        conn.execute(
            insert(Base.metadata.tables["blob"]).values(
                sha256=sha, size=len(content), mime_type="text/plain"
            )
        )
    if store:
        path = blob_path(settings.blobs_dir, sha)
        path.parent.mkdir(parents=True)
        path.write_bytes(content)
    return sha


def test_backup_manifest_and_layout(live: Engine, settings: Settings, tmp_path: Path) -> None:
    result = create_backup(live, tmp_path / "b.hiotbak", blobs_dir=settings.blobs_dir)
    m = result.manifest
    assert m.kind == "full"
    assert m.format_version == 1
    assert m.schema_version == head_revision()
    assert m.includes_audit_log and not m.includes_secrets and not m.encrypted
    assert m.row_counts["audit_log"] == 0
    assert "auth_session" not in m.row_counts and "api_token" not in m.row_counts
    with zipfile.ZipFile(result.path) as zf:
        names = set(zf.namelist())
        manifest = json.loads(zf.read("manifest.json"))
        for name, digest in manifest["sha256"].items():
            assert hashlib.sha256(zf.read(name)).hexdigest() == digest
    assert "db/domus.sqlite" in names
    assert names - {"manifest.json"} == set(manifest["sha256"])
    with open_source(result.path) as source:
        checked = verify(source)
    assert checked.ok, checked.errors
    assert checked.warnings == []
    assert sum(checked.row_counts.values()) == 62


def test_round_trip_backup_wipe_restore(live: Engine, settings: Settings, tmp_path: Path) -> None:
    before_counts = _counts(live)
    export_directory(live, tmp_path / "before")
    archive = create_backup(live, tmp_path / "b.hiotbak", blobs_dir=settings.blobs_dir).path
    live.dispose()
    _wipe(settings)

    result = restore_replace(settings, archive)
    assert result.safety_backup is None, "nothing to save after a wipe"
    after = make_engine(settings.resolved_database_url())
    try:
        assert _counts(after) == before_counts
        export_directory(after, tmp_path / "after")
    finally:
        after.dispose()
    assert _data_files(tmp_path / "after") == _data_files(tmp_path / "before")


def test_replace_saves_safety_backup(live: Engine, settings: Settings, tmp_path: Path) -> None:
    archive = create_backup(live, tmp_path / "b.hiotbak", blobs_dir=settings.blobs_dir).path
    live.dispose()
    result = restore_replace(settings, archive)
    assert result.safety_backup is not None
    assert result.safety_backup.parent == settings.backups_dir
    with open_source(result.safety_backup) as source:
        assert verify(source).ok
    assert not list(settings.data_dir.glob(".domus.sqlite.restore-*"))


def test_replace_dry_run_leaves_database_alone(
    live: Engine, settings: Settings, sample_home: Path
) -> None:
    live.dispose()
    _wipe(settings)
    result = restore_replace(settings, sample_home, dry_run=True)
    assert result.report.dry_run
    assert result.report.total().inserted == 62
    assert not settings.sqlite_path.exists()
    assert not settings.backups_dir.exists()


def test_merge_into_fresh_database(settings: Settings, sample_home: Path) -> None:
    result = restore_merge(settings, sample_home)
    assert result.report.total().inserted == 62
    assert result.verify.ok
    again = restore_merge(settings, sample_home, dry_run=True)
    assert again.report.total().skipped == 62


def test_tampered_file_fails_verify(live: Engine, settings: Settings, tmp_path: Path) -> None:
    archive = create_backup(live, tmp_path / "b.hiotbak", blobs_dir=settings.blobs_dir).path
    tampered = tmp_path / "t.hiotbak"
    with zipfile.ZipFile(archive) as zf:
        data = zf.read("data/tag.jsonl").replace(b"smart", b"SMART")
    _rezip(archive, tampered, {"data/tag.jsonl": data})
    with open_source(tampered) as source:
        result = verify(source)
    assert not result.ok
    assert any("data/tag.jsonl: SHA-256 does not match" in e for e in result.errors)
    with pytest.raises(RestoreError, match="failed verification"):
        restore_merge(settings, tampered)


def test_unlisted_file_fails_verify(live: Engine, settings: Settings, tmp_path: Path) -> None:
    archive = create_backup(live, tmp_path / "b.hiotbak", blobs_dir=settings.blobs_dir).path
    with zipfile.ZipFile(archive, "a") as zf:
        zf.writestr("data/user.jsonl.extra", b"")
        zf.writestr("blobs/" + "0" * 64, b"")
    with open_source(archive) as source:
        result = verify(source)
    assert any("not listed in the manifest hashes" in e for e in result.errors)
    assert any("ignoring unexpected file data/user.jsonl.extra" in w for w in result.warnings)


def _export_with_manifest(engine: Engine, dest: Path, **changes: object) -> Path:
    export_directory(engine, dest)
    manifest = json.loads((dest / "manifest.json").read_text())
    manifest.update(changes)
    (dest / "manifest.json").write_text(json.dumps(manifest))
    return dest


def test_newer_schema_version_is_refused(live: Engine, settings: Settings, tmp_path: Path) -> None:
    src = _export_with_manifest(live, tmp_path / "x", schema_version="9999_from_the_future")
    with open_source(src) as source:
        result = verify(source)
    assert any("newer than this app" in e for e in result.errors)
    with pytest.raises(RestoreError, match="newer than this app"):
        restore_merge(settings, src)


def test_unsupported_format_version_is_refused(live: Engine, tmp_path: Path) -> None:
    src = _export_with_manifest(live, tmp_path / "x", format_version=2)
    with open_source(src) as source:
        assert any("unsupported format_version 2" in e for e in verify(source).errors)


def test_row_count_mismatch_fails_verify(live: Engine, tmp_path: Path) -> None:
    src = _export_with_manifest(live, tmp_path / "x")
    manifest = json.loads((src / "manifest.json").read_text())
    manifest["row_counts"]["asset"] = 10
    (src / "manifest.json").write_text(json.dumps(manifest))
    with open_source(src) as source:
        assert "data/asset.jsonl: 9 rows, manifest says 10" in verify(source).errors


def test_sample_home_verifies(sample_home: Path) -> None:
    with open_source(sample_home) as source:
        result = verify(source)
    assert result.ok, result.errors
    assert result.manifest is not None and result.manifest.schema_version is None


def test_corrupt_snapshot_fails_verify(live: Engine, settings: Settings, tmp_path: Path) -> None:
    archive = create_backup(live, tmp_path / "b.hiotbak", blobs_dir=settings.blobs_dir).path
    bad = b"not a database" * 100
    with zipfile.ZipFile(archive) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    manifest["sha256"]["db/domus.sqlite"] = hashlib.sha256(bad).hexdigest()
    tampered = tmp_path / "t.hiotbak"
    _rezip(
        archive,
        tampered,
        {"db/domus.sqlite": bad, "manifest.json": json.dumps(manifest).encode()},
    )
    with open_source(tampered) as source:
        assert any(e.startswith("db/domus.sqlite:") for e in verify(source).errors)


@pytest.mark.parametrize(
    "name", ["../evil.txt", "/etc/passwd", "data/../../evil", "C:/evil", "data\\evil", "a//b"]
)
def test_zip_slip_entries_are_rejected(tmp_path: Path, name: str) -> None:
    bad = tmp_path / "bad.hiotbak"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("manifest.json", b"{}")
        zf.writestr(zipfile.ZipInfo(name), b"x")
    with pytest.raises(ArchiveError, match="unsafe path"):
        open_source(bad)


def test_zip_symlink_entry_is_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "bad.hiotbak"
    info = zipfile.ZipInfo("data/link")
    info.external_attr = 0o120777 << 16
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr(info, b"/etc/passwd")
    with pytest.raises(ArchiveError, match="symbolic links"):
        open_source(bad)


def test_zip_bomb_is_rejected(tmp_path: Path) -> None:
    bomb = tmp_path / "bomb.hiotbak"
    with zipfile.ZipFile(bomb, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("data/asset.jsonl", b"\0" * 1_000_000)
    assert bomb.stat().st_size < 10_000
    with pytest.raises(ArchiveError, match="expands to more than"):
        open_source(bomb, max_total_bytes=100_000)


def test_directory_symlink_is_rejected(tmp_path: Path, sample_home: Path) -> None:
    src = tmp_path / "src"
    shutil.copytree(sample_home, src)
    (src / "data" / "link.jsonl").symlink_to(tmp_path)
    with pytest.raises(ArchiveError, match="symbolic links"):
        open_source(src)


def test_not_a_zip_is_reported(tmp_path: Path) -> None:
    junk = tmp_path / "junk.hiotbak"
    junk.write_bytes(b"hello")
    with pytest.raises(ArchiveError, match="not a readable zip"):
        open_source(junk)


def test_blobs_are_backed_up_and_restored(live: Engine, settings: Settings, tmp_path: Path) -> None:
    stored = _add_blob(live, settings, b"manual page", store=True)
    missing = _add_blob(live, settings, b"lost photo", store=False)
    result = create_backup(live, tmp_path / "b.hiotbak", blobs_dir=settings.blobs_dir)
    assert result.missing_blobs == [missing]
    with zipfile.ZipFile(result.path) as zf:
        assert zf.read(f"blobs/{stored}") == b"manual page"
    with open_source(result.path) as source:
        checked = verify(source)
    assert checked.ok
    assert checked.missing_blobs == [missing]
    assert any(missing in w for w in checked.warnings)

    live.dispose()
    shutil.rmtree(settings.blobs_dir)
    restore_replace(settings, result.path)
    assert blob_path(settings.blobs_dir, stored).read_bytes() == b"manual page"


def test_blob_with_wrong_content_fails_verify(tmp_path: Path, sample_home: Path) -> None:
    src = tmp_path / "src"
    shutil.copytree(sample_home, src)
    (src / "blobs").mkdir()
    (src / "blobs" / ("a" * 64)).write_bytes(b"not matching")
    with open_source(src) as source:
        result = verify(source)
    assert any("does not match its SHA-256 name" in e for e in result.errors)


def test_backup_requires_current_schema(tmp_path: Path) -> None:
    eng = make_engine(f"sqlite:///{tmp_path / 'empty.sqlite'}")
    try:
        with pytest.raises(Exception, match="domus db upgrade"):
            create_backup(eng, tmp_path / "b.hiotbak", blobs_dir=tmp_path / "blobs")
    finally:
        eng.dispose()
    assert not (tmp_path / "b.hiotbak").exists()


def test_failed_replace_keeps_current_data(
    live: Engine, settings: Settings, sample_home: Path, tmp_path: Path
) -> None:
    before = _counts(live)
    src = tmp_path / "src"
    shutil.copytree(sample_home, src)
    (src / "data" / "property.jsonl").unlink()  # breaks every foreign key
    manifest = json.loads((src / "manifest.json").read_text())
    del manifest["row_counts"]["property"]
    (src / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(Exception, match="FOREIGN KEY"):
        restore_replace(settings, src)
    assert _counts(live) == before
    assert not list(settings.data_dir.glob(".domus.sqlite.restore-*"))


def test_created_at_is_utc_z(live: Engine, settings: Settings, tmp_path: Path) -> None:
    m = create_backup(live, tmp_path / "b.hiotbak", blobs_dir=settings.blobs_dir).manifest
    parsed = datetime.strptime(m.created_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    assert abs((datetime.now(UTC) - parsed).total_seconds()) < 60
