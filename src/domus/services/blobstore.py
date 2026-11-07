"""The local filesystem blob store (data-storage-backup.md 3.1).

Blobs are keyed by the SHA-256 of their content and live at
``blobs_dir/ab/cd/<sha256>``, the same layout backups read and write. Writes go
to a temporary file first and are renamed into place, so a crash never leaves a
half-written blob under a real digest.
"""

import hashlib
import os
import secrets
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from domus.backup.blobs import blob_path

CHUNK = 1024 * 1024


class TooLarge(Exception):
    """The upload went over the configured size limit."""


@dataclass(frozen=True)
class StoredBlob:
    sha256: str
    size: int
    path: Path


class LocalFsBlobStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    @property
    def staging_dir(self) -> Path:
        return self.root / ".staging"

    def path(self, sha256: str) -> Path:
        return blob_path(self.root, sha256)

    def exists(self, sha256: str) -> bool:
        return self.path(sha256).is_file()

    def new_staging_file(self) -> Path:
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        return self.staging_dir / f"{secrets.token_hex(16)}.tmp"

    async def stage_stream(self, chunks: AsyncIterator[bytes], *, max_bytes: int) -> Path:
        """Write a request body to a staging file, stopping once it passes ``max_bytes``."""
        tmp = self.new_staging_file()
        size = 0
        try:
            with tmp.open("wb") as fh:
                async for chunk in chunks:
                    size += len(chunk)
                    if size > max_bytes:
                        raise TooLarge
                    fh.write(chunk)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        return tmp

    def commit(self, staged: Path) -> StoredBlob:
        """Hash a staging file and move it into the store under its digest.

        The staging file is gone afterwards either way. If the store already
        holds the same content, the existing blob is kept.
        """
        digest = hashlib.sha256()
        size = 0
        try:
            with staged.open("rb") as fh:
                while chunk := fh.read(CHUNK):
                    digest.update(chunk)
                    size += len(chunk)
            sha = digest.hexdigest()
            dest = self.path(sha)
            if dest.is_file():
                return StoredBlob(sha, size, dest)
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged, dest)
            return StoredBlob(sha, size, dest)
        finally:
            staged.unlink(missing_ok=True)
