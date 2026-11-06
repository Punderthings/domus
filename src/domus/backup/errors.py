"""Exceptions raised by the backup, export, import, and restore code."""


class BackupError(Exception):
    """Base class for every backup and restore failure."""


class ArchiveError(BackupError):
    """The archive or directory is unsafe, unreadable, or malformed."""


class ImportDataError(BackupError):
    """A JSONL row cannot be imported (unknown column, bad value, constraint failure)."""


class RestoreError(BackupError):
    """A restore was refused or could not complete; the current data is untouched."""
