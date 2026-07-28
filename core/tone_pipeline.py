"""Tone and colour adjustments: the Basic panel.

Operates on linear-light float32 RGB in [0, 1] (the same convention used across
`core/`), so it composes cleanly before/after lens correction and denoise.

This module is the reference implementation. `core.preview_renderer` mirrors it on
the GPU for interactive editing and is held to it by parity tests.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

_WORKING_GAMMA = 1.0 / 2.2
_POINT_RANGE = 0.25  # how far blacks/whites sliders can move the black/white input points
NEUTRAL_TEMPERATURE = 5500.0  # Kelvin at which the white balance sliders do nothing
MIN_TEMPERATURE = 2000.0
MAX_TEMPERATURE = 12000.0
_TINT_STRENGTH = 0.0012  # green/magenta gain per tint unit
# How far a full highlight/shadow push can move a tone. Pushing both ends hard is a
# normal edit, so this has to recover detail without collapsing the tonal range
# between them — calibrated so a heavy preset keeps most of its original spread.
HIGHLIGHT_SHADOW_STRENGTH = 0.28
_CLARITY_RADIUS = 0.02  # local-contrast blur radius, as a fraction of the image's long edge
_DEHAZE_STRENGTH = 0.6


@dataclass(frozen=True)
class ToneSettings:
    # White balance. The RAW is already decoded with the camera's as-shot balance, so
    # these adjust *on top of* that: NEUTRAL_TEMPERATURE is the no-op point rather
    # than a colorimetric absolute. The numbers still read in familiar Kelvin/tint units.
    temperature: float = NEUTRAL_TEMPERATURE  # Kelvin
    tint: float = 0.0  # -150..150, green to magenta
    exposure: float = 0.0  # stops, typically -5..+5
    contrast: float = 0.0  # -100..100
    highlights: float = 0.0  # -100..100
    shadows: float = 0.0  # -100..100
    whites: float = 0.0  # -100..100
    blacks: float = 0.0  # -100..100
    clarity: float = 0.0  # -100..100, midtone local contrast
    vibrance: float = 0.0  # -100..100, saturation weighted toward muted colours
    saturation: float = 0.0  # -100..100, uniform across all colours
    dehaze: float = 0.0  # -100..100


def apply_tone(rgb: np.ndarray, settings: ToneSettings) -> np.ndarray:
    img = rgb.astype(np.float32)

    # White balance belongs in linear light, before any curve shaping, because it is a
    # correction to the light the sensor saw rather than a look applied afterwards.
    gains = white_balance_gains(settings.temperature, settings.tint)
    if gains != (1.0, 1.0, 1.0):
        img = img * np.asarray(gains, dtype=np.float32)

    img = img * (2.0**settings.exposure)

    # Highlights/Shadows/Whites/Blacks/Contrast behave the way editors present them
    # (as perceptual-brightness adjustments), so do the curve shaping in gamma space.
    img = np.power(np.clip(img, 0.0, None), _WORKING_GAMMA)

    if settings.dehaze:
        img = _apply_dehaze(img, settings.dehaze)

    black_point = (settings.blacks / 100.0) * _POINT_RANGE
    white_point = 1.0 + (settings.whites / 100.0) * _POINT_RANGE
    img = (img - black_point) / max(white_point - black_point, 1e-6)

    luminance = img.mean(axis=-1, keepdims=True)
    shadow_mask = np.clip(1.0 - 2.0 * luminance, 0.0, 1.0) ** 2
    highlight_mask = np.clip(2.0 * luminance - 1.0, 0.0, 1.0) ** 2
    img = img + (settings.shadows / 100.0) * HIGHLIGHT_SHADOW_STRENGTH * shadow_mask
    img = img + (settings.highlights / 100.0) * HIGHLIGHT_SHADOW_STRENGTH * highlight_mask

    contrast_amount = settings.contrast / 100.0
    img = 0.5 + (img - 0.5) * (1.0 + contrast_amount)

    if settings.clarity:
        img = _apply_clarity(img, settings.clarity)
    if settings.vibrance:
        img = _apply_vibrance(img, settings.vibrance)
    if settings.saturation:
        img = _apply_saturation(img, settings.saturation)

    img = np.clip(img, 0.0, 1.0)
    img = np.power(img, 1.0 / _WORKING_GAMMA)
    return img.astype(np.float32)


def _blackbody_rgb(kelvin: float) -> tuple[float, float, float]:
    """Approximate the RGB colour of a blackbody radiator at `kelvin`.

    The usual piecewise fit to the Planckian locus; accurate enough for a white
    balance control, where what matters is a smooth, monotonic warm/cool response.
    """
    temperature = min(max(kelvin, 1000.0), 40000.0) / 100.0

    if temperature <= 66:
        red = 255.0
        green = 99.4708025861 * math.log(temperature) - 161.1195681661
    else:
        red = 329.698727446 * ((temperature - 60) ** -0.1332047592)
        green = 288.1221695283 * ((temperature - 60) ** -0.0755148492)

    if temperature >= 66:
        blue = 255.0
    elif temperature <= 19:
        blue = 0.0
    else:
        blue = 138.5177312231 * math.log(temperature - 10) - 305.0447927307

    clamp = lambda value: min(max(value, 1.0), 255.0)  # noqa: E731 - local, single use
    return (clamp(red), clamp(green), clamp(blue))


def white_balance_gains(temperature: float, tint: float) -> tuple[float, float, float]:
    """Per-channel gains for a temperature/tint pair, normalised so the neutral
    temperature with no tint leaves the image untouched."""
    if temperature == NEUTRAL_TEMPERATURE and tint == 0.0:
        return (1.0, 1.0, 1.0)

    target = _blackbody_rgb(temperature)
    reference = _blackbody_rgb(NEUTRAL_TEMPERATURE)
    # Raising the temperature should warm the image, which means attenuating blue
    # relative to red — the inverse of the illuminant's own colour.
    red, green, blue = (reference[i] / target[i] for i in range(3))

    # Tint trades green against magenta (red+blue together).
    green *= 1.0 - tint * _TINT_STRENGTH
    magenta = 1.0 + tint * _TINT_STRENGTH * 0.5
    red *= magenta
    blue *= magenta

    # Normalise on green so the adjustment shifts colour without shifting brightness.
    return (red / green, 1.0, blue / green)


def _apply_saturation(img: np.ndarray, amount: float) -> np.ndarray:
    """Uniform saturation, unlike vibrance which protects already-saturated colours."""
    grey = img.mean(axis=-1, keepdims=True)
    return grey + (img - grey) * (1.0 + amount / 100.0)


def clarity_blur_radius(height: int, width: int) -> int:
    """Odd-sized Gaussian kernel scaled to the image, so clarity looks the same on a
    screen-sized preview as it does on the full-resolution export."""
    radius = max(1, int(round(max(height, width) * _CLARITY_RADIUS)))
    return radius * 2 + 1


def _apply_clarity(img: np.ndarray, amount: float) -> np.ndarray:
    """Unsharp mask on a large radius: boosts midtone local contrast, not edge detail.

    Weighted toward midtones so it doesn't crush blacks or blow highlights, which is
    what distinguishes clarity from plain contrast.
    """
    kernel = clarity_blur_radius(img.shape[0], img.shape[1])
    blurred = cv2.GaussianBlur(img, (kernel, kernel), 0)
    luminance = img.mean(axis=-1, keepdims=True)
    midtone_weight = 1.0 - (2.0 * np.clip(luminance, 0.0, 1.0) - 1.0) ** 2
    return img + (amount / 100.0) * midtone_weight * (img - blurred)


def _apply_vibrance(img: np.ndarray, amount: float) -> np.ndarray:
    """Saturation weighted by how muted a pixel already is.

    Already-saturated colours (often skin tones and skies) move least, which is the
    difference between vibrance and a flat saturation slider.
    """
    grey = img.mean(axis=-1, keepdims=True)
    deviation = img - grey
    current_saturation = np.abs(deviation).max(axis=-1, keepdims=True)
    weight = 1.0 - np.clip(current_saturation * 2.0, 0.0, 1.0)
    return grey + deviation * (1.0 + (amount / 100.0) * weight)


def _apply_dehaze(img: np.ndarray, amount: float) -> np.ndarray:
    """Remove (or add) the flat veiling light that haze lays over a scene.

    Haze shows up as a floor under the darkest channel; lifting the image off that
    floor restores contrast and colour, which is why this runs before the black/white
    points rather than as ordinary contrast.
    """
    strength = (amount / 100.0) * _DEHAZE_STRENGTH
    dark_channel = img.min(axis=-1, keepdims=True)
    veil = float(np.percentile(dark_channel, 90.0))
    if veil <= 1e-6:
        return img
    return (img - strength * veil) / max(1.0 - strength * veil, 1e-6)
