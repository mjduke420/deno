"""Walk a folder, read each photo's metadata, and record it in the catalog.

Scanning reads metadata only — thumbnails are generated lazily by the grid as photos
scroll into view, so adding a large shoot stays fast.
"""
from __future__ import annotations

import io
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator

import rawpy
from PIL import ExifTags, Image

from core.catalog import Catalog, format_timestamp

RAW_SUFFIXES = {".cr3", ".cr2", ".orf", ".arw", ".nef", ".dng", ".raf", ".rw2", ".pef", ".srw"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
SUPPORTED_SUFFIXES = RAW_SUFFIXES | IMAGE_SUFFIXES

_EXIF_DATETIME_FORMAT = "%Y:%m:%d %H:%M:%S"
_EXIF_TAG_IDS = {name: tag_id for tag_id, name in ExifTags.TAGS.items()}

ProgressCallback = Callable[[int, int], None]
CancelCheck = Callable[[], bool]


@dataclass(frozen=True)
class PhotoMetadata:
    filename: str
    file_mtime: float | None = None
    file_size: int | None = None
    captured_at: str | None = None
    camera_model: str | None = None
    lens_model: str | None = None
    iso: float | None = None
    aperture: float | None = None
    shutter_speed: float | None = None
    focal_length_mm: float | None = None
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True)
class ScanResult:
    added: int
    failed: int
    cancelled: bool = False

    @property
    def total(self) -> int:
        return self.added + self.failed


def find_photos(folder: str | Path) -> Iterator[Path]:
    """Yield supported photo files under `folder`, recursively, in stable order."""
    root = Path(folder)
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
            yield path


def read_metadata(path: str | Path) -> PhotoMetadata:
    """Read catalog metadata for one photo. Fields that can't be determined for an
    otherwise-readable file come back as None rather than raising."""
    path = Path(path)
    stat = path.stat()
    base = {
        "filename": path.name,
        "file_mtime": stat.st_mtime,
        "file_size": stat.st_size,
    }

    if path.suffix.lower() in IMAGE_SUFFIXES:
        return PhotoMetadata(**base, **_read_plain_image_metadata(path))
    return PhotoMetadata(**base, **_read_raw_metadata(path))


def scan_folder(
    catalog: Catalog,
    folder: str | Path,
    progress_cb: ProgressCallback | None = None,
    should_cancel: CancelCheck | None = None,
) -> ScanResult:
    """Register `folder` and catalog every photo under it.

    Safe to re-run: `Catalog.upsert_photo` refreshes file metadata while preserving
    ratings, flags, labels and edits.
    """
    folder_id = catalog.add_folder(folder)
    photos = list(find_photos(folder))
    total = len(photos)
    added = failed = 0

    for index, photo_path in enumerate(photos, start=1):
        if should_cancel is not None and should_cancel():
            return ScanResult(added=added, failed=failed, cancelled=True)
        try:
            metadata = read_metadata(photo_path)
            catalog.upsert_photo(folder_id, photo_path, **asdict(metadata))
            added += 1
        except Exception:
            failed += 1  # one unreadable file must not abort a 4,000-photo scan
        if progress_cb is not None:
            progress_cb(index, total)

    return ScanResult(added=added, failed=failed)


def _read_raw_metadata(path: Path) -> dict:
    with rawpy.imread(str(path)) as raw:
        other = raw.other
        lens = raw.lens
        sizes = raw.sizes
        try:
            preview_exif = _exif_from_thumb(raw.extract_thumb())
        except Exception:
            preview_exif = {}

    captured_at = None
    if other is not None and other.timestamp:
        captured_at = format_timestamp(other.timestamp)
    captured_at = captured_at or preview_exif.get("captured_at")

    return {
        "captured_at": captured_at,
        "camera_model": preview_exif.get("camera_model"),
        "lens_model": (lens.model or None) if lens else None,
        "iso": other.iso_speed if other else None,
        "aperture": other.aperture if other else None,
        "shutter_speed": other.shutter_speed if other else None,
        "focal_length_mm": other.focal_length if other else None,
        "width": sizes.width if sizes else None,
        "height": sizes.height if sizes else None,
    }


def _read_plain_image_metadata(path: Path) -> dict:
    with Image.open(path) as img:
        width, height = img.size
        exif = _normalize_exif(img.getexif())
    return {
        "captured_at": exif.get("captured_at"),
        "camera_model": exif.get("camera_model"),
        "lens_model": None,
        "iso": None,
        "aperture": None,
        "shutter_speed": None,
        "focal_length_mm": None,
        "width": width,
        "height": height,
    }


def _exif_from_thumb(thumb) -> dict:
    """RAW bodies embed a preview JPEG carrying Make/Model/DateTime, which rawpy
    itself doesn't surface."""
    if thumb.format != rawpy.ThumbFormat.JPEG:
        return {}
    with Image.open(io.BytesIO(thumb.data)) as preview:
        return _normalize_exif(preview.getexif())


def _normalize_exif(exif) -> dict:
    if not exif:
        return {}
    model = exif.get(_EXIF_TAG_IDS["Model"])
    make = exif.get(_EXIF_TAG_IDS["Make"])
    raw_datetime = exif.get(_EXIF_TAG_IDS["DateTime"])

    camera_model = None
    if model:
        model = str(model).strip()
        make = str(make).strip() if make else ""
        # "Canon" + "EOS R8" -> "Canon EOS R8", without producing "Canon Canon EOS R8".
        camera_model = model if not make or model.lower().startswith(make.lower()) else f"{make} {model}"

    return {
        "camera_model": camera_model,
        "captured_at": _parse_exif_datetime(raw_datetime),
    }


def _parse_exif_datetime(value) -> str | None:
    """EXIF stores 'YYYY:MM:DD HH:MM:SS'; the catalog wants ISO 'YYYY-MM-DD HH:MM:SS'."""
    if not value:
        return None
    try:
        return format_timestamp(datetime.strptime(str(value).strip(), _EXIF_DATETIME_FORMAT))
    except ValueError:
        return None
