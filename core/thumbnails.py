"""Fast thumbnails for the library grid, backed by a disk cache.

RAW files carry a full-size JPEG preview that LibRaw can pull out in ~0.013s —
roughly 77x faster than a full demosaic decode. The library grid runs entirely on
these previews; the expensive `core.raw_loader` path is reserved for the Develop view.

Cache entries are keyed by path + mtime + size, so a file edited on disk invalidates
its own thumbnail without any explicit cache busting.
"""
from __future__ import annotations

import hashlib
import inspect
import io
from pathlib import Path
from typing import Callable

import rawpy
from PIL import Image, ImageOps

THUMBNAIL_SIZE = 512
JPEG_QUALITY = 85
_PLAIN_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}

PreviewExtractor = Callable[[Path], Image.Image]


def _load_jpeg_downscaled(source, target_size: int | None) -> Image.Image:
    """Decode a JPEG, using draft mode to decode at reduced scale where possible.

    Embedded RAW previews are full-size (6000x4000 on the R8). Letting libjpeg
    downscale in the DCT domain during decode is far cheaper than decoding at full
    resolution and resampling afterwards.
    """
    with Image.open(source) as img:
        if target_size:
            img.draft("RGB", (target_size, target_size))
        return ImageOps.exif_transpose(img.convert("RGB"))


def extract_preview(path: Path, target_size: int | None = None) -> Image.Image:
    """Return the largest cheaply-available image for a photo, oriented upright."""
    if path.suffix.lower() in _PLAIN_IMAGE_SUFFIXES:
        return _load_jpeg_downscaled(path, target_size)

    with rawpy.imread(str(path)) as raw:
        thumb = raw.extract_thumb()
        if thumb.format == rawpy.ThumbFormat.JPEG:
            return _load_jpeg_downscaled(io.BytesIO(thumb.data), target_size)
        # Some bodies store an uncompressed preview instead of a JPEG.
        return Image.fromarray(thumb.data).convert("RGB")


def _accepts_two_arguments(extractor: PreviewExtractor) -> bool:
    """Whether an extractor takes a target size in addition to the path."""
    try:
        target = extractor.__call__ if not inspect.isfunction(extractor) else extractor
        parameters = inspect.signature(target).parameters
    except (TypeError, ValueError):
        return False
    if any(p.kind is inspect.Parameter.VAR_POSITIONAL for p in parameters.values()):
        return True
    positional = [
        p
        for p in parameters.values()
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    return len(positional) >= 2


def cache_key(path: str | Path) -> str:
    """Identity of a file's *current* contents, as far as the cache is concerned."""
    resolved = Path(path).resolve()
    stat = resolved.stat()
    fingerprint = f"{resolved}|{stat.st_mtime_ns}|{stat.st_size}"
    return hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()


class ThumbnailCache:
    def __init__(
        self,
        cache_dir: str | Path,
        size: int = THUMBNAIL_SIZE,
        extractor: PreviewExtractor = extract_preview,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.size = size
        self._extractor = extractor
        self._extractor_takes_size = _accepts_two_arguments(extractor)

    def _call_extractor(self, photo_path: Path) -> Image.Image:
        """Pass the target size to extractors that accept it (so they can decode at
        reduced scale), while still supporting simple path-only extractors."""
        if self._extractor_takes_size:
            return self._extractor(photo_path, self.size)
        return self._extractor(photo_path)

    def path_for(self, photo_path: str | Path) -> Path:
        return self.cache_dir / f"{cache_key(photo_path)}.jpg"

    def is_cached(self, photo_path: str | Path) -> bool:
        try:
            return self.path_for(photo_path).exists()
        except OSError:
            return False

    def get(self, photo_path: str | Path) -> Path | None:
        """Return the cached thumbnail path, generating it if needed.

        Returns None instead of raising when a photo can't be read — a single corrupt
        or disconnected file must not take down a grid of thousands.
        """
        photo_path = Path(photo_path)
        try:
            destination = self.path_for(photo_path)
        except OSError:
            return None  # file is gone or unreadable

        if destination.exists():
            return destination

        try:
            preview = self._call_extractor(photo_path)
            preview.thumbnail((self.size, self.size), Image.Resampling.LANCZOS)
            # Write to a temp name first so an interrupted run can't leave a
            # half-written JPEG that later looks like a valid cache hit.
            staging = destination.with_suffix(".partial")
            preview.save(staging, format="JPEG", quality=JPEG_QUALITY)
            staging.replace(destination)
        except Exception:
            return None
        return destination

    def discard(self, photo_path: str | Path) -> None:
        """Drop one photo's cached thumbnail.

        Called when a photo leaves the catalog — entries are keyed by file content, so
        without this they would linger indefinitely with nothing referencing them.
        Safe to call for a file that is already gone from disk.
        """
        try:
            self.path_for(photo_path).unlink(missing_ok=True)
        except OSError:
            pass  # source file already gone: its key can't be computed, nothing to do

    def clear(self) -> None:
        for entry in self.cache_dir.glob("*.jpg"):
            entry.unlink(missing_ok=True)
