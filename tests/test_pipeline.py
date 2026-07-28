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
