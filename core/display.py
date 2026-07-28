"""Convert linear-light RGB float arrays into displayable Qt images."""
from __future__ import annotations

import numpy as np
from PySide6.QtGui import QImage

_SRGB_GAMMA = 1.0 / 2.2


def linear_to_srgb8(rgb: np.ndarray) -> np.ndarray:
    """Convert a float32 linear RGB array in [0, 1] to an 8-bit sRGB-gamma array."""
    clipped = np.clip(rgb, 0.0, 1.0)
    gamma_corrected = np.power(clipped, _SRGB_GAMMA)
    return (gamma_corrected * 255.0 + 0.5).astype(np.uint8)


def srgb8_to_linear(srgb8: np.ndarray) -> np.ndarray:
    """Inverse of `linear_to_srgb8`: 8-bit sRGB-gamma array -> float32 linear RGB in [0, 1]."""
    normalized = srgb8.astype(np.float32) / 255.0
    return np.power(normalized, 1.0 / _SRGB_GAMMA)


def to_qimage(rgb: np.ndarray) -> QImage:
    """Convert an RGB array (float32 linear in [0, 1], or already-uint8 sRGB) to a QImage."""
    srgb8 = np.ascontiguousarray(rgb if rgb.dtype == np.uint8 else linear_to_srgb8(rgb))
    height, width, _ = srgb8.shape
    qimage = QImage(srgb8.data, width, height, width * 3, QImage.Format.Format_RGB888)
    return qimage.copy()  # detach from the numpy buffer before it goes out of scope
