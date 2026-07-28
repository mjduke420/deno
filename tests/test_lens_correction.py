import numpy as np
import pytest

from core.lens_correction import LensSettings, apply_lens_correction


def _test_image(size: int = 64) -> np.ndarray:
    # A centered bright square on a dark background, so distortion/CA warps are visible.
    img = np.zeros((size, size, 3), dtype=np.float32)
    quarter = size // 4
    img[quarter : size - quarter, quarter : size - quarter, :] = 1.0
    return img


def test_default_settings_are_identity():
    img = _test_image()
    result = apply_lens_correction(img, LensSettings())
    np.testing.assert_array_equal(result, img)


def test_distortion_changes_pixel_values_at_edges():
    img = _test_image()
    result = apply_lens_correction(img, LensSettings(distortion=80.0))
    assert not np.array_equal(result, img)
    assert result.shape == img.shape


def test_positive_vignetting_brightens_corners_more_than_center():
    img = np.full((64, 64, 3), 0.5, dtype=np.float32)
    result = apply_lens_correction(img, LensSettings(vignetting=100.0))

    center_value = result[32, 32, 0]
    corner_value = result[2, 2, 0]
    assert corner_value > center_value
    assert center_value == pytest.approx(0.5, abs=1e-4)


def test_negative_vignetting_darkens_corners_more_than_center():
    img = np.full((64, 64, 3), 0.5, dtype=np.float32)
    result = apply_lens_correction(img, LensSettings(vignetting=-100.0))

    center_value = result[32, 32, 0]
    corner_value = result[2, 2, 0]
    assert corner_value < center_value


def test_vignetting_never_produces_negative_values():
    img = np.full((64, 64, 3), 0.5, dtype=np.float32)
    result = apply_lens_correction(img, LensSettings(vignetting=-100.0))
    assert result.min() >= 0.0


def test_chromatic_aberration_removal_shifts_only_red_and_blue_channels():
    img = _test_image()
    result = apply_lens_correction(img, LensSettings(remove_chromatic_aberration=True))

    # Green channel is untouched (it's the CA reference channel); R/B are radially shifted.
    np.testing.assert_array_equal(result[..., 1], img[..., 1])
    assert not np.array_equal(result[..., 0], img[..., 0])
    assert not np.array_equal(result[..., 2], img[..., 2])
