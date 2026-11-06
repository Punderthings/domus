"""Backup, restore, and JSONL export in the ``.hiotbak`` format (data-storage-backup.md 4).

Typical use::

    create_backup(engine, path, blobs_dir=settings.blobs_dir)
    with open_source(path) as source:
        result = verify(source)
    restore_merge(settings, path, dry_run=True)
"""

from domus.backup.archive import BackupResult, create_backup, default_backup_name
from domus.backup.errors import ArchiveError, BackupError, ImportDataError, RestoreError
from domus.backup.export import export_directory
from domus.backup.importer import ImportReport, TableCounts, import_source
from domus.backup.manifest import FORMAT_VERSION, Manifest, parse_manifest
from domus.backup.restore import RestoreResult, restore_merge, restore_replace
from domus.backup.source import BackupSource, open_source
from domus.backup.verify import VerifyResult, verify

__all__ = [
    "FORMAT_VERSION",
    "ArchiveError",
    "BackupError",
    "BackupResult",
    "BackupSource",
    "ImportDataError",
    "ImportReport",
    "Manifest",
    "RestoreError",
    "RestoreResult",
    "TableCounts",
    "VerifyResult",
    "create_backup",
    "default_backup_name",
    "export_directory",
    "import_source",
    "open_source",
    "parse_manifest",
    "restore_merge",
    "restore_replace",
    "verify",
]
