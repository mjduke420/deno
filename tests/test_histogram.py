import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from ui.histogram import BINS, HistogramWidget, clipping_fractions, compute_histogram


@pytest.fixture(scope="session")
def qt_app():
    return QApplication.instance() or QApplication([])


def _solid(value, size=32):
    return np.full((size, size, 3), value, dtype=np.uint8)


# ---------- computation ----------


def test_histogram_has_one_row_per_channel_and_256_bins():
    assert compute_histogram(_solid(128)).shape == (3, BINS)


def test_solid_image_puts_every_pixel_in_one_bin():
    histogram = compute_histogram(_solid(200, size=10))

    assert histogram[0, 200] == 100
    assert histogram[0].sum() == 100


def test_channels_are_counted_separately():
    img = np.zeros((4, 4, 3), dtype=np.uint8)
    img[..., 0] = 10
    img[..., 1] = 20
    img[..., 2] = 30

    histogram = compute_histogram(img)

    assert histogram[0, 10] == 16
    assert histogram[1, 20] == 16
    assert histogram[2, 30] == 16


def test_non_image_input_is_rejected():
    with pytest.raises(ValueError):
        compute_histogram(np.zeros((4, 4), dtype=np.uint8))


# ---------- clipping ----------


def test_midtone_image_reports_no_clipping():
    shadows, highlights = clipping_fractions(_solid(128))
    assert shadows == 0.0 and highlights == 0.0


def test_pure_black_is_reported_as_shadow_clipping():
    shadows, highlights = clipping_fractions(_solid(0))
    assert shadows == 1.0 and highlights == 0.0


def test_pure_white_is_reported_as_highlight_clipping():
    shadows, highlights = clipping_fractions(_solid(255))
    assert highlights == 1.0 and shadows == 0.0


def test_clipping_is_measured_as_a_fraction_of_pixels():
    img = _solid(128, size=10)
    img[:1] = 255  # one row of ten

    _, highlights = clipping_fractions(img)
    assert highlights == pytest.approx(0.1)


def test_clipping_counts_a_pixel_blown_in_any_single_channel():
    img = _solid(100, size=10)
    img[..., 0] = 255  # red only

    _, highlights = clipping_fractions(img)
    assert highlights == 1.0


def test_empty_image_reports_no_clipping():
    assert clipping_fractions(np.zeros((0, 0, 3), dtype=np.uint8)) == (0.0, 0.0)


# ---------- widget ----------


def test_widget_lamps_follow_the_image(qt_app):
    widget = HistogramWidget()

    widget.set_image(_solid(128))
    assert not widget.shadows_clipped and not widget.highlights_clipped

    widget.set_image(_solid(255))
    assert widget.highlights_clipped

    widget.set_image(_solid(0))
    assert widget.shadows_clipped


def test_widget_ignores_a_negligible_amount_of_clipping(qt_app):
    """A handful of specular pixels shouldn't light the warning."""
    img = _solid(128, size=100)
    img[0, 0] = 255  # 1 pixel in 10,000

    widget = HistogramWidget()
    widget.set_image(img)

    assert not widget.highlights_clipped


def test_widget_handles_being_cleared(qt_app):
    widget = HistogramWidget()
    widget.set_image(_solid(255))

    widget.set_image(None)

    assert not widget.highlights_clipped and not widget.shadows_clipped


def test_widget_renders_without_error(qt_app):
    """paintEvent must survive both an empty and a populated state."""
    widget = HistogramWidget()
    widget.resize(200, 110)
    widget.grab()  # forces a paint

    widget.set_image(_solid(90))
    widget.grab()
