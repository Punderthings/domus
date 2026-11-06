"""Image clean-up before an upload is stored.

Without an image library the file is stored as uploaded, after the magic-byte
check in ``uploads``. See the PR notes: this becomes a Pillow re-encode that
drops EXIF/GPS metadata once that dependency is approved.
"""

from pathlib import Path

from domus.services.blobstore import LocalFsBlobStore


class BadImage(Exception):
    """The file claims to be an image but cannot be decoded."""


def sanitize(staged: Path, store: LocalFsBlobStore, mime: str) -> tuple[Path, str]:
    """Return the staging file to store and its MIME type."""
    del store
    return staged, mime
