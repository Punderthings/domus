"""Read a backup from a ``.hiotbak`` zip or from an unzipped directory.

Archives come from outside the app, so every member name is checked before
use: no absolute paths, no ``..``, no backslashes or drive letters, no
symbolic links, no duplicates, and a cap on the total uncompressed size
(zip-slip and zip-bomb protection). Nothing is ever extracted by name; callers
read members as streams.
"""

import hashlib
import os
import re
import stat
import zipfile
from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import Path
from types import TracebackType
from typing import IO, Self

from domus.backup.errors import ArchiveError

DEFAULT_MAX_TOTAL_BYTES = 2 * 1024**3  # 2 GiB
_CHUNK = 1024 * 1024
_DRIVE = re.compile(r"^[A-Za-z]:")


def check_member_name(name: str) -> None:
    """Raise ArchiveError unless ``name`` is a safe, relative, POSIX-style path."""
    bad = (
        not name
        or "\\" in name
        or "\x00" in name
        or name.startswith("/")
        or _DRIVE.match(name) is not None
        or any(part in ("", ".", "..") for part in name.split("/"))
    )
    if bad:
        raise ArchiveError(f"unsafe path in archive: {name!r}")


class BackupSource(ABC):
    """A read-only view of a backup's files, addressed by relative POSIX path."""

    def __init__(self, label: str, names: list[str]) -> None:
        self.label = label
        self._names = sorted(names)
        self._name_set = frozenset(names)

    def names(self) -> list[str]:
        """Every regular file in the backup, sorted."""
        return list(self._names)

    def has(self, name: str) -> bool:
        return name in self._name_set

    def _require(self, name: str) -> None:
        if name not in self._name_set:
            raise ArchiveError(f"{name} is not in {self.label}")

    @abstractmethod
    def open(self, name: str) -> IO[bytes]:
        """Open one file for binary reading."""

    @abstractmethod
    def close(self) -> None:
        """Release any open handles."""

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def read_bytes(self, name: str) -> bytes:
        with self.open(name) as fh:
            return fh.read()

    def iter_lines(self, name: str) -> Iterator[str]:
        """Yield the UTF-8 text lines of one file, without line endings."""
        with self.open(name) as fh:
            for raw in fh:
                yield raw.decode("utf-8").rstrip("\r\n")

    def sha256(self, name: str) -> str:
        digest = hashlib.sha256()
        with self.open(name) as fh:
            while chunk := fh.read(_CHUNK):
                digest.update(chunk)
        return digest.hexdigest()

    def copy_to(self, name: str, dest: Path) -> str:
        """Stream one file to ``dest`` and return its SHA-256."""
        digest = hashlib.sha256()
        with self.open(name) as src, dest.open("wb") as out:
            while chunk := src.read(_CHUNK):
                digest.update(chunk)
                out.write(chunk)
        return digest.hexdigest()


class DirectorySource(BackupSource):
    """An unzipped backup, such as ``examples/sample-home``."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        names: list[str] = []
        for dirpath, dirnames, filenames in os.walk(self._root, followlinks=False):
            here = Path(dirpath)
            for entry in [*dirnames, *filenames]:
                if (here / entry).is_symlink():
                    raise ArchiveError(f"symbolic links are not allowed: {here / entry}")
            for filename in filenames:
                rel = (here / filename).relative_to(self._root).as_posix()
                check_member_name(rel)
                names.append(rel)
        super().__init__(str(root), names)

    def open(self, name: str) -> IO[bytes]:
        self._require(name)
        return (self._root / name).open("rb")

    def close(self) -> None:
        """Nothing to release: each open() returns its own file handle."""


class ZipSource(BackupSource):
    """A ``.hiotbak`` zip archive."""

    def __init__(self, path: Path, *, max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES) -> None:
        try:
            self._zip = zipfile.ZipFile(path)
        except (zipfile.BadZipFile, OSError) as exc:
            raise ArchiveError(f"{path} is not a readable zip archive: {exc}") from exc
        try:
            names = self._check_members(max_total_bytes)
        except Exception:
            self._zip.close()
            raise
        super().__init__(str(path), names)

    def _check_members(self, max_total_bytes: int) -> list[str]:
        names: list[str] = []
        seen: set[str] = set()
        total = 0
        for info in self._zip.infolist():
            if info.is_dir():
                check_member_name(info.filename.rstrip("/"))
                continue
            check_member_name(info.filename)
            if stat.S_ISLNK(info.external_attr >> 16):
                raise ArchiveError(f"symbolic links are not allowed: {info.filename!r}")
            if info.filename in seen:
                raise ArchiveError(f"duplicate entry in archive: {info.filename!r}")
            seen.add(info.filename)
            # zipfile never returns more than file_size bytes for a member, so
            # capping the declared sizes caps what can be decompressed.
            total += info.file_size
            if total > max_total_bytes:
                raise ArchiveError(
                    f"archive expands to more than {max_total_bytes} bytes; refusing to read it"
                )
            names.append(info.filename)
        return names

    def open(self, name: str) -> IO[bytes]:
        self._require(name)
        return self._zip.open(name)

    def close(self) -> None:
        self._zip.close()


def open_source(path: Path, *, max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES) -> BackupSource:
    """Open ``path`` as a directory backup or a zip archive."""
    if path.is_dir():
        return DirectorySource(path)
    if path.is_file():
        return ZipSource(path, max_total_bytes=max_total_bytes)
    raise ArchiveError(f"{path} does not exist")
