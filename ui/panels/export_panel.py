"""Export panel: JPEG quality slider + export action."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget

from ui.collapsible_panel import CollapsiblePanel

_DEFAULT_QUALITY = 90


class ExportPanel(QWidget):
    export_requested = Signal(int)  # emits the chosen JPEG quality (1-100)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._quality = _DEFAULT_QUALITY

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.panel = CollapsiblePanel("Export", self)
        group_layout = self.panel.content_layout()

        quality_row = QWidget()
        quality_row_layout = QHBoxLayout(quality_row)
        quality_row_layout.setContentsMargins(0, 0, 0, 0)

        self.quality_slider = QSlider(Qt.Orientation.Horizontal)
        self.quality_slider.setRange(1, 100)
        self.quality_slider.setValue(_DEFAULT_QUALITY)

        self.quality_label = QLabel(str(_DEFAULT_QUALITY))
        self.quality_label.setFixedWidth(30)
        self.quality_slider.valueChanged.connect(self._on_quality_changed)

        quality_row_layout.addWidget(QLabel("JPEG Quality"))
        quality_row_layout.addWidget(self.quality_slider)
        quality_row_layout.addWidget(self.quality_label)
        group_layout.addWidget(quality_row)

        self.export_button = QPushButton("Export...")
        self.export_button.clicked.connect(lambda: self.export_requested.emit(self._quality))
        group_layout.addWidget(self.export_button)

        layout.addWidget(self.panel)

    def _on_quality_changed(self, value: int) -> None:
        self._quality = value
        self.quality_label.setText(str(value))
