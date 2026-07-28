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
from core.raw_loader import RawImage, load_raw
from core.tone_pipeline import ToneSettings, apply_tone


class Denoiser(Protocol):
    def denoise(self, rgb_uint8: np.ndarray, progress_cb: object = None) -> np.ndarray: ...


class Pipeline:
    def __init__(self) -> None:
        self._raw: RawImage | None = None
        self._denoised_base: np.ndarray | None = None  # linear RGB, cached until reload/re-denoise
        self.lens = LensSettings()
        self.tone = ToneSettings()
        self.denoise_enabled = False

    def load(self, path: str) -> RawImage:
        self._raw = load_raw(path)
        self._denoised_base = None
        self.denoise_enabled = False
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
        base_srgb8 = linear_to_srgb8(raw_at_start.rgb)
        denoised_srgb8 = denoiser.denoise(base_srgb8, progress_cb=progress_cb)
        if self._raw is raw_at_start:
            self._denoised_base = srgb8_to_linear(denoised_srgb8)

    def render(self) -> np.ndarray:
        if self._raw is None:
            raise ValueError("No RAW file loaded")
        base = self._denoised_base if (self.denoise_enabled and self._denoised_base is not None) else self._raw.rgb
        img = apply_lens_correction(base, self.lens)
        return apply_tone(img, self.tone)
