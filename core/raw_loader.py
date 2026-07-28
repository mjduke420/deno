"""Decode photos into linear RGB arrays plus shooting metadata.

RAW files (CR3/CR2/ORF/NEF/…) go through LibRaw; already-rendered images (JPEG/PNG/
TIFF) are linearised from sRGB so the rest of the pipeline can treat both the same.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rawpy
from PIL import Image, ImageOps

from core.display import srgb8_to_linear

PLAIN_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}


@dataclass(frozen=True)
class RawImage:
    rgb: np.ndarray  # (H, W, 3) float32 in [0, 1], demosaiced + camera white balance applied, linear gamma
    iso: float | None
    lens_model: str | None
    focal_length_mm: float | None
    aperture: float | None
    shutter_speed: float | None


def load_raw(path: str | Path) -> RawImage:
    """Decode a photo to a linear RGB array and extract shooting metadata."""
    path = Path(path)
    if path.suffix.lower() in PLAIN_IMAGE_SUFFIXES:
        return _load_plain_image(path)
    return _load_raw_file(path)


def _load_raw_file(path: Path) -> RawImage:
    with rawpy.imread(str(path)) as raw:
        rgb16 = raw.postprocess(
            use_camera_wb=True,
            no_auto_bright=True,
            output_bps=16,
            gamma=(1, 1),
        )
        other = raw.other
        lens = raw.lens

    return RawImage(
        rgb=rgb16.astype(np.float32) / 65535.0,
        iso=other.iso_speed if other else None,
        lens_model=lens.model if lens and lens.model else None,
        focal_length_mm=other.focal_length if other else None,
        aperture=other.aperture if other else None,
        shutter_speed=other.shutter_speed if other else None,
    )


def _load_plain_image(path: Path) -> RawImage:
    """Already-rendered images carry no RAW metadata, so only pixels are recovered."""
    with Image.open(path) as img:
        upright = ImageOps.exif_transpose(img.convert("RGB"))
        srgb8 = np.asarray(upright, dtype=np.uint8)

    return RawImage(
        rgb=srgb8_to_linear(srgb8),
        iso=None,
        lens_model=None,
        focal_length_mm=None,
        aperture=None,
        shutter_speed=None,
    )
