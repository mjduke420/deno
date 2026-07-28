"""AI Denoise panel: enable toggle + progress feedback for the GPU model run."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QGroupBox, QLabel, QProgressBar, QVBoxLayout, QWidget


class DenoisePanel(QWidget):
    enabled_toggled = Signal(bool)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        group = QGroupBox("AI Denoise")
        group_layout = QVBoxLayout(group)

        self.checkbox = QCheckBox("Enable AI Denoise (GPU)")
        self.checkbox.toggled.connect(self.enabled_toggled)
        group_layout.addWidget(self.checkbox)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        group_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        group_layout.addWidget(self.status_label)

        layout.addWidget(group)
        layout.addStretch()

    def set_checkbox_checked_silently(self, checked: bool) -> None:
        self.checkbox.blockSignals(True)
        self.checkbox.setChecked(checked)
        self.checkbox.blockSignals(False)

    def set_checkbox_enabled(self, enabled: bool) -> None:
        self.checkbox.setEnabled(enabled)

    def show_progress(self, done: int, total: int) -> None:
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(done)
        self.status_label.setText(f"Denoising tile {done}/{total}...")

    def show_idle(self, message: str = "") -> None:
        self.progress_bar.setVisible(False)
        self.status_label.setText(message)
