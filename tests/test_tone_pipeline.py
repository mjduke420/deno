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


def _textured_image(size=64):
    """Fine texture on a mid grey, so local-contrast effects are measurable."""
    rng = np.random.default_rng(0)
    base = np.full((size, size, 3), 0.25, dtype=np.float32)
    return np.clip(base + rng.normal(0, 0.02, base.shape).astype(np.float32), 0.0, 1.0)


def _colored_image(saturation, size=32):
    grey = 0.25
    img = np.full((size, size, 3), grey, dtype=np.float32)
    img[..., 0] += saturation
    img[..., 2] -= saturation
    return np.clip(img, 0.0, 1.0)


# ---------- clarity ----------


def test_clarity_increases_local_contrast():
    img = _textured_image()
    boosted = apply_tone(img, ToneSettings(clarity=100.0))
    neutral = apply_tone(img, ToneSettings())

    assert boosted.std() > neutral.std()


def test_negative_clarity_softens_local_contrast():
    img = _textured_image()
    softened = apply_tone(img, ToneSettings(clarity=-100.0))
    neutral = apply_tone(img, ToneSettings())

    assert softened.std() < neutral.std()


def test_clarity_of_zero_is_identity():
    img = _textured_image()
    np.testing.assert_allclose(apply_tone(img, ToneSettings(clarity=0.0)), apply_tone(img, ToneSettings()))


# ---------- vibrance ----------


def test_vibrance_increases_saturation():
    img = _colored_image(0.05)
    boosted = apply_tone(img, ToneSettings(vibrance=100.0))

    spread_before = float(img.max(axis=-1).mean() - img.min(axis=-1).mean())
    spread_after = float(boosted.max(axis=-1).mean() - boosted.min(axis=-1).mean())
    assert spread_after > spread_before


def test_vibrance_affects_muted_colours_more_than_saturated_ones():
    """That weighting is what separates vibrance from a plain saturation slider."""

    def relative_gain(saturation):
        img = _colored_image(saturation)
        before = float(img.max(axis=-1).mean() - img.min(axis=-1).mean())
        after_img = apply_tone(img, ToneSettings(vibrance=100.0))
        after = float(after_img.max(axis=-1).mean() - after_img.min(axis=-1).mean())
        return after / before

    assert relative_gain(0.03) > relative_gain(0.30)


def test_negative_vibrance_desaturates():
    img = _colored_image(0.08)
    muted = apply_tone(img, ToneSettings(vibrance=-100.0))

    spread_before = float(img.max(axis=-1).mean() - img.min(axis=-1).mean())
    spread_after = float(muted.max(axis=-1).mean() - muted.min(axis=-1).mean())
    assert spread_after < spread_before


# ---------- dehaze ----------


def test_dehaze_deepens_a_hazy_image():
    hazy = np.full((32, 32, 3), 0.35, dtype=np.float32)
    hazy[:16] = 0.55  # low-contrast, lifted-black scene

    dehazed = apply_tone(hazy, ToneSettings(dehaze=100.0))
    neutral = apply_tone(hazy, ToneSettings())

    assert dehazed.min() < neutral.min()  # blacks come back down
    assert dehazed.std() > neutral.std()  # contrast recovered


def test_negative_dehaze_flattens_the_image():
    img = _textured_image()
    hazed = apply_tone(img, ToneSettings(dehaze=-100.0))
    neutral = apply_tone(img, ToneSettings())

    assert hazed.mean() > neutral.mean()


def test_new_sliders_default_to_no_op():
    img = _textured_image()
    settings = ToneSettings()
    assert settings.clarity == 0.0 and settings.vibrance == 0.0 and settings.dehaze == 0.0
    np.testing.assert_allclose(apply_tone(img, settings), img, atol=1e-5)


def test_output_is_always_clipped_to_valid_range():
    rgb = np.array([[[0.0, 0.5, 1.0]]], dtype=np.float32)
    result = apply_tone(rgb, ToneSettings(exposure=5.0, whites=-100.0, blacks=100.0))
    assert result.min() >= 0.0
    assert result.max() <= 1.0
