"""The blob store and upload checks, without the HTTP layer."""

from collections.abc import AsyncIterator
from pathlib import Path

import anyio
import pytest
from tests.images import PDF, png

from domus.services.blobstore import LocalFsBlobStore, TooLarge
from domus.services.uploads import safe_filename, sniff_mime


@pytest.mark.parametrize(
    ("head", "mime"),
    [
        (png()[:16], "image/png"),
        (b"\xff\xd8\xff\xe0\x00\x10JFIF", "image/jpeg"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp"),
        (b"GIF89a\x01\x00", "image/gif"),
        (PDF[:16], "application/pdf"),
        (b"<svg xmlns=", None),
        (b"<html><script>", None),
        (b"", None),
    ],
)
def test_sniff_mime(head: bytes, mime: str | None) -> None:
    assert sniff_mime(head) == mime


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("plan.png", "plan.png"),
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\me\\wall.jpg", "wall.jpg"),
        ('bad"name\r\n.png', "badname.png"),
        ("", None),
        (None, None),
        ("dir/", None),
    ],
)
def test_safe_filename(raw: str | None, clean: str | None) -> None:
    assert safe_filename(raw) == clean


async def _chunks(*parts: bytes) -> AsyncIterator[bytes]:
    for p in parts:
        yield p


def test_commit_is_content_addressed(tmp_path: Path) -> None:
    store = LocalFsBlobStore(tmp_path)
    first = store.commit(anyio.run(lambda: store.stage_stream(_chunks(b"ab", b"c"), max_bytes=10)))
    assert first.size == 3
    assert first.path == tmp_path / first.sha256[:2] / first.sha256[2:4] / first.sha256
    assert first.path.read_bytes() == b"abc"
    again = store.commit(anyio.run(lambda: store.stage_stream(_chunks(b"abc"), max_bytes=10)))
    assert again.sha256 == first.sha256
    assert list(store.staging_dir.iterdir()) == []


def test_stage_stream_stops_at_the_limit(tmp_path: Path) -> None:
    store = LocalFsBlobStore(tmp_path)
    with pytest.raises(TooLarge):
        anyio.run(lambda: store.stage_stream(_chunks(b"12345", b"678"), max_bytes=6))
    assert list(store.staging_dir.iterdir()) == []
