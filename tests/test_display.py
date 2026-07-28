import numpy as np

from core.display import linear_to_srgb8, srgb8_to_linear


def test_black_stays_black():
    rgb = np.zeros((2, 2, 3), dtype=np.float32)
    result = linear_to_srgb8(rgb)
    assert result.dtype == np.uint8
    assert np.all(result == 0)


def test_white_stays_white():
    rgb = np.ones((2, 2, 3), dtype=np.float32)
    result = linear_to_srgb8(rgb)
    assert np.all(result == 255)


def test_midtone_is_brightened_by_gamma():
    # Linear 0.5 should map to well above 128 after sRGB-ish gamma (darker mid-tones lifted).
    rgb = np.full((1, 1, 3), 0.5, dtype=np.float32)
    result = linear_to_srgb8(rgb)
    assert result[0, 0, 0] > 128


def test_out_of_range_values_are_clipped():
    rgb = np.array([[[-1.0, 2.0, 0.5]]], dtype=np.float32)
    result = linear_to_srgb8(rgb)
    assert result[0, 0, 0] == 0
    assert result[0, 0, 1] == 255


def test_srgb8_to_linear_round_trips_through_linear_to_srgb8():
    rgb = np.array([[[0.05, 0.3, 0.8]]], dtype=np.float32)
    srgb8 = linear_to_srgb8(rgb)
    recovered = srgb8_to_linear(srgb8)
    np.testing.assert_allclose(recovered, rgb, atol=1e-2)  # atol covers 8-bit quantization


def test_srgb8_to_linear_black_and_white_endpoints():
    srgb8 = np.array([[[0, 128, 255]]], dtype=np.uint8)
    result = srgb8_to_linear(srgb8)
    assert result[0, 0, 0] == 0.0
    assert result[0, 0, 2] == 1.0
