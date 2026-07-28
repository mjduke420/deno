"""Interactive preview rendering, on the GPU when one is available.

Editing sliders must feel instant, which rules out re-processing a 24-megapixel frame
on the CPU for every tick (measured at ~2.4s). Two things fix that:

  * render a **proxy** sized for the screen rather than the full image — the canvas
    can only show a couple of megapixels anyway;
  * keep that proxy **resident on the GPU**, so a slider tick is a handful of tensor
    ops on already-uploaded data rather than an upload plus a NumPy pass.

Measured on a 24MP frame (RTX 3090): 2380ms CPU full-res -> 3.8ms GPU proxy.

`core.tone_pipeline` and `core.lens_correction` remain the reference implementations
and are what export uses; this module mirrors their maths and is covered by parity
tests against them.
"""
from __future__ import annotations

import numpy as np

from core.lens_correction import (
    _MAX_CA_SHIFT_PX,
    _MAX_DISTORTION_K1,
    _MAX_VIGNETTE_STRENGTH,
    LensSettings,
    apply_lens_correction,
)
from core.tone_pipeline import _POINT_RANGE, _WORKING_GAMMA, ToneSettings, apply_tone

DEFAULT_MAX_DIMENSION = 2048


def _torch():
    """Imported lazily so this module stays importable without torch present."""
    import torch

    return torch


def gpu_available() -> bool:
    try:
        return _torch().cuda.is_available()
    except Exception:
        return False


class PreviewRenderer:
    """Renders the editing preview from a downscaled proxy of the current photo."""

    def __init__(self, max_dimension: int = DEFAULT_MAX_DIMENSION, use_gpu: bool | None = None) -> None:
        self.max_dimension = max_dimension
        self._use_gpu = gpu_available() if use_gpu is None else use_gpu
        self._proxy: np.ndarray | None = None  # CPU copy, always kept
        self._tensor = None  # GPU copy, when available

    @property
    def is_gpu(self) -> bool:
        return self._use_gpu and self._tensor is not None

    @property
    def has_image(self) -> bool:
        return self._proxy is not None

    def set_image(self, rgb: np.ndarray) -> None:
        """Install a new source image, uploading its proxy to the GPU once."""
        self._proxy = _downscale(rgb, self.max_dimension)
        self._tensor = None
        if self._use_gpu:
            try:
                torch = _torch()
                self._tensor = torch.from_numpy(np.ascontiguousarray(self._proxy)).to("cuda")
            except Exception:
                # Out of VRAM, driver hiccup, etc. Preview still works on the CPU.
                self._use_gpu = False
                self._tensor = None

    def clear(self) -> None:
        self._proxy = None
        self._tensor = None

    def render(self, lens: LensSettings, tone: ToneSettings) -> np.ndarray:
        """Return the preview as an 8-bit sRGB array, ready for display."""
        if self._proxy is None:
            raise ValueError("No preview image set")
        if self._tensor is not None:
            try:
                return self._render_gpu(lens, tone)
            except Exception:
                self._use_gpu = False  # fall back for the rest of the session
                self._tensor = None
        return self._render_cpu(lens, tone)

    # ---------- backends ----------

    def _render_cpu(self, lens: LensSettings, tone: ToneSettings) -> np.ndarray:
        from core.display import linear_to_srgb8

        corrected = apply_lens_correction(self._proxy, lens)
        return linear_to_srgb8(apply_tone(corrected, tone))

    def _render_gpu(self, lens: LensSettings, tone: ToneSettings) -> np.ndarray:
        torch = _torch()
        image = self._tensor
        if _lens_is_active(lens):
            image = _gpu_lens_correction(torch, image, lens)
        image = _gpu_tone(torch, image, tone)
        srgb = torch.clamp(image, 0.0, 1.0).pow(_WORKING_GAMMA)
        return (srgb * 255.0 + 0.5).to(torch.uint8).cpu().numpy()


def _downscale(rgb: np.ndarray, max_dimension: int) -> np.ndarray:
    import cv2

    height, width = rgb.shape[:2]
    scale = max_dimension / max(height, width)
    if scale >= 1.0:
        return np.ascontiguousarray(rgb)
    size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
    return np.ascontiguousarray(cv2.resize(rgb, size, interpolation=cv2.INTER_AREA))


