"""Where content-addressed blobs live on disk (data-storage-backup.md 3.1).

The blob store itself is a later step; backups only need to find a blob by
its SHA-256 at ``blobs_dir/ab/cd/<sha256>`` and copy it in or out.
"""

import os
import re
import secrets
from pathlib import Path

from domus.backup.errors import ArchiveError
from domus.backup.source import BackupSource

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ARCHIVE_PREFIX = "blobs/"


def blob_path(blobs_dir: Path, sha256: str) -> Path:
    """The on-disk path for one blob. Rejects anything that is not a hex digest."""
    if not SHA256_RE.match(sha256):
        raise ValueError(f"not a SHA-256 hex digest: {sha256!r}")
    return blobs_dir / sha256[:2] / sha256[2:4] / sha256


def archive_name(sha256: str) -> str:
    return f"{ARCHIVE_PREFIX}{sha256}"


def sha_from_archive_name(name: str) -> str | None:
    """The digest for a ``blobs/<sha256>`` member name, or None for any other name."""
    if not name.startswith(ARCHIVE_PREFIX):
        return None
    sha = name.removeprefix(ARCHIVE_PREFIX)
    return sha if SHA256_RE.match(sha) else None


def install_blobs(source: BackupSource, blobs_dir: Path) -> int:
    """Copy every ``blobs/<sha256>`` member into the blob store; return how many were new.

    Each copy goes to a temporary file, is hashed, and is renamed into place only
    if the content matches its name.
    """
    installed = 0
    for name in source.names():
        sha = sha_from_archive_name(name)
        if sha is None:
            continue
        dest = blob_path(blobs_dir, sha)
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(f".{sha}.{secrets.token_hex(4)}.tmp")
        try:
            actual = source.copy_to(name, tmp)
            if actual != sha:
                raise ArchiveError(f"{name}: content does not match its SHA-256 name")
            os.replace(tmp, dest)
            installed += 1
        finally:
            tmp.unlink(missing_ok=True)
    return installed
