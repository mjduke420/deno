import numpy as np
import pytest

from core.tone_pipeline import (
    NEUTRAL_TEMPERATURE,
    ToneSettings,
    apply_tone,
    white_balance_gains,
)


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


# ---------- white balance ----------


def test_neutral_temperature_and_tint_change_nothing():
    assert white_balance_gains(NEUTRAL_TEMPERATURE, 0.0) == (1.0, 1.0, 1.0)


def test_raising_the_temperature_warms_the_image():
    """Higher Kelvin reads as warmer, matching how the slider is labelled."""
    red, _, blue = white_balance_gains(NEUTRAL_TEMPERATURE + 2000, 0.0)
    assert red > 1.0 > blue


def test_lowering_the_temperature_cools_the_image():
    red, _, blue = white_balance_gains(NEUTRAL_TEMPERATURE - 2000, 0.0)
    assert blue > 1.0 > red


def test_white_balance_does_not_shift_overall_brightness():
    """Green is the anchor, so a colour shift shouldn't read as an exposure change."""
    for kelvin in (3000.0, 5500.0, 9000.0):
        assert white_balance_gains(kelvin, 0.0)[1] == 1.0


def test_negative_tint_pushes_green_and_positive_pushes_magenta():
    green_side = white_balance_gains(NEUTRAL_TEMPERATURE, -100.0)
    magenta_side = white_balance_gains(NEUTRAL_TEMPERATURE, 100.0)

    # Relative to green (anchored at 1.0), red and blue drop for green, rise for magenta.
    assert green_side[0] < 1.0 and green_side[2] < 1.0
    assert magenta_side[0] > 1.0 and magenta_side[2] > 1.0


def test_temperature_is_clamped_to_a_sane_range():
    """Absurd values must not produce a divide-by-zero or a black frame."""
    for kelvin in (1.0, 10.0, 1_000_000.0):
        gains = white_balance_gains(kelvin, 0.0)
        assert all(g > 0 for g in gains)


def test_warming_a_grey_image_makes_it_warmer():
    grey = np.full((8, 8, 3), 0.3, dtype=np.float32)

    warmed = apply_tone(grey, ToneSettings(temperature=8000.0))

    assert warmed[..., 0].mean() > warmed[..., 2].mean()


# ---------- saturation ----------


def test_saturation_increases_colour_spread():
    img = _colored_image(0.06)
    boosted = apply_tone(img, ToneSettings(saturation=80.0))

    before = float(img.max(axis=-1).mean() - img.min(axis=-1).mean())
    after = float(boosted.max(axis=-1).mean() - boosted.min(axis=-1).mean())
    assert after > before


def test_full_negative_saturation_produces_grey():
    img = _colored_image(0.08)
    grey = apply_tone(img, ToneSettings(saturation=-100.0))

    spread = float(grey.max(axis=-1).mean() - grey.min(axis=-1).mean())
    assert spread < 1e-3


def test_saturation_treats_muted_and_vivid_colours_alike():
    """This is what separates saturation from vibrance."""

    def gain(saturation):
        img = _colored_image(saturation)
        before = float(img.max(axis=-1).mean() - img.min(axis=-1).mean())
        after_img = apply_tone(img, ToneSettings(saturation=50.0))
        after = float(after_img.max(axis=-1).mean() - after_img.min(axis=-1).mean())
        return after / before

    assert gain(0.03) == pytest.approx(gain(0.12), rel=0.15)


def test_pushing_highlights_and_shadows_together_preserves_tonal_range():
    """Recovering both ends is an ordinary edit; it must not flatten the picture.

    Regression: highlights and shadows each moved a tone by up to 0.5, so a preset
    pushing both squeezed the histogram into a narrow band and looked muddy.
    """
    gradient = np.linspace(0.01, 0.95, 256, dtype=np.float32)
    img = np.repeat(gradient[None, :, None], 8, axis=0).repeat(3, axis=2)

    plain = apply_tone(img, ToneSettings())
    pushed = apply_tone(img, ToneSettings(highlights=-100.0, shadows=74.0))

    def spread(x):
        return float(np.percentile(x, 95) - np.percentile(x, 5))

    # A full 0..1 gradient is the worst case — real photos span less and fare better
    # (measured at 85% on a real frame). The old behaviour scored 0.30 here.
    assert spread(pushed) > spread(plain) * 0.45


def test_highlights_still_meaningfully_recover():
    """The other half of the trade-off: it has to actually do something."""
    bright = np.full((8, 8, 3), 0.85, dtype=np.float32)

    recovered = apply_tone(bright, ToneSettings(highlights=-100.0))

    assert recovered.mean() < bright.mean() * 0.8


def test_output_is_always_clipped_to_valid_range():
    rgb = np.array([[[0.0, 0.5, 1.0]]], dtype=np.float32)
    result = apply_tone(rgb, ToneSettings(exposure=5.0, whites=-100.0, blacks=100.0))
    assert result.min() >= 0.0
    assert result.max() <= 1.0
