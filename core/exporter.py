"""Export rendered images to JPEG, singly or as a batch of portfolio picks."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
from PIL import Image

from core.display import linear_to_srgb8
from core.edit_state import EditState
from core.lens_correction import apply_lens_correction
from core.raw_loader import load_raw
from core.tone_pipeline import apply_tone

ProgressCallback = Callable[[int, int], None]
CancelCheck = Callable[[], bool]


@dataclass(frozen=True)
class BatchExportResult:
    exported: int
    failed: int
    cancelled: bool = False

    @property
    def total(self) -> int:
        return self.exported + self.failed


def export_jpeg(rgb: np.ndarray, path: str, quality: int) -> None:
    """Save an RGB array (float32 linear in [0, 1], or already-uint8 sRGB) as a JPEG.

    `quality` is the standard JPEG 1-100 quality scale (Pillow's `quality` param).
    """
    srgb8 = rgb if rgb.dtype == np.uint8 else linear_to_srgb8(rgb)
    Image.fromarray(srgb8).save(Path(path), format="JPEG", quality=quality)


def render_with_edits(photo_path: str | Path, edits: EditState) -> np.ndarray:
    """Decode a photo and apply its saved adjustments.

    AI denoise is deliberately *not* run here: it is a multi-second GPU pass per photo,
    so a batch export applies the cheap, deterministic adjustments only.
    """
    raw_image = load_raw(photo_path)
    corrected = apply_lens_correction(raw_image.rgb, edits.lens)
    return apply_tone(corrected, edits.tone)


def export_photos(
    photos: Iterable,
    output_dir: str | Path,
    quality: int,
    progress_cb: ProgressCallback | None = None,
    should_cancel: CancelCheck | None = None,
) -> BatchExportResult:
    """Export each photo to `output_dir` as a JPEG, applying that photo's own edits.

    `photos` are `core.catalog.Photo` records. Output filenames follow the source
    stem, de-duplicated so two shoots sharing a filename can't overwrite each other.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    photos = list(photos)
    total = len(photos)
    exported = failed = 0

    for index, photo in enumerate(photos, start=1):
        if should_cancel is not None and should_cancel():
            return BatchExportResult(exported=exported, failed=failed, cancelled=True)
        try:
            rendered = render_with_edits(photo.path, photo.edits)
            export_jpeg(rendered, str(_unique_destination(output_dir, photo.filename)), quality)
            exported += 1
        except Exception:
            failed += 1  # one bad file shouldn't abort a portfolio export
        if progress_cb is not None:
            progress_cb(index, total)

    return BatchExportResult(exported=exported, failed=failed)


def _unique_destination(output_dir: Path, filename: str) -> Path:
    stem = Path(filename).stem
    candidate = output_dir / f"{stem}.jpg"
    counter = 2
    while candidate.exists():
        candidate = output_dir / f"{stem}_{counter}.jpg"
        counter += 1
    return candidate
