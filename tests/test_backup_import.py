"""JSONL export and merge import (data-storage-backup.md 4.3)."""

import json
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from domus.backup import ImportDataError, export_directory, import_source, open_source
from domus.backup.codec import decode_row, encode_value, format_datetime
from domus.models import Area, Asset, Base, Location, Property

Rows = list[dict[str, Any]]
PROPERTY_ID = "01a1a901-5800-7001-8000-000000000001"


def _counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as conn:
        return {
            t.name: conn.execute(select(func.count()).select_from(t)).scalar_one()
            for t in Base.metadata.sorted_tables
        }


def _import_dir(engine: Engine, path: Path, *, dry_run: bool = False) -> Any:
    with open_source(path) as source:
        return import_source(engine, source, dry_run=dry_run)


def _copy_sample(sample_home: Path, dest: Path) -> Path:
    shutil.copytree(sample_home, dest)
    return dest


def _rewrite(path: Path, edit: Callable[[Rows], Rows]) -> None:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    rows = edit(rows)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_sample_home_import_matches_manifest(engine: Engine, sample_home: Path) -> None:
    manifest = json.loads((sample_home / "manifest.json").read_text())
    report = _import_dir(engine, sample_home)
    counts = _counts(engine)
    for table, expected in manifest["row_counts"].items():
        assert counts[table] == expected, table
        assert report.tables[table].inserted == expected, table
    assert report.total().updated == report.total().skipped == 0


def test_missing_columns_get_model_defaults(engine: Engine, sample_home: Path) -> None:
    _import_dir(engine, sample_home)
    with engine.connect() as conn:
        asset = conn.execute(select(Asset.__table__).limit(1)).mappings().one()
        area = conn.execute(select(Area.__table__).limit(1)).mappings().one()
    assert asset["created_by"] is None
    assert asset["deleted_at"] is None
    assert area["ha_area_id"] is None
    assert area["created_at"] == datetime(2026, 11, 5, tzinfo=UTC)


def test_omitted_non_null_column_uses_default(engine: Engine, tmp_path: Path) -> None:
    src = tmp_path / "src"
    (src / "data").mkdir(parents=True)
    (src / "manifest.json").write_text(
        json.dumps({"format_version": 1, "created_at": "x", "kind": "partial"})
    )
    row = {"id": PROPERTY_ID, "name": "Bare"}
    (src / "data" / "property.jsonl").write_text(json.dumps(row) + "\n")
    _import_dir(engine, src)
    with engine.connect() as conn:
        prop = conn.execute(select(Property.__table__)).mappings().one()
    assert prop["timezone"] == "UTC"
    assert prop["default_currency"] == "USD"
    assert prop["updated_at"] is not None


def test_reimport_is_idempotent(engine: Engine, sample_home: Path) -> None:
    _import_dir(engine, sample_home)
    report = _import_dir(engine, sample_home)
    total = report.total()
    assert total.inserted == total.updated == 0
    assert total.skipped == 62


def test_export_then_reimport_skips_everything(
    engine: Engine, sample_home: Path, tmp_path: Path
) -> None:
    _import_dir(engine, sample_home)
    before = _counts(engine)
    manifest = export_directory(engine, tmp_path / "export")
    assert manifest.kind == "partial"
    assert manifest.property_ids == [PROPERTY_ID]
    assert "audit_log" not in manifest.row_counts
    assert "api_token" not in manifest.row_counts
    assert "auth_session" not in manifest.row_counts
    report = _import_dir(engine, tmp_path / "export")
    assert report.total().inserted == report.total().updated == 0
    assert _counts(engine) == before


