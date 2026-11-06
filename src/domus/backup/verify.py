"""Check a backup before trusting it (``domus backup verify``, data-storage-backup.md 4.2).

Errors make a backup unusable for restore; warnings (such as an unexpected
README, or a referenced blob that was missing when the backup was made) are
reported but do not block a restore.
"""

import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from alembic.script import ScriptDirectory

from domus.backup.blobs import sha_from_archive_name
from domus.backup.codec import loads_row
from domus.backup.errors import ArchiveError, BackupError
from domus.backup.export import table_for_data_name
from domus.backup.manifest import (
    KINDS,
    MANIFEST_NAME,
    SUPPORTED_FORMAT_VERSIONS,
    Manifest,
    parse_manifest,
)
from domus.backup.source import BackupSource, check_member_name
from domus.backup.sqlite import integrity_check
from domus.backup.tables import NOT_IMPORTABLE, importable_table
from domus.migrate import alembic_config

SNAPSHOT_NAME = "db/domus.sqlite"


@dataclass
class VerifyResult:
    """The outcome of :func:`verify`."""

    manifest: Manifest | None = None
    errors: list[str] = field(default_factory=list[str])
    warnings: list[str] = field(default_factory=list[str])
    # Rows per data file, as counted while verifying.
    row_counts: dict[str, int] = field(default_factory=dict[str, int])
    missing_blobs: list[str] = field(default_factory=list[str])

    @property
    def ok(self) -> bool:
        return not self.errors


def known_revisions() -> frozenset[str]:
    """Every Alembic revision this app knows. All of them are at or below head."""
    script = ScriptDirectory.from_config(alembic_config())
    return frozenset(rev.revision for rev in script.walk_revisions())


def _check_manifest(manifest: Manifest, result: VerifyResult) -> None:
    if manifest.format_version not in SUPPORTED_FORMAT_VERSIONS:
        result.errors.append(
            f"unsupported format_version {manifest.format_version}; "
            f"this app reads {sorted(SUPPORTED_FORMAT_VERSIONS)}"
        )
    if manifest.kind not in KINDS:
        result.errors.append(f"unknown kind {manifest.kind!r}")
    if manifest.encrypted:
        result.errors.append("encrypted backups are not supported yet")
    # null means the initial schema (hand-written datasets such as sample-home).
    if manifest.schema_version is not None and manifest.schema_version not in known_revisions():
        result.errors.append(
            f"schema_version {manifest.schema_version!r} is newer than this app "
            "(or unknown); upgrade Domus before restoring it"
        )


def _check_hashes(source: BackupSource, manifest: Manifest, result: VerifyResult) -> None:
    if not manifest.sha256:
        result.warnings.append("manifest lists no file hashes; contents not checksummed")
        return
    for name, expected in sorted(manifest.sha256.items()):
        try:
            check_member_name(name)
        except ArchiveError as exc:
            result.errors.append(str(exc))
            continue
        if not source.has(name):
            result.errors.append(f"{name} is listed in the manifest but missing")
        elif source.sha256(name) != expected:
            result.errors.append(f"{name}: SHA-256 does not match the manifest")
    for name in source.names():
        if name != MANIFEST_NAME and name not in manifest.sha256 and _is_backup_file(name):
            result.errors.append(f"{name} is not listed in the manifest hashes")


def _is_backup_file(name: str) -> bool:
    return (
        table_for_data_name(name) is not None
        or name == SNAPSHOT_NAME
        or sha_from_archive_name(name) is not None
    )


def _check_data(source: BackupSource, manifest: Manifest, result: VerifyResult) -> set[str]:
    """Count and parse every data file; return the blob digests the data refers to."""
    referenced: set[str] = set()
    for name in source.names():
        table = table_for_data_name(name)
        if table is None:
            continue
        if table in NOT_IMPORTABLE:
            result.errors.append(f"{name}: table {table} may not appear in a backup")
            continue
        if importable_table(table) is None:
            result.errors.append(f"{name}: unknown table {table}")
            continue
        count = 0
        try:
            for lineno, line in enumerate(source.iter_lines(name), start=1):
                if not line.strip():
                    continue
                try:
                    row = loads_row(line)
                except ValueError as exc:
                    result.errors.append(f"{name} line {lineno}: {exc}")
                    continue
                count += 1
                if table == "blob" and isinstance(row.get("sha256"), str):
                    referenced.add(str(row["sha256"]))
        except UnicodeDecodeError as exc:
            result.errors.append(f"{name}: not UTF-8 text: {exc}")
        result.row_counts[table] = count
        expected = manifest.row_counts.get(table)
        if expected is None:
            result.errors.append(f"{name} has no entry in the manifest row_counts")
        elif expected != count:
            result.errors.append(f"{name}: {count} rows, manifest says {expected}")
    for table, expected in sorted(manifest.row_counts.items()):
        if table not in result.row_counts and expected != 0:
            result.errors.append(f"manifest lists {expected} {table} rows but the file is missing")
    return referenced


def _check_snapshot(source: BackupSource, result: VerifyResult) -> None:
    if not source.has(SNAPSHOT_NAME):
        return
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "snapshot.sqlite"
        source.copy_to(SNAPSHOT_NAME, copy)
        try:
            integrity_check(copy)
        except BackupError as exc:
            result.errors.append(f"{SNAPSHOT_NAME}: {exc}")


def _check_blobs(source: BackupSource, referenced: set[str], result: VerifyResult) -> None:
    present: set[str] = set()
    for name in source.names():
        sha = sha_from_archive_name(name)
        if sha is None:
            continue
        present.add(sha)
        if source.sha256(name) != sha:
            result.errors.append(f"{name}: content does not match its SHA-256 name")
    result.missing_blobs = sorted(referenced - present)
    for sha in result.missing_blobs:
        result.warnings.append(f"blob {sha} is referenced but not in the backup")


def verify(source: BackupSource) -> VerifyResult:
    """Check the manifest, hashes, row counts, snapshot integrity, and blobs."""
    result = VerifyResult()
    if not source.has(MANIFEST_NAME):
        result.errors.append(f"{MANIFEST_NAME} is missing")
        return result
    try:
        manifest = parse_manifest(source.read_bytes(MANIFEST_NAME))
    except ArchiveError as exc:
        result.errors.append(str(exc))
        return result
    result.manifest = manifest
    _check_manifest(manifest, result)
    for name in source.names():
        if name != MANIFEST_NAME and not _is_backup_file(name):
            result.warnings.append(f"ignoring unexpected file {name}")
    _check_hashes(source, manifest, result)
    referenced = _check_data(source, manifest, result)
    _check_snapshot(source, result)
    _check_blobs(source, referenced, result)
    return result
