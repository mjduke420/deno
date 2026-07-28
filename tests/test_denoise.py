import numpy as np

from core.denoise import denoise_tiled


def _gradient_image(height: int = 300, width: int = 400) -> np.ndarray:
    x = np.linspace(0, 255, width, dtype=np.float32)
    y = np.linspace(0, 255, height, dtype=np.float32)
    xx, yy = np.meshgrid(x, y)
    channel = ((xx + yy) / 2).astype(np.uint8)
    return np.stack([channel, channel, channel], axis=-1)


def test_identity_tile_fn_reconstructs_original_image():
    img = _gradient_image()
    result = denoise_tiled(img, tile_fn=lambda tile: tile, tile_size=128, overlap=16)

    assert result.shape == img.shape
    assert result.dtype == np.uint8
    # Blending an identity function should reconstruct the original near-exactly
    # (small rounding error is expected from the float accumulate/divide).
    np.testing.assert_allclose(result.astype(np.int16), img.astype(np.int16), atol=1)


def test_constant_tile_fn_produces_constant_output():
    img = _gradient_image()
    result = denoise_tiled(img, tile_fn=lambda tile: np.full_like(tile, 100), tile_size=128, overlap=16)

    assert np.all(result == 100)


def test_image_smaller_than_tile_size_still_works():
    img = _gradient_image(height=50, width=60)
    result = denoise_tiled(img, tile_fn=lambda tile: tile, tile_size=128, overlap=16)
    np.testing.assert_allclose(result.astype(np.int16), img.astype(np.int16), atol=1)


def test_progress_callback_reports_all_tiles_done():
    img = _gradient_image()
    calls = []
    denoise_tiled(img, tile_fn=lambda tile: tile, tile_size=128, overlap=16, progress_cb=lambda done, total: calls.append((done, total)))

    assert calls[-1][0] == calls[-1][1]  # last call reports done == total
    assert calls[-1][0] == len(calls)  # done increments by 1 each call, in order


def test_tile_fn_receives_correctly_shaped_tiles():
    img = _gradient_image()
    seen_shapes = set()

    def recording_tile_fn(tile: np.ndarray) -> np.ndarray:
        seen_shapes.add(tile.shape)
        return tile

    denoise_tiled(img, tile_fn=recording_tile_fn, tile_size=128, overlap=16)
    for shape in seen_shapes:
        assert shape[2] == 3
        assert shape[0] <= 128 and shape[1] <= 128
