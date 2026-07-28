"""Exposure panel: Lightroom-style Basic tone sliders (Exposure, Contrast, Highlights, Shadows, Whites, Blacks)."""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from core.tone_pipeline import MAX_TEMPERATURE, MIN_TEMPERATURE, ToneSettings
from ui.collapsible_panel import CollapsiblePanel

# (field, label, slider min, slider max, divisor from slider int -> value, section)
# Temperature is in Kelvin and rests at a non-zero default, so each spec carries its
# own neutral rather than assuming every slider returns to zero.
_SLIDER_SPECS = [
    ("temperature", "Temp", int(MIN_TEMPERATURE), int(MAX_TEMPERATURE), 1.0, "White Balance"),
    ("tint", "Tint", -150, 150, 1.0, "White Balance"),
    ("exposure", "Exposure", -500, 500, 100.0, "Tone"),
    ("contrast", "Contrast", -100, 100, 1.0, "Tone"),
    ("highlights", "Highlights", -100, 100, 1.0, "Tone"),
    ("shadows", "Shadows", -100, 100, 1.0, "Tone"),
    ("whites", "Whites", -100, 100, 1.0, "Tone"),
    ("blacks", "Blacks", -100, 100, 1.0, "Tone"),
    ("clarity", "Clarity", -100, 100, 1.0, "Presence"),
    ("dehaze", "Dehaze", -100, 100, 1.0, "Presence"),
    ("vibrance", "Vibrance", -100, 100, 1.0, "Presence"),
    ("saturation", "Saturation", -100, 100, 1.0, "Presence"),
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
        body = self.panel.content_layout()

        defaults = ToneSettings()
        current_section = None
        form: QFormLayout | None = None

        for field_name, label, lo, hi, divisor, section in _SLIDER_SPECS:
            if section != current_section:
                # White Balance / Tone / Presence, as the Basic panel is grouped.
                current_section = section
                if form is not None:
                    body.addWidget(_section_separator())
                heading = QLabel(section)
                heading.setObjectName("sectionHeading")
                body.addWidget(heading)
                form = QFormLayout()
                form.setContentsMargins(0, 0, 0, 0)
                form.setSpacing(4)
                body.addLayout(form)

            default_value = int(round(getattr(defaults, field_name) * divisor))
            slider = ResettableSlider(default_value=default_value)
            slider.setRange(lo, hi)
            slider.setValue(default_value)

            value_label = QLabel()
            value_label.setFixedWidth(44)
            value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            self._sliders[field_name] = slider
            self._value_labels[field_name] = value_label
            self._divisors[field_name] = divisor
            value_label.setText(_format_value(field_name, getattr(defaults, field_name), divisor))
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
            self._value_labels[field_name].setText(_format_value(field_name, value, divisor))

    def _make_slider_handler(self, field_name: str, divisor: float, value_label: QLabel):
        def handler(raw_value: int) -> None:
            value = raw_value / divisor
            value_label.setText(_format_value(field_name, value, divisor))
            self._settings = replace(self._settings, **{field_name: value})
            self.settings_changed.emit(self._settings)

        return handler


def _format_value(field_name: str, value: float, divisor: float) -> str:
    """Temperature reads as an absolute Kelvin figure; everything else as an offset."""
    if field_name == "temperature":
        return f"{value:.0f}"
    if divisor != 1.0:
        return f"{value:+.2f}"
    return f"{value:+.0f}"


def _section_separator() -> QFrame:
    line = QFrame()
    line.setObjectName("panelSeparator")
    line.setFrameShape(QFrame.Shape.HLine)
    return line
