"""Image clean-up before an upload is stored (master plan section 5).

Every uploaded image is decoded and re-encoded with Pillow. That drops EXIF
(including GPS position, which phone photos of a home usually carry), XMP, and
text comments, and it rejects anything that only looks like an image. The
camera's rotation is applied to the pixels first, so photos still show the
right way up without their EXIF orientation tag. The ICC colour profile is kept.
"""

import warnings
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from domus.services.blobstore import LocalFsBlobStore

# Refuse decompression bombs: about a 10,000 x 10,000 image.
MAX_PIXELS = 100_000_000

FORMATS: dict[str, str] = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
    "image/gif": "GIF",
}


class BadImage(Exception):
    """The file claims to be an image but cannot be decoded."""


def _jpeg_ready(img: Image.Image) -> Image.Image:
    if img.mode in ("RGB", "L", "CMYK"):
        return img
    return img.convert("RGB")


def sanitize(staged: Path, store: LocalFsBlobStore, mime: str) -> tuple[Path, str]:
    """Re-encode ``staged`` without metadata; return the new staging file and its type.

    The original staging file is removed. The output keeps the input's format.
    """
    fmt = FORMATS.get(mime)
    if fmt is None:
        raise BadImage(f"not an image type we re-encode: {mime}")
    out = store.new_staging_file()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            try:
                with Image.open(staged, formats=[fmt]) as src:
                    if src.width * src.height > MAX_PIXELS:
                        raise BadImage("Image is too large to process")
                    animated = fmt in ("GIF", "WEBP") and getattr(src, "n_frames", 1) > 1
                    icc = src.info.get("icc_profile")
                    if animated:
                        frames = _frames(src)
                        first, rest = frames[0], frames[1:]
                        first.info = {}
                        first.save(out, format=fmt, save_all=True, append_images=rest, loop=0)
                    else:
                        src.load()
                        img = ImageOps.exif_transpose(src)
                        img.info = {}
                        kwargs: dict[str, object] = {}
                        if icc and fmt in ("JPEG", "PNG", "WEBP"):
                            kwargs["icc_profile"] = icc
                        if fmt == "JPEG":
                            _jpeg_ready(img).save(out, format=fmt, quality=90, **kwargs)
                        elif fmt == "WEBP":
                            img.save(out, format=fmt, quality=90, **kwargs)
                        else:
                            img.save(out, format=fmt, **kwargs)
            except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
                raise BadImage("The file could not be read as an image") from exc
            except (Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
                raise BadImage("Image is too large to process") from exc
    except BaseException:
        out.unlink(missing_ok=True)
        raise
    staged.unlink(missing_ok=True)
    return out, mime


def _frames(src: Image.Image) -> list[Image.Image]:
    frames: list[Image.Image] = []
    for i in range(getattr(src, "n_frames", 1)):
        src.seek(i)
        frames.append(src.copy())
    return frames
