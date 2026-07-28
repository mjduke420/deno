"""Lens Correction panel: manual Distortion/Vignetting amount sliders + CA removal checkbox."""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from core.lens_correction import LensSettings

# (field name, display label, slider min, slider max)
_SLIDER_SPECS = [
    ("distortion", "Distortion", -100, 100),
    ("vignetting", "Vignetting", -100, 100),
]


class LensPanel(QWidget):
    settings_changed = Signal(object)  # emits a LensSettings

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._settings = LensSettings()
        self._sliders: dict[str, QSlider] = {}
        self._value_labels: dict[str, QLabel] = {}

        layout = QVBoxLayout(self)
        group = QGroupBox("Lens Corrections")
        form = QFormLayout(group)

        for field_name, label, lo, hi in _SLIDER_SPECS:
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(lo, hi)
            slider.setValue(0)

            value_label = QLabel("0")
            value_label.setFixedWidth(40)
            value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            self._sliders[field_name] = slider
            self._value_labels[field_name] = value_label
            slider.valueChanged.connect(self._make_slider_handler(field_name, value_label))

            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(slider)
            row_layout.addWidget(value_label)
            form.addRow(label, row)

        self._ca_checkbox = QCheckBox("Remove Chromatic Aberration")
        self._ca_checkbox.toggled.connect(self._on_ca_toggled)
        form.addRow(self._ca_checkbox)

        layout.addWidget(group)
        layout.addStretch()

    def settings(self) -> LensSettings:
        return self._settings

    def set_settings(self, settings: LensSettings) -> None:
        """Push a photo's stored lens corrections into the controls, with signals
        blocked so loading can't be mistaken for a user edit."""
        self._settings = settings
        for field_name, slider in self._sliders.items():
            value = getattr(settings, field_name)
            slider.blockSignals(True)
            slider.setValue(round(value))
            slider.blockSignals(False)
            self._value_labels[field_name].setText(f"{round(value):+d}")

        self._ca_checkbox.blockSignals(True)
        self._ca_checkbox.setChecked(settings.remove_chromatic_aberration)
        self._ca_checkbox.blockSignals(False)

    def _make_slider_handler(self, field_name: str, value_label: QLabel):
        def handler(value: int) -> None:
            value_label.setText(f"{value:+d}")
            self._settings = replace(self._settings, **{field_name: float(value)})
            self.settings_changed.emit(self._settings)

        return handler

    def _on_ca_toggled(self, checked: bool) -> None:
        self._settings = replace(self._settings, remove_chromatic_aberration=checked)
        self.settings_changed.emit(self._settings)
