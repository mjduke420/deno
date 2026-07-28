"""Manual lens correction: distortion, vignetting, and chromatic aberration removal.

Amount-slider driven (matches the Lightroom "Lens Corrections" panel), rather than
profile-lookup driven — lensfun's Canon RF zoom-lens coverage is too inconsistent to
rely on. Operates on linear-light float32 RGB in [0, 1].
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

_MAX_DISTORTION_K1 = 0.35  # radial curvature at slider extremes
_MAX_VIGNETTE_STRENGTH = 0.8  # corner brightness multiplier range at slider extremes
_MAX_CA_SHIFT_PX = 3.0  # R/B channel radial shift (in normalized units) at full CA removal


@dataclass(frozen=True)
class LensSettings:
    distortion: float = 0.0  # -100..100 (negative = pull corners in, positive = push corners out)
    vignetting: float = 0.0  # -100..100 (negative = darken corners, positive = brighten corners)
    remove_chromatic_aberration: bool = False


def apply_lens_correction(rgb: np.ndarray, settings: LensSettings) -> np.ndarray:
    img = rgb
    if settings.distortion != 0.0:
        img = _correct_distortion(img, settings.distortion)
    if settings.vignetting != 0.0:
        img = _correct_vignetting(img, settings.vignetting)
    if settings.remove_chromatic_aberration:
        img = _correct_chromatic_aberration(img)
    return img


def _normalized_grid(height: int, width: int) -> tuple[np.ndarray, np.ndarray, float, float, float]:
    center_x, center_y = width / 2.0, height / 2.0
    scale = max(center_x, center_y)
    ys, xs = np.mgrid[0:height, 0:width].astype(np.float32)
    nx = (xs - center_x) / scale
    ny = (ys - center_y) / scale
    return nx, ny, center_x, center_y, scale


def _correct_distortion(img: np.ndarray, amount: float) -> np.ndarray:
    height, width = img.shape[:2]
    nx, ny, center_x, center_y, scale = _normalized_grid(height, width)
    k1 = (amount / 100.0) * _MAX_DISTORTION_K1
    r2 = nx * nx + ny * ny
    factor = 1.0 + k1 * r2
    src_x = center_x + nx * factor * scale
    src_y = center_y + ny * factor * scale
    return cv2.remap(img, src_x, src_y, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


def _correct_vignetting(img: np.ndarray, amount: float) -> np.ndarray:
    height, width = img.shape[:2]
    nx, ny, *_ = _normalized_grid(height, width)
    r2 = nx * nx + ny * ny
    strength = (amount / 100.0) * _MAX_VIGNETTE_STRENGTH
    gain = np.clip(1.0 + strength * r2, 0.0, None)
    return img * gain[..., None]


def _correct_chromatic_aberration(img: np.ndarray) -> np.ndarray:
    height, width = img.shape[:2]
    nx, ny, center_x, center_y, scale = _normalized_grid(height, width)
    radius = np.sqrt(nx * nx + ny * ny)
    shift = (_MAX_CA_SHIFT_PX / scale) * radius

    def shifted_channel(channel: np.ndarray, sign: float) -> np.ndarray:
        factor = 1.0 + sign * shift
        src_x = center_x + nx * factor * scale
        src_y = center_y + ny * factor * scale
        return cv2.remap(channel, src_x, src_y, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

    red = shifted_channel(np.ascontiguousarray(img[..., 0]), -1.0)
    blue = shifted_channel(np.ascontiguousarray(img[..., 2]), 1.0)
    return np.stack([red, img[..., 1], blue], axis=-1)
