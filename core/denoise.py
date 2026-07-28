"""AI denoise: tiled GPU inference using a real-sensor-noise-trained NAFNet (SIDD) model.

The model itself only knows how to denoise one manageable tile at a time (memory
bound), so `denoise_tiled` splits the image into overlapping tiles, runs a supplied
`tile_fn` on each, and blends the results back with a feathered mask so tile seams
don't show. `tile_fn` is a plain callable so the blending logic can be unit-tested
with a cheap mock instead of the real network.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Protocol

import numpy as np
from PIL import Image

MODEL_DIR = Path(__file__).parent.parent / "models"
DEFAULT_TILE_SIZE = 512
DEFAULT_OVERLAP = 32

TileFn = Callable[[np.ndarray], np.ndarray]  # uint8 HxWx3 tile in -> uint8 HxWx3 tile out, same shape


class ProgressCallback(Protocol):
    def __call__(self, done: int, total: int) -> None: ...


def denoise_tiled(
    rgb_uint8: np.ndarray,
    tile_fn: TileFn,
    tile_size: int = DEFAULT_TILE_SIZE,
    overlap: int = DEFAULT_OVERLAP,
    progress_cb: ProgressCallback | None = None,
) -> np.ndarray:
    """Run `tile_fn` over `rgb_uint8` in overlapping tiles, blended with a feathered mask."""
    height, width = rgb_uint8.shape[:2]
    output = np.zeros((height, width, 3), dtype=np.float32)
    weight = np.zeros((height, width, 1), dtype=np.float32)

    stride = tile_size - overlap
    y_starts = _tile_starts(height, tile_size, stride)
    x_starts = _tile_starts(width, tile_size, stride)
    total = len(y_starts) * len(x_starts)
    done = 0

    for y0 in y_starts:
        y1 = min(y0 + tile_size, height)
        for x0 in x_starts:
            x1 = min(x0 + tile_size, width)
            tile = rgb_uint8[y0:y1, x0:x1]
            result_tile = tile_fn(tile).astype(np.float32)
            mask = _feather_mask(y0, y1, x0, x1, height, width, overlap)

            output[y0:y1, x0:x1] += result_tile * mask
            weight[y0:y1, x0:x1] += mask
            done += 1
            if progress_cb is not None:
                progress_cb(done, total)

    blended = output / np.clip(weight, 1e-6, None)
    return np.clip(blended, 0, 255).astype(np.uint8)


def _tile_starts(length: int, tile_size: int, stride: int) -> list[int]:
    if length <= tile_size:
        return [0]
    starts = list(range(0, length - tile_size, stride))
    starts.append(length - tile_size)  # make sure the last tile reaches the far edge
    return sorted(set(starts))


def _feather_mask(y0: int, y1: int, x0: int, x1: int, height: int, width: int, overlap: int) -> np.ndarray:
    """Linear ramp on edges that border another tile; full weight on edges at the image border."""
    h, w = y1 - y0, x1 - x0
    ramp = max(1, min(overlap, h // 2, w // 2))

    row = np.ones(h, dtype=np.float32)
    if y0 > 0:
        row[:ramp] = np.linspace(0.0, 1.0, ramp, endpoint=False)
    if y1 < height:
        row[-ramp:] = np.linspace(1.0, 0.0, ramp, endpoint=False)[::-1]

    col = np.ones(w, dtype=np.float32)
    if x0 > 0:
        col[:ramp] = np.linspace(0.0, 1.0, ramp, endpoint=False)
    if x1 < width:
        col[-ramp:] = np.linspace(1.0, 0.0, ramp, endpoint=False)[::-1]

    return (row[:, None] * col[None, :])[..., None]


class NafnetDenoiser:
    """Wraps nafnetlib's SIDD-trained NAFNet for use as a `denoise_tiled` tile_fn."""

    def __init__(self, model_id: str = "sidd_width64", device: str = "auto"):
        import torch
        from nafnetlib import DenoiseProcessor  # deferred: torch/model init is slow

        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"

        MODEL_DIR.mkdir(exist_ok=True)
        self._processor = DenoiseProcessor(model_id=model_id, model_dir=str(MODEL_DIR), device=device)

    def tile_fn(self, tile: np.ndarray) -> np.ndarray:
        result = self._processor.process(Image.fromarray(tile))
        return np.array(result, dtype=np.uint8)

    def denoise(
        self,
        rgb_uint8: np.ndarray,
        tile_size: int = DEFAULT_TILE_SIZE,
        overlap: int = DEFAULT_OVERLAP,
        progress_cb: ProgressCallback | None = None,
    ) -> np.ndarray:
        return denoise_tiled(rgb_uint8, self.tile_fn, tile_size, overlap, progress_cb)
