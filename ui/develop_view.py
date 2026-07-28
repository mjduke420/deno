"""Develop module: the single-photo editor (denoise, exposure, lens, export).

Owns its own `Pipeline` and adjustment panels so the Library module doesn't have to
know anything about rendering.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QFileDialog,
    QMessageBox,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from core.denoise import NafnetDenoiser
from core.display import to_qimage
from core.edit_state import EditState
from core.exporter import export_jpeg
from core.lens_correction import LensSettings
from core.pipeline import Pipeline
from core.raw_loader import RawImage
from core.tone_pipeline import ToneSettings
from ui.image_view import ImageView
from ui.panels.denoise_panel import DenoisePanel
from ui.panels.export_panel import ExportPanel
from ui.panels.exposure_panel import ExposurePanel
from ui.panels.lens_panel import LensPanel
from ui.workers import DenoiseWorker

JPEG_FILE_FILTER = "JPEG (*.jpg *.jpeg)"
_PANEL_WIDTH = 300


def format_shooting_info(path: str, raw_image: RawImage) -> str:
    # Any of these EXIF fields can be missing (manual/adapted lenses, bodies that
    # don't report a field), so each is formatted defensively.
    iso = f"ISO {raw_image.iso:.0f}" if raw_image.iso is not None else "ISO —"
    focal = f"{raw_image.focal_length_mm:.0f}mm" if raw_image.focal_length_mm is not None else "—mm"
    aperture = f"f/{raw_image.aperture:.1f}" if raw_image.aperture is not None else "f/—"
    lens = raw_image.lens_model or "Unknown lens"
    return f"{Path(path).name} — {iso}, {lens}, {focal}, {aperture}"


class DevelopView(QWidget):
    edits_changed = Signal()  # any adjustment changed; the window persists them
    status_message = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        self.pipeline = Pipeline()
        self._denoiser: NafnetDenoiser | None = None
        self._denoise_worker: DenoiseWorker | None = None
        self._original_qimage: QImage | None = None
        self._current_qimage: QImage | None = None
        self._current_path: str | None = None
        self.showing_before = False

        self.image_view = ImageView(self)
        self.exposure_panel = ExposurePanel(self)
        self.lens_panel = LensPanel(self)
        self.denoise_panel = DenoisePanel(self)
        self.export_panel = ExportPanel(self)

        self.exposure_panel.settings_changed.connect(self._on_tone_settings_changed)
        self.lens_panel.settings_changed.connect(self._on_lens_settings_changed)
        self.denoise_panel.enabled_toggled.connect(self._on_denoise_toggled)
        self.export_panel.export_requested.connect(self._on_export_requested)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.addWidget(self.image_view)
        splitter.addWidget(self._build_panel_column())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

    def _build_panel_column(self) -> QScrollArea:
        column = QWidget()
        column_layout = QVBoxLayout(column)
        column_layout.addWidget(self.denoise_panel)
        column_layout.addWidget(self.exposure_panel)
        column_layout.addWidget(self.lens_panel)
        column_layout.addWidget(self.export_panel)
        column_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidget(column)
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(_PANEL_WIDTH)
        scroll.setMaximumWidth(_PANEL_WIDTH + 80)
        return scroll

    # ---------- loading ----------

    @property
    def current_path(self) -> str | None:
        return self._current_path

    def has_photo(self) -> bool:
        return self.pipeline.raw is not None

    def load_photo(self, path: str, edits: EditState | None = None) -> bool:
        """Decode a photo and restore its saved adjustments. Returns False on failure."""
        try:
            raw_image = self.pipeline.load(path)
        except Exception as exc:  # rawpy raises various LibRaw-specific errors
            QMessageBox.critical(self, "Failed to open photo", f"{Path(path).name}\n\n{exc}")
            return False

        self._current_path = path
        self.pipeline.apply_edit_state(edits or EditState())
        self._push_edits_into_panels(self.pipeline.edit_state())

        self.showing_before = False
        # Built at preview resolution too, so opening a photo doesn't pay for a
        # full-resolution gamma pass just to have a "before" to toggle to.
        self._original_qimage = to_qimage(
            self.pipeline.preview.render(LensSettings(), ToneSettings())
        )
        self._refresh_view()
        self.status_message.emit(format_shooting_info(path, raw_image))
        return True

    def edit_state(self) -> EditState:
        return self.pipeline.edit_state()

    def _push_edits_into_panels(self, state: EditState) -> None:
        self.exposure_panel.set_settings(state.tone)
        self.lens_panel.set_settings(state.lens)
        # Denoise has to be re-run per photo, so the checkbox always starts clear.
        self.denoise_panel.set_checkbox_checked_silently(False)
        self.denoise_panel.show_idle()

    # ---------- adjustments ----------

    def _on_tone_settings_changed(self, settings: ToneSettings) -> None:
        self.pipeline.tone = settings
        self._refresh_view()
        self.edits_changed.emit()

    def _on_lens_settings_changed(self, settings: LensSettings) -> None:
        self.pipeline.lens = settings
        self._refresh_view()
        self.edits_changed.emit()

    def set_showing_before(self, showing_before: bool) -> None:
        self.showing_before = showing_before
        self._apply_view_mode()

    # ---------- denoise ----------

    def is_denoising(self) -> bool:
        return self._denoise_worker is not None and self._denoise_worker.isRunning()

    def _on_denoise_toggled(self, checked: bool) -> None:
        if not checked:
            self.pipeline.denoise_enabled = False
            self._refresh_view()
            self.edits_changed.emit()
            return

        if self.pipeline.has_denoised_base:
            self.pipeline.denoise_enabled = True
            self._refresh_view()
            self.edits_changed.emit()
            return

        self._start_denoise_worker()

    def _start_denoise_worker(self) -> None:
        self.denoise_panel.set_checkbox_enabled(False)
        self.denoise_panel.show_progress(0, 1)

        self._denoise_worker = DenoiseWorker(self.pipeline, self._get_or_create_denoiser, self)
        self._denoise_worker.progress.connect(self.denoise_panel.show_progress)
        self._denoise_worker.finished_ok.connect(self._on_denoise_finished)
        self._denoise_worker.failed.connect(self._on_denoise_failed)
        self._denoise_worker.start()

    def _get_or_create_denoiser(self) -> NafnetDenoiser:
        if self._denoiser is None:
            self._denoiser = NafnetDenoiser()
        return self._denoiser

    def _on_denoise_finished(self) -> None:
        self.denoise_panel.set_checkbox_enabled(True)
        self.denoise_panel.show_idle("Denoise complete.")
        # run_denoise discards its result if a different photo was loaded mid-run.
        self.pipeline.denoise_enabled = self.pipeline.has_denoised_base
        if not self.pipeline.has_denoised_base:
            self.denoise_panel.set_checkbox_checked_silently(False)
        self._refresh_view()
        self.edits_changed.emit()

    def _on_denoise_failed(self, message: str) -> None:
        self.denoise_panel.set_checkbox_enabled(True)
        self.denoise_panel.set_checkbox_checked_silently(False)
        self.denoise_panel.show_idle("")
        # Drop the cached model so a retry starts from a clean CUDA context.
        self._denoiser = None
        QMessageBox.critical(self, "AI Denoise failed", message)

    # ---------- export ----------

    def _on_export_requested(self, quality: int) -> None:
        if self.pipeline.raw is None:
            QMessageBox.warning(self, "Nothing to export", "Open a photo first.")
            return

        suggested = str(Path(self._current_path).with_suffix(".jpg")) if self._current_path else ""
        path, _ = QFileDialog.getSaveFileName(self, "Export JPEG", suggested, JPEG_FILE_FILTER)
        if not path:
            return
        if not path.lower().endswith((".jpg", ".jpeg")):
            path += ".jpg"

        try:
            export_jpeg(self.pipeline.render(), path, quality)
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return

        self.status_message.emit(f"Exported to {path} (quality {quality})")

    # ---------- rendering ----------

    def _refresh_view(self) -> None:
        if self.pipeline.raw is None:
            return
        # Preview resolution only — a full-resolution render costs seconds per slider
        # tick. Export still goes through the full-resolution path.
        self._current_qimage = to_qimage(self.pipeline.render_preview())
        self._apply_view_mode()

    def _apply_view_mode(self) -> None:
        qimage = self._original_qimage if self.showing_before else self._current_qimage
        if qimage is not None:
            self.image_view.set_image(qimage)
