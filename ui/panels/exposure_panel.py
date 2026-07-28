"""Exposure panel: Lightroom-style Basic tone sliders (Exposure, Contrast, Highlights, Shadows, Whites, Blacks)."""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFormLayout, QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget

from core.tone_pipeline import ToneSettings
from ui.collapsible_panel import CollapsiblePanel

# (field name, display label, slider min, slider max, divisor to convert slider int -> float value)
_SLIDER_SPECS = [
    ("exposure", "Exposure", -500, 500, 100.0),
    ("contrast", "Contrast", -100, 100, 1.0),
    ("highlights", "Highlights", -100, 100, 1.0),
    ("shadows", "Shadows", -100, 100, 1.0),
    ("whites", "Whites", -100, 100, 1.0),
    ("blacks", "Blacks", -100, 100, 1.0),
    ("clarity", "Clarity", -100, 100, 1.0),
    ("vibrance", "Vibrance", -100, 100, 1.0),
    ("dehaze", "Dehaze", -100, 100, 1.0),
]


class ResettableSlider(QSlider):
    """A slider that snaps back to its default when double-clicked, as in Lightroom."""

    def __init__(self, default_value: int = 0, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._default_value = default_value
        self.setToolTip("Double-click to reset")

    def mouseDoubleClickEvent(self, event) -> None:
        self.setValue(self._default_value)
        event.accept()


class ExposurePanel(QWidget):
    settings_changed = Signal(object)  # emits a ToneSettings

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._settings = ToneSettings()
        self._sliders: dict[str, QSlider] = {}
        self._value_labels: dict[str, QLabel] = {}
        self._divisors: dict[str, float] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.panel = CollapsiblePanel("Basic", self)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(4)
        self.panel.content_layout().addLayout(form)

        for field_name, label, lo, hi, divisor in _SLIDER_SPECS:
            slider = ResettableSlider()
            slider.setRange(lo, hi)
            slider.setValue(0)

            value_label = QLabel("0")
            value_label.setFixedWidth(40)
            value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            self._sliders[field_name] = slider
            self._value_labels[field_name] = value_label
            self._divisors[field_name] = divisor
            slider.valueChanged.connect(self._make_slider_handler(field_name, divisor, value_label))

            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(slider)
            row_layout.addWidget(value_label)
            form.addRow(label, row)

        layout.addWidget(self.panel)

    def settings(self) -> ToneSettings:
        return self._settings

    def set_settings(self, settings: ToneSettings) -> None:
        """Push a photo's stored edits into the sliders.

        Signals are blocked while writing so restoring a photo can't echo back as a
        user edit and overwrite the very settings being loaded.
        """
        self._settings = settings
        for field_name, slider in self._sliders.items():
            value = getattr(settings, field_name)
            divisor = self._divisors[field_name]
            slider.blockSignals(True)
            slider.setValue(round(value * divisor))
            slider.blockSignals(False)
            self._value_labels[field_name].setText(
                f"{value:+.2f}" if divisor != 1.0 else f"{value:+.0f}"
            )

    def _make_slider_handler(self, field_name: str, divisor: float, value_label: QLabel):
        def handler(raw_value: int) -> None:
            value = raw_value / divisor
            value_label.setText(f"{value:+.2f}" if divisor != 1.0 else f"{value:+.0f}")
            self._settings = replace(self._settings, **{field_name: value})
            self.settings_changed.emit(self._settings)

        return handler
