"""Orchestrates the RAW-decode -> (denoise) -> lens-correction -> tone -> display pipeline.

Expensive stages (RAW decode, AI denoise) are cached separately from the cheap,
live-adjustable ones (lens correction, tone), so dragging a slider never re-triggers
GPU work — only loading a new file or (re-)running denoise does.
"""
from __future__ import annotations

from typing import Protocol

import numpy as np

from core.display import linear_to_srgb8, srgb8_to_linear
from core.edit_state import EditState
from core.lens_correction import LensSettings, apply_lens_correction
from core.preview_renderer import PreviewRenderer
from core.raw_loader import RawImage, load_raw
from core.tone_pipeline import ToneSettings, apply_tone


class Denoiser(Protocol):
    def denoise(self, rgb_uint8: np.ndarray, progress_cb: object = None) -> np.ndarray: ...


class Pipeline:
    def __init__(self, preview: PreviewRenderer | None = None) -> None:
        self._raw: RawImage | None = None
        self._denoised_base: np.ndarray | None = None  # linear RGB, cached until reload/re-denoise
        self.lens = LensSettings()
        self.tone = ToneSettings()
        self.denoise_enabled = False
        # Interactive preview runs from a GPU-resident proxy; `render()` remains the
        # full-resolution path used for export.
        self.preview = preview if preview is not None else PreviewRenderer()
        self._preview_source: np.ndarray | None = None

    def load(self, path: str) -> RawImage:
        self._raw = load_raw(path)
        self._denoised_base = None
        self.denoise_enabled = False
        self._refresh_preview_source()
        return self._raw

    @property
    def raw(self) -> RawImage | None:
        return self._raw

    @property
    def has_denoised_base(self) -> bool:
        return self._denoised_base is not None

    def edit_state(self) -> EditState:
        """The current adjustments, bundled for persistence in the catalog."""
        return EditState(tone=self.tone, lens=self.lens, denoise_enabled=self.denoise_enabled)

    def apply_edit_state(self, state: EditState) -> None:
        """Restore a photo's saved adjustments.

        `denoise_enabled` is remembered here, but `render` only uses a denoised base
        once one actually exists for the loaded file — so a photo saved with denoise on
        shows un-denoised until the GPU pass has been re-run for it.
        """
        self.tone = state.tone
        self.lens = state.lens
        self.denoise_enabled = state.denoise_enabled

    def run_denoise(self, denoiser: Denoiser, progress_cb=None) -> None:
        """Blocking (intended to run on a background thread). Denoises the neutral base
        rendering (no lens/tone applied) and caches the result as linear RGB.

        If a different file gets loaded while this is running (e.g. the worker thread
        is mid-run on a background QThread and the user opens a new RAW on the main
        thread), the stale result is discarded instead of being cached against the
        now-current file.
        """
        if self._raw is None:
            raise ValueError("No RAW file loaded")
        raw_at_start = self._raw
        original = raw_at_start.rgb
        noisy_srgb8 = linear_to_srgb8(original)
        denoised_srgb8 = denoiser.denoise(noisy_srgb8, progress_cb=progress_cb)

        if self._raw is raw_at_start:
            # The model only speaks 8-bit sRGB (that is what it was trained on), but
            # adopting its output wholesale would discard the 16-bit RAW decode and
            # leave every later edit working on quantised data. Instead take only what
            # the model *changed* and apply that to the full-precision original, so
            # detail the model left alone keeps its original bit depth.
            noise = srgb8_to_linear(denoised_srgb8) - srgb8_to_linear(noisy_srgb8)
            self._denoised_base = np.clip(original + noise, 0.0, 1.0).astype(np.float32)
            self._invalidate_preview_source()

    def render(self) -> np.ndarray:
        """Full-resolution render, in linear RGB. Used for export."""
        if self._raw is None:
            raise ValueError("No RAW file loaded")
        img = apply_lens_correction(self._base_image(), self.lens)
        return apply_tone(img, self.tone)

    def render_preview(self) -> np.ndarray:
        """Screen-resolution render as 8-bit sRGB, fast enough for live slider feedback."""
        if self._raw is None:
            raise ValueError("No RAW file loaded")
        base = self._base_image()
        # Compared by identity rather than a "was it denoised?" flag: the flag had to
        # be updated in lockstep from several places and silently went stale, leaving
        # the noisy proxy on the GPU after a denoise run finished.
        if not self.preview.has_image or self._preview_source is not base:
            self._preview_source = base
            self.preview.set_image(base)
        return self.preview.render(self.lens, self.tone)

    def _base_image(self) -> np.ndarray:
        return self._denoised_base if self._using_denoised_base() else self._raw.rgb

    def _using_denoised_base(self) -> bool:
        return self.denoise_enabled and self._denoised_base is not None

    def _invalidate_preview_source(self) -> None:
        self._preview_source = None

    def _refresh_preview_source(self) -> None:
        """Re-seed the preview proxy — after a load, or when denoise is toggled."""
        if self._raw is None:
            self.preview.clear()
            self._preview_source = None
            return
        self._preview_source = self._base_image()
        self.preview.set_image(self._preview_source)
