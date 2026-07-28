"""Batch export panel: send the current picks out as portfolio JPEGs."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

SCOPE_SELECTED = "selected"
SCOPE_FILTERED = "filtered"
_DEFAULT_QUALITY = 95  # portfolio output defaults higher than the single-image editor


class LibraryExportPanel(QWidget):
    export_requested = Signal(str, int)  # scope, jpeg quality

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._quality = _DEFAULT_QUALITY

        layout = QVBoxLayout(self)
        group = QGroupBox("Batch Export")
        box = QVBoxLayout(group)

        self.scope_combo = QComboBox()
        self.scope_combo.addItem("Selected photos", SCOPE_SELECTED)
        self.scope_combo.addItem("All filtered photos", SCOPE_FILTERED)
        box.addWidget(self.scope_combo)

        quality_row = QWidget()
        quality_layout = QHBoxLayout(quality_row)
        quality_layout.setContentsMargins(0, 0, 0, 0)
        self.quality_slider = QSlider(Qt.Orientation.Horizontal)
        self.quality_slider.setRange(1, 100)
        self.quality_slider.setValue(_DEFAULT_QUALITY)
        self.quality_label = QLabel(str(_DEFAULT_QUALITY))
        self.quality_label.setFixedWidth(30)
        self.quality_slider.valueChanged.connect(self._on_quality_changed)
        quality_layout.addWidget(QLabel("Quality"))
        quality_layout.addWidget(self.quality_slider)
        quality_layout.addWidget(self.quality_label)
        box.addWidget(quality_row)

        self.export_button = QPushButton("Export…")
        self.export_button.clicked.connect(
            lambda: self.export_requested.emit(self.scope_combo.currentData(), self._quality)
        )
        box.addWidget(self.export_button)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        box.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        box.addWidget(self.status_label)

        layout.addWidget(group)
        layout.addStretch()

    def _on_quality_changed(self, value: int) -> None:
        self._quality = value
        self.quality_label.setText(str(value))

    def show_progress(self, done: int, total: int) -> None:
        self.export_button.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(done)
        self.status_label.setText(f"Exporting {done}/{total}…")

    def show_idle(self, message: str = "") -> None:
        self.export_button.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.status_label.setText(message)