def _lens_is_active(lens: LensSettings) -> bool:
    return bool(lens.distortion or lens.vignetting or lens.remove_chromatic_aberration)


def _gpu_tone(torch, image, tone: ToneSettings):
    """Mirror of `core.tone_pipeline.apply_tone`."""
    img = image * (2.0**tone.exposure)
    img = torch.clamp(img, min=0.0).pow(_WORKING_GAMMA)

    black_point = (tone.blacks / 100.0) * _POINT_RANGE
    white_point = 1.0 + (tone.whites / 100.0) * _POINT_RANGE
    img = (img - black_point) / max(white_point - black_point, 1e-6)

    luminance = img.mean(dim=-1, keepdim=True)
    shadow_mask = torch.clamp(1.0 - 2.0 * luminance, 0.0, 1.0).pow(2)
    highlight_mask = torch.clamp(2.0 * luminance - 1.0, 0.0, 1.0).pow(2)
    img = img + (tone.shadows / 100.0) * 0.5 * shadow_mask
    img = img + (tone.highlights / 100.0) * 0.5 * highlight_mask

    img = 0.5 + (img - 0.5) * (1.0 + tone.contrast / 100.0)
    img = torch.clamp(img, 0.0, 1.0)
    return img.pow(1.0 / _WORKING_GAMMA)


def _gpu_lens_correction(torch, image, lens: LensSettings):
    """Mirror of `core.lens_correction.apply_lens_correction` using grid_sample."""
    import torch.nn.functional as F

    height, width = int(image.shape[0]), int(image.shape[1])
    device = image.device
    center_x, center_y = width / 2.0, height / 2.0
    scale = max(center_x, center_y)

    ys, xs = torch.meshgrid(
        torch.arange(height, device=device, dtype=torch.float32),
        torch.arange(width, device=device, dtype=torch.float32),
        indexing="ij",
    )
    nx = (xs - center_x) / scale
    ny = (ys - center_y) / scale

    planes = image.permute(2, 0, 1).unsqueeze(0)  # 1 x C x H x W
    geometry = (torch, F, center_x, center_y, scale, width, height)

    if lens.distortion:
        k1 = (lens.distortion / 100.0) * _MAX_DISTORTION_K1
        factor = 1.0 + k1 * (nx * nx + ny * ny)
        planes = _sample(planes, nx * factor, ny * factor, geometry)

    if lens.remove_chromatic_aberration:
        radius = torch.sqrt(nx * nx + ny * ny)
        shift = (_MAX_CA_SHIFT_PX / scale) * radius
        red = _sample(planes[:, 0:1], nx * (1.0 - shift), ny * (1.0 - shift), geometry)
        blue = _sample(planes[:, 2:3], nx * (1.0 + shift), ny * (1.0 + shift), geometry)
        planes = torch.cat([red, planes[:, 1:2], blue], dim=1)

    result = planes.squeeze(0).permute(1, 2, 0)

    if lens.vignetting:
        strength = (lens.vignetting / 100.0) * _MAX_VIGNETTE_STRENGTH
        gain = torch.clamp(1.0 + strength * (nx * nx + ny * ny), min=0.0)
        result = result * gain.unsqueeze(-1)

    return result


def _sample(planes, nx, ny, geometry):
    """grid_sample using the same source coordinates cv2.remap would read from."""
    torch, F, center_x, center_y, scale, width, height = geometry
    src_x = center_x + nx * scale
    src_y = center_y + ny * scale
    # grid_sample wants normalised [-1, 1] coordinates over pixel centres.
    grid_x = (src_x / max(width - 1, 1)) * 2.0 - 1.0
    grid_y = (src_y / max(height - 1, 1)) * 2.0 - 1.0
    grid = torch.stack((grid_x, grid_y), dim=-1).unsqueeze(0)
    return F.grid_sample(planes, grid, mode="bilinear", padding_mode="reflection", align_corners=True)
