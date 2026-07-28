import numpy as np
import pytest

from core.tone_pipeline import ToneSettings, apply_tone


def test_default_settings_are_identity():
    rgb = np.array([[[0.05, 0.3, 0.8]]], dtype=np.float32)
    result = apply_tone(rgb, ToneSettings())
    np.testing.assert_allclose(result, rgb, atol=1e-5)


def test_exposure_doubles_linear_value():
    rgb = np.full((1, 1, 3), 0.1, dtype=np.float32)
    result = apply_tone(rgb, ToneSettings(exposure=1.0))
    np.testing.assert_allclose(result, 0.2, atol=1e-4)


def test_exposure_negative_stop_halves_linear_value():
    rgb = np.full((1, 1, 3), 0.4, dtype=np.float32)
    result = apply_tone(rgb, ToneSettings(exposure=-1.0))
    np.testing.assert_allclose(result, 0.2, atol=1e-4)


def test_contrast_spreads_values_away_from_midpoint():
    # Contrast pivots around gamma-space 0.5 (~0.18 linear, i.e. photographic middle gray),
    # so pick values clearly below/above that pivot rather than around linear 0.5.
    dark = np.full((1, 1, 3), 0.05, dtype=np.float32)
    bright = np.full((1, 1, 3), 0.8, dtype=np.float32)
    settings = ToneSettings(contrast=50.0)

    dark_result = apply_tone(dark, settings)[0, 0, 0]
    bright_result = apply_tone(bright, settings)[0, 0, 0]

    assert dark_result < 0.05
    assert bright_result > 0.8


def test_shadows_lift_dark_regions_without_much_affecting_bright():
    dark = np.full((1, 1, 3), 0.1, dtype=np.float32)
    bright = np.full((1, 1, 3), 0.9, dtype=np.float32)
    settings = ToneSettings(shadows=100.0)

    dark_result = apply_tone(dark, settings)[0, 0, 0]
    bright_result = apply_tone(bright, settings)[0, 0, 0]

    assert dark_result > 0.1
    assert bright_result == pytest.approx(0.9, abs=1e-3)


def test_highlights_reduce_bright_regions_without_much_affecting_dark():
    dark = np.full((1, 1, 3), 0.1, dtype=np.float32)
    bright = np.full((1, 1, 3), 0.9, dtype=np.float32)
    settings = ToneSettings(highlights=-100.0)

    dark_result = apply_tone(dark, settings)[0, 0, 0]
    bright_result = apply_tone(bright, settings)[0, 0, 0]

    assert bright_result < 0.9
    assert dark_result == pytest.approx(0.1, abs=1e-3)


def test_output_is_always_clipped_to_valid_range():
    rgb = np.array([[[0.0, 0.5, 1.0]]], dtype=np.float32)
    result = apply_tone(rgb, ToneSettings(exposure=5.0, whites=-100.0, blacks=100.0))
    assert result.min() >= 0.0
    assert result.max() <= 1.0