def test_partial_export_leaves_out_accounts(
    engine: Engine, sample_home: Path, tmp_path: Path
) -> None:
    """Exports handed to others never carry emails, password hashes, or the audit log."""
    from domus.models import Membership, User

    _import_dir(engine, sample_home)
    with Session(engine) as s:
        fake_hash = "$argon2id$not-a-real-hash"
        user = User(email="a@example.com", display_name="A", password_hash=fake_hash)
        s.add(user)
        s.flush()
        s.add(Membership(user_id=user.id, property_id=PROPERTY_ID, role="admin"))
        s.commit()
    export_directory(engine, tmp_path / "export")
    data = tmp_path / "export" / "data"
    for table in ("user", "membership", "audit_log"):
        assert not (data / f"{table}.jsonl").exists()
    assert "argon2id" not in "".join(p.read_text() for p in data.iterdir())


def test_export_shape_matches_sample(engine: Engine, sample_home: Path, tmp_path: Path) -> None:
    _import_dir(engine, sample_home)
    export_directory(engine, tmp_path / "export")
    line = (tmp_path / "export" / "data" / "asset.jsonl").read_text().splitlines()[0]
    row = json.loads(line)
    assert list(row)[:3] == ["id", "created_at", "updated_at"]
    assert row["created_at"] == "2026-11-05T00:00:00Z"
    assert row["install_date"] == "2021-03-14"
    assert row["purchase_price"] == 1899.0
    # Every value in the sample row survives the round trip unchanged.
    sample = json.loads((sample_home / "data" / "asset.jsonl").read_text().splitlines()[0])
    assert {k: row[k] for k in sample} == sample


def test_export_rows_sorted_by_primary_key(
    engine: Engine, sample_home: Path, tmp_path: Path
) -> None:
    _import_dir(engine, sample_home)
    export_directory(engine, tmp_path / "export")
    lines = (tmp_path / "export" / "data" / "asset_tag.jsonl").read_text().splitlines()
    keys = [(r["tag_id"], r["asset_id"]) for r in map(json.loads, lines)]
    assert keys == sorted(keys)


def test_export_refuses_non_empty_dir(engine: Engine, tmp_path: Path) -> None:
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "x").write_text("x")
    with pytest.raises(Exception, match="not empty"):
        export_directory(engine, tmp_path / "out")


def test_dry_run_changes_nothing(engine: Engine, sample_home: Path) -> None:
    report = _import_dir(engine, sample_home, dry_run=True)
    assert report.dry_run
    assert report.total().inserted == 62
    assert sum(_counts(engine).values()) == 0


def test_dry_run_on_populated_db_changes_nothing(
    engine: Engine, sample_home: Path, tmp_path: Path
) -> None:
    _import_dir(engine, sample_home)
    src = _copy_sample(sample_home, tmp_path / "src")

    def rename(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows[0] |= {"name": "Renamed", "updated_at": "2027-01-01T00:00:00Z"}
        return rows

    _rewrite(src / "data" / "property.jsonl", rename)
    report = _import_dir(engine, src, dry_run=True)
    assert report.tables["property"].updated == 1
    with engine.connect() as conn:
        assert conn.execute(select(Property.__table__.c.name)).scalar_one() == "Sample Home"


def test_newer_updated_at_wins_older_is_skipped(
    engine: Engine, sample_home: Path, tmp_path: Path
) -> None:
    _import_dir(engine, sample_home)
    src = _copy_sample(sample_home, tmp_path / "src")

    def edit(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows[0] |= {"name": "Newer", "updated_at": "2026-12-01T00:00:00Z"}
        rows[1] |= {"name": "Older", "updated_at": "2026-01-01T00:00:00Z"}
        rows[2] |= {"name": "Same time"}
        return rows

    _rewrite(src / "data" / "area.jsonl", edit)
    report = _import_dir(engine, src)
    assert report.tables["area"].updated == 1
    assert report.tables["area"].skipped == 3
    with engine.connect() as conn:
        names = set(conn.execute(select(Area.__table__.c.name)).scalars())
    assert "Newer" in names
    assert "Older" not in names
    assert "Same time" not in names


def test_unknown_column_is_rejected(engine: Engine, sample_home: Path, tmp_path: Path) -> None:
    src = _copy_sample(sample_home, tmp_path / "src")
    _rewrite(src / "data" / "tag.jsonl", lambda rows: [rows[0] | {"colour": "red"}, *rows[1:]])
    with pytest.raises(ImportDataError, match=r"tag\.jsonl line 1: unknown column.*colour"):
        _import_dir(engine, src)
    assert sum(_counts(engine).values()) == 0, "the whole import is one transaction"


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("is_critical", "yes", "expected true or false"),
        ("install_date", 20210314, "expected a YYYY-MM-DD date string"),
        ("created_at", "2026-11-05T00:00:00", "needs a UTC offset"),
        ("purchase_price", "1899", "expected a number"),
        ("name", None, "may not be null"),
    ],
)
def test_bad_values_are_rejected(
    engine: Engine, sample_home: Path, tmp_path: Path, column: str, value: object, message: str
) -> None:
    src = _copy_sample(sample_home, tmp_path / "src")
    _rewrite(src / "data" / "asset.jsonl", lambda rows: [rows[0] | {column: value}, *rows[1:]])
    with pytest.raises(ImportDataError, match=message):
        _import_dir(engine, src)


