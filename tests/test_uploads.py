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


# --- Image re-encoding (Pillow) -----------------------------------------------


def _jpeg_with_gps() -> bytes:
    from io import BytesIO

    from PIL import Image

    img = Image.new("RGB", (4, 2), (10, 200, 10))
    exif = Image.Exif()
    exif[0x0112] = 6  # orientation: rotate 90 degrees to display
    exif[0x8825] = {2: (42.0, 21.0, 0.0), 1: "N"}  # GPSInfo: latitude
    out = BytesIO()
    img.save(out, format="JPEG", exif=exif.tobytes(), comment=b"secret")
    return out.getvalue()


def test_sanitize_strips_exif_and_applies_rotation(tmp_path: Path) -> None:
    from PIL import Image

    from domus.services.images import sanitize

    store = LocalFsBlobStore(tmp_path)
    staged = store.new_staging_file()
    staged.write_bytes(_jpeg_with_gps())
    with Image.open(staged) as before:
        assert before.getexif().get(0x8825) is not None
    out, mime = sanitize(staged, store, "image/jpeg")
    assert mime == "image/jpeg"
    assert not staged.exists()
    with Image.open(out) as after:
        assert after.size == (2, 4)  # rotated into the pixels
        assert dict(after.getexif()) == {}
        assert "comment" not in after.info
        assert "exif" not in after.info


@pytest.mark.parametrize("mime", ["image/png", "image/gif", "image/webp"])
def test_sanitize_keeps_the_format(tmp_path: Path, mime: str) -> None:
    from io import BytesIO

    from PIL import Image

    from domus.services.images import FORMATS, sanitize

    buf = BytesIO()
    Image.new("RGB", (3, 3), (1, 2, 3)).save(buf, format=FORMATS[mime])
    store = LocalFsBlobStore(tmp_path)
    staged = store.new_staging_file()
    staged.write_bytes(buf.getvalue())
    out, _ = sanitize(staged, store, mime)
    with Image.open(out) as after:
        assert after.format == FORMATS[mime]
        assert after.size == (3, 3)


def test_sanitize_keeps_gif_animation(tmp_path: Path) -> None:
    from io import BytesIO

    from PIL import Image

    from domus.services.images import sanitize

    frames = [Image.new("RGB", (2, 2), c) for c in [(255, 0, 0), (0, 255, 0), (0, 0, 255)]]
    buf = BytesIO()
    frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:])
    store = LocalFsBlobStore(tmp_path)
    staged = store.new_staging_file()
    staged.write_bytes(buf.getvalue())
    out, _ = sanitize(staged, store, "image/gif")
    with Image.open(out) as after:
        assert getattr(after, "n_frames", 1) == 3


def test_sanitize_rejects_a_fake_image(tmp_path: Path) -> None:
    from domus.services.images import BadImage, sanitize

    store = LocalFsBlobStore(tmp_path)
    staged = store.new_staging_file()
    staged.write_bytes(b"\x89PNG\r\n\x1a\n" + b"not really a png")
    with pytest.raises(BadImage):
        sanitize(staged, store, "image/png")
    assert [p for p in store.staging_dir.iterdir() if p != staged] == []


def test_sanitize_rejects_decompression_bombs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from domus.services import images

    monkeypatch.setattr(images, "MAX_PIXELS", 10)
    store = LocalFsBlobStore(tmp_path)
    staged = store.new_staging_file()
    staged.write_bytes(png(4, 4))
    with pytest.raises(images.BadImage):
        images.sanitize(staged, store, "image/png")


def test_sanitize_counts_every_animation_frame(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from io import BytesIO

    from PIL import Image

    from domus.services import images

    frames = [Image.new("RGB", (4, 4), c) for c in [(255, 0, 0), (0, 255, 0), (0, 0, 255)]]
    buf = BytesIO()
    frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:])
    monkeypatch.setattr(images, "MAX_PIXELS", 40)  # one frame fits, three do not
    store = LocalFsBlobStore(tmp_path)
    staged = store.new_staging_file()
    staged.write_bytes(buf.getvalue())
    with pytest.raises(images.BadImage):
        images.sanitize(staged, store, "image/gif")
