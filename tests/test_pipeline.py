import numpy as np
import pytest

from core.pipeline import Pipeline
from core.raw_loader import RawImage


class _FakeDenoiser:
    def __init__(self):
        self.call_count = 0

    def denoise(self, rgb_uint8, progress_cb=None):
        self.call_count += 1
        return np.clip(rgb_uint8.astype(np.int16) + 10, 0, 255).astype(np.uint8)


def _make_raw_image(size: int = 8) -> RawImage:
    rgb = np.full((size, size, 3), 0.3, dtype=np.float32)
    return RawImage(rgb=rgb, iso=100.0, lens_model="Test Lens", focal_length_mm=50.0, aperture=2.8, shutter_speed=0.01)


def test_render_without_loaded_file_raises():
    pipeline = Pipeline()
    with pytest.raises(ValueError):
        pipeline.render()


def test_render_uses_raw_image_by_default():
    pipeline = Pipeline()
    pipeline._raw = _make_raw_image()
    result = pipeline.render()
    assert result.shape == (8, 8, 3)


def test_denoise_toggle_switches_render_output_without_recomputing():
    pipeline = Pipeline()
    pipeline._raw = _make_raw_image()
    without_denoise = pipeline.render()

    fake = _FakeDenoiser()
    pipeline.run_denoise(fake)
    assert fake.call_count == 1
    assert pipeline.has_denoised_base

    pipeline.denoise_enabled = True
    with_denoise = pipeline.render()
    assert not np.array_equal(with_denoise, without_denoise)

    pipeline.denoise_enabled = False
    back_to_raw = pipeline.render()
    np.testing.assert_array_equal(back_to_raw, without_denoise)

    # Re-enabling reuses the cached result rather than calling the denoiser again.
    pipeline.denoise_enabled = True
    pipeline.render()
    assert fake.call_count == 1


def test_run_denoise_without_loaded_file_raises():
    pipeline = Pipeline()
    with pytest.raises(ValueError):
        pipeline.run_denoise(_FakeDenoiser())


def test_enabling_denoise_actually_changes_the_preview():
    """Regression: the preview tracked 'was it denoised?' with a flag that went stale,
    so after a denoise run the GPU kept rendering the original noisy proxy."""
    pipeline = Pipeline()
    pipeline._raw = _make_raw_image(size=32)
    before = pipeline.render_preview().copy()

    pipeline.run_denoise(_FakeDenoiser())
    pipeline.denoise_enabled = True
    after = pipeline.render_preview()

    assert not np.array_equal(before, after), "denoised result never reached the preview"


def test_disabling_denoise_returns_the_preview_to_the_original():
    pipeline = Pipeline()
    pipeline._raw = _make_raw_image(size=32)
    original = pipeline.render_preview().copy()

    pipeline.run_denoise(_FakeDenoiser())
    pipeline.denoise_enabled = True
    pipeline.render_preview()
    pipeline.denoise_enabled = False

    np.testing.assert_array_equal(pipeline.render_preview(), original)


def test_denoise_preserves_the_full_precision_of_the_raw_decode():
    """The model works in 8-bit sRGB, but its output must not quantise the 16-bit
    decode — only the correction it computed should be applied."""

    class _NoOpDenoiser:
        """Returns its input unchanged, so the correction is exactly zero."""

        def denoise(self, rgb_uint8, progress_cb=None):
            return rgb_uint8

    pipeline = Pipeline()
    # Values deliberately between 8-bit steps, which a round-trip would flatten.
    fine_detail = np.linspace(0.20001, 0.20009, 16 * 16 * 3, dtype=np.float32).reshape(16, 16, 3)
    pipeline._raw = RawImage(
        rgb=fine_detail, iso=100.0, lens_model=None, focal_length_mm=None, aperture=None, shutter_speed=None
    )

    pipeline.run_denoise(_NoOpDenoiser())

    np.testing.assert_allclose(pipeline._denoised_base, fine_detail, atol=1e-6)
    assert len(np.unique(pipeline._denoised_base)) > 200, "8-bit round-trip flattened the data"


def test_denoise_correction_is_applied_to_the_original():
    class _BrighteningDenoiser:
        def denoise(self, rgb_uint8, progress_cb=None):
            return np.clip(rgb_uint8.astype(np.int16) + 20, 0, 255).astype(np.uint8)

    pipeline = Pipeline()
    pipeline._raw = _make_raw_image(size=16)

    pipeline.run_denoise(_BrighteningDenoiser())

    assert pipeline._denoised_base.mean() > pipeline._raw.rgb.mean()
    assert pipeline._denoised_base.max() <= 1.0  # stays in range


def test_denoise_amount_blends_between_original_and_denoised():
    """Partial strength is the answer to denoise scrubbing fine detail."""
    pipeline = Pipeline()
    pipeline._raw = _make_raw_image(size=16)
    original = pipeline._raw.rgb.copy()

    pipeline.run_denoise(_FakeDenoiser())  # brightens by ~10/255
    pipeline.denoise_enabled = True

    pipeline.denoise_amount = 1.0
    full = pipeline._base_image().copy()
    pipeline.denoise_amount = 0.5
    half = pipeline._base_image().copy()
    pipeline.denoise_amount = 0.0
    none = pipeline._base_image().copy()

    np.testing.assert_allclose(none, original, atol=1e-6)
    np.testing.assert_allclose(half, original + (full - original) * 0.5, atol=1e-6)
    assert full.mean() > half.mean() > none.mean()


@pytest.mark.parametrize("requested,expected", [(-1.0, 0.0), (0.25, 0.25), (2.0, 1.0)])
def test_denoise_amount_is_clamped(requested, expected):
    pipeline = Pipeline()
    pipeline.denoise_amount = requested
    assert pipeline.denoise_amount == expected


def test_denoise_amount_round_trips_through_edit_state():
    pipeline = Pipeline()
    pipeline.denoise_amount = 0.25
    pipeline.denoise_enabled = True

    restored = Pipeline()
    restored.apply_edit_state(pipeline.edit_state())

    assert restored.denoise_amount == 0.25
    assert restored.denoise_enabled is True


def test_changing_the_amount_updates_the_preview():
    pipeline = Pipeline()
    pipeline._raw = _make_raw_image(size=32)
    pipeline.run_denoise(_FakeDenoiser())
    pipeline.denoise_enabled = True

    pipeline.denoise_amount = 1.0
    full = pipeline.render_preview().copy()
    pipeline.denoise_amount = 0.0
    none = pipeline.render_preview()

    assert not np.array_equal(full, none)


def test_load_clears_the_denoise_cache_and_resets_the_toggle():
    pipeline = Pipeline()
    pipeline._raw = _make_raw_image()
    pipeline.run_denoise(_FakeDenoiser())
    pipeline.denoise_enabled = True
    assert pipeline.has_denoised_base

    pipeline.load("IMG_7346.CR3")

    assert not pipeline.has_denoised_base
    assert pipeline.denoise_enabled is False


def test_stale_denoise_result_is_discarded_if_a_new_file_loads_mid_run():
    pipeline = Pipeline()
    pipeline._raw = _make_raw_image()

    class _SlowDenoiserThatSwitchesFiles:
        def denoise(self, rgb_uint8, progress_cb=None):
            # Simulate a new file being opened on the main thread while this
            # (worker-thread) denoise call is still in flight.
            pipeline._raw = _make_raw_image(size=4)
            return np.clip(rgb_uint8.astype(np.int16) + 10, 0, 255).astype(np.uint8)

    pipeline.run_denoise(_SlowDenoiserThatSwitchesFiles())

    assert not pipeline.has_denoised_base
