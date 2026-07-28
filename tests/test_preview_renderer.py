"""The GPU preview must match the CPU reference, or the export won't match the screen."""
import numpy as np
import pytest

from core.display import linear_to_srgb8
from core.lens_correction import LensSettings, apply_lens_correction
from core.preview_renderer import PreviewRenderer, gpu_available
from core.tone_pipeline import ToneSettings, apply_tone

requires_gpu = pytest.mark.skipif(not gpu_available(), reason="no CUDA device")


def _test_image(height=240, width=320) -> np.ndarray:
    """A gradient with a bright patch, so tone curves and geometry both show up."""
    y = np.linspace(0.02, 0.9, height, dtype=np.float32)[:, None]
    x = np.linspace(0.02, 0.9, width, dtype=np.float32)[None, :]
    base = (y + x) / 2.0
    image = np.stack([base, base * 0.8, base * 0.6], axis=-1).astype(np.float32)
    image[height // 4 : height // 2, width // 4 : width // 2] = 0.95
    return np.ascontiguousarray(image)


def _cpu_reference(rgb, lens, tone) -> np.ndarray:
    return linear_to_srgb8(apply_tone(apply_lens_correction(rgb, lens), tone))


TONE_CASES = [
    ToneSettings(),
    ToneSettings(exposure=1.5),
    ToneSettings(exposure=-1.0),
    ToneSettings(contrast=45.0),
    ToneSettings(shadows=60.0),
    ToneSettings(highlights=-55.0),
    ToneSettings(whites=35.0, blacks=-25.0),
    ToneSettings(exposure=0.7, contrast=20.0, highlights=-30.0, shadows=40.0, whites=10.0, blacks=-5.0),
    ToneSettings(vibrance=70.0),
    ToneSettings(vibrance=-70.0),
    ToneSettings(dehaze=60.0),
    ToneSettings(dehaze=-60.0),
    ToneSettings(exposure=0.4, vibrance=40.0, dehaze=30.0),
    ToneSettings(temperature=8000.0),
    ToneSettings(temperature=3200.0),
    ToneSettings(tint=-60.0),
    ToneSettings(tint=60.0),
    ToneSettings(saturation=60.0),
    ToneSettings(saturation=-60.0),
    # The Skittles preset, exercised end to end through the GPU path.
    ToneSettings(
        temperature=5850.0, tint=-8.0, contrast=30.0, highlights=-100.0, shadows=74.0,
        whites=38.0, blacks=-20.0, clarity=15.0, dehaze=30.0, vibrance=40.0, saturation=-5.0,
    ),
]


# ---------- proxy behaviour (no GPU required) ----------


def test_large_images_are_downscaled_to_the_proxy_limit():
    renderer = PreviewRenderer(max_dimension=128, use_gpu=False)
    renderer.set_image(_test_image(600, 900))

    result = renderer.render(LensSettings(), ToneSettings())

    assert max(result.shape[:2]) == 128
    assert result.shape[1] > result.shape[0]  # aspect ratio kept


def test_small_images_are_not_upscaled():
    renderer = PreviewRenderer(max_dimension=4096, use_gpu=False)
    renderer.set_image(_test_image(60, 80))

    assert renderer.render(LensSettings(), ToneSettings()).shape[:2] == (60, 80)


def test_render_without_an_image_raises():
    with pytest.raises(ValueError):
        PreviewRenderer(use_gpu=False).render(LensSettings(), ToneSettings())


def test_clear_forgets_the_image():
    renderer = PreviewRenderer(use_gpu=False)
    renderer.set_image(_test_image())
    assert renderer.has_image

    renderer.clear()

    assert not renderer.has_image


def test_cpu_backend_matches_the_reference_pipeline_exactly():
    rgb = _test_image()
    renderer = PreviewRenderer(max_dimension=4096, use_gpu=False)
    renderer.set_image(rgb)

    tone = ToneSettings(exposure=0.5, contrast=25.0, shadows=30.0)
    np.testing.assert_array_equal(
        renderer.render(LensSettings(), tone), _cpu_reference(rgb, LensSettings(), tone)
    )


# ---------- GPU parity ----------


@requires_gpu
@pytest.mark.parametrize("tone", TONE_CASES)
def test_gpu_tone_matches_cpu(tone):
    rgb = _test_image()
    renderer = PreviewRenderer(max_dimension=4096, use_gpu=True)
    renderer.set_image(rgb)
    assert renderer.is_gpu

    gpu = renderer.render(LensSettings(), tone).astype(np.int16)
    cpu = _cpu_reference(rgb, LensSettings(), tone).astype(np.int16)

    # Both are 8-bit quantised; allow a single level of float-ordering difference.
    assert np.abs(gpu - cpu).max() <= 1
    assert np.abs(gpu - cpu).mean() < 0.05


@requires_gpu
@pytest.mark.parametrize(
    "lens",
    [
        LensSettings(vignetting=-60.0),
        LensSettings(vignetting=45.0),
        LensSettings(distortion=30.0),
        LensSettings(distortion=-30.0),
    ],
)
def test_gpu_lens_correction_matches_cpu(lens):
    rgb = _test_image()
    renderer = PreviewRenderer(max_dimension=4096, use_gpu=True)
    renderer.set_image(rgb)

    gpu = renderer.render(lens, ToneSettings()).astype(np.int16)
    cpu = _cpu_reference(rgb, lens, ToneSettings()).astype(np.int16)

    # Geometric resampling differs slightly at edges between cv2.remap and
    # grid_sample; the interior must agree closely.
    interior = (slice(8, -8), slice(8, -8))
    assert np.abs(gpu[interior] - cpu[interior]).mean() < 1.5


@requires_gpu
def test_gpu_combined_lens_and_tone_matches_cpu():
    rgb = _test_image()
    lens = LensSettings(distortion=20.0, vignetting=-40.0)
    tone = ToneSettings(exposure=0.6, contrast=25.0, shadows=35.0)
    renderer = PreviewRenderer(max_dimension=4096, use_gpu=True)
    renderer.set_image(rgb)

    gpu = renderer.render(lens, tone).astype(np.int16)
    cpu = _cpu_reference(rgb, lens, tone).astype(np.int16)

    interior = (slice(8, -8), slice(8, -8))
    assert np.abs(gpu[interior] - cpu[interior]).mean() < 2.0


@requires_gpu
@pytest.mark.parametrize("clarity", [60.0, -60.0])
def test_gpu_clarity_matches_cpu(clarity):
    """Clarity blurs, so GPU and CPU differ slightly at the border where the two
    implementations pad differently; the interior must agree."""
    rgb = _test_image()
    renderer = PreviewRenderer(max_dimension=4096, use_gpu=True)
    renderer.set_image(rgb)
    tone = ToneSettings(clarity=clarity)

    gpu = renderer.render(LensSettings(), tone).astype(np.int16)
    cpu = _cpu_reference(rgb, LensSettings(), tone).astype(np.int16)

    interior = (slice(16, -16), slice(16, -16))
    assert np.abs(gpu[interior] - cpu[interior]).mean() < 1.5


@requires_gpu
def test_gpu_output_is_display_ready_uint8():
    renderer = PreviewRenderer(use_gpu=True)
    renderer.set_image(_test_image())

    result = renderer.render(LensSettings(), ToneSettings(exposure=3.0))

    assert result.dtype == np.uint8
    assert result.shape[2] == 3
    assert result.min() >= 0 and result.max() <= 255


@requires_gpu
def test_switching_images_replaces_the_resident_proxy():
    renderer = PreviewRenderer(max_dimension=4096, use_gpu=True)
    renderer.set_image(np.full((64, 64, 3), 0.1, dtype=np.float32))
    dark = renderer.render(LensSettings(), ToneSettings()).mean()

    renderer.set_image(np.full((64, 64, 3), 0.8, dtype=np.float32))
    bright = renderer.render(LensSettings(), ToneSettings()).mean()

    assert bright > dark