def test_missing_parent_row_fails_cleanly(
    engine: Engine, sample_home: Path, tmp_path: Path
) -> None:
    src = _copy_sample(sample_home, tmp_path / "src")
    (src / "data" / "property.jsonl").unlink()
    # SQLite says "FOREIGN KEY constraint failed", Postgres "violates foreign key constraint".
    with pytest.raises(ImportDataError, match=r"(?i)foreign key"):
        _import_dir(engine, src)
    assert sum(_counts(engine).values()) == 0


def test_secret_tables_cannot_be_imported(
    engine: Engine, sample_home: Path, tmp_path: Path
) -> None:
    src = _copy_sample(sample_home, tmp_path / "src")
    (src / "data" / "api_token.jsonl").write_text("")
    with pytest.raises(ImportDataError, match="api_token cannot be imported"):
        _import_dir(engine, src)


def test_duplicate_primary_key_is_rejected(
    engine: Engine, sample_home: Path, tmp_path: Path
) -> None:
    src = _copy_sample(sample_home, tmp_path / "src")
    _rewrite(src / "data" / "tag.jsonl", lambda rows: [*rows, rows[0]])
    with pytest.raises(ImportDataError, match="duplicate primary key"):
        _import_dir(engine, src)


def test_child_location_before_parent_is_reordered(
    engine: Engine, sample_home: Path, tmp_path: Path
) -> None:
    src = _copy_sample(sample_home, tmp_path / "src")
    child_id = "01a1a901-5800-70ff-8000-0000000000ff"
    parent_id = "01a1a901-5800-7009-8000-000000000009"

    def add_child(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        child = rows[0] | {"id": child_id, "name": "Shelf", "parent_location_id": parent_id}
        return [child, *rows]

    _rewrite(src / "data" / "location.jsonl", add_child)
    report = _import_dir(engine, src)
    assert report.tables["location"].inserted == 9
    with engine.connect() as conn:
        parent = conn.execute(
            select(Location.__table__.c.parent_location_id).where(
                Location.__table__.c.id == child_id
            )
        ).scalar_one()
    assert parent == parent_id


def test_codec_formats() -> None:
    when = datetime(2026, 11, 5, 12, 30, tzinfo=UTC)
    assert format_datetime(when) == "2026-11-05T12:30:00Z"
    assert encode_value(Decimal("49.99")) == 49.99
    table = Base.metadata.tables["asset"]
    row = decode_row(table, {"id": "x", "purchase_price": 49.99}, "test")
    assert row["purchase_price"] == Decimal("49.99")
    with pytest.raises(ImportDataError, match="missing primary key"):
        decode_row(table, {"name": "no id"}, "test")
