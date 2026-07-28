"""Exposure/tone adjustments: Exposure, Contrast, Highlights, Shadows, Whites, Blacks.

Operates on linear-light float32 RGB in [0, 1] (the same convention used across
`core/`), so it composes cleanly before/after lens correction and denoise.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

_WORKING_GAMMA = 1.0 / 2.2
_POINT_RANGE = 0.25  # how far blacks/whites sliders can move the black/white input points


@dataclass(frozen=True)
class ToneSettings:
    exposure: float = 0.0  # stops, typically -5..+5
    contrast: float = 0.0  # -100..100
    highlights: float = 0.0  # -100..100
    shadows: float = 0.0  # -100..100
    whites: float = 0.0  # -100..100
    blacks: float = 0.0  # -100..100


def apply_tone(rgb: np.ndarray, settings: ToneSettings) -> np.ndarray:
    img = rgb.astype(np.float32) * (2.0**settings.exposure)

    # Highlights/Shadows/Whites/Blacks/Contrast behave the way editors present them
    # (as perceptual-brightness adjustments), so do the curve shaping in gamma space.
    img = np.power(np.clip(img, 0.0, None), _WORKING_GAMMA)

    black_point = (settings.blacks / 100.0) * _POINT_RANGE
    white_point = 1.0 + (settings.whites / 100.0) * _POINT_RANGE
    img = (img - black_point) / max(white_point - black_point, 1e-6)

    luminance = img.mean(axis=-1, keepdims=True)
    shadow_mask = np.clip(1.0 - 2.0 * luminance, 0.0, 1.0) ** 2
    highlight_mask = np.clip(2.0 * luminance - 1.0, 0.0, 1.0) ** 2
    img = img + (settings.shadows / 100.0) * 0.5 * shadow_mask
    img = img + (settings.highlights / 100.0) * 0.5 * highlight_mask

    contrast_amount = settings.contrast / 100.0
    img = 0.5 + (img - 0.5) * (1.0 + contrast_amount)

    img = np.clip(img, 0.0, 1.0)
    img = np.power(img, 1.0 / _WORKING_GAMMA)
    return img.astype(np.float32)
