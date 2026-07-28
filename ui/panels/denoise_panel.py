"""AI Denoise panel: enable toggle, strength, and progress feedback for the GPU run."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from core.edit_state import DEFAULT_DENOISE_AMOUNT
from ui.collapsible_panel import CollapsiblePanel
from ui.panels.exposure_panel import ResettableSlider

# Full strength scrubs fine detail along with the noise, so the slider defaults to a
# partial application and steps in the usual quarters.
DEFAULT_AMOUNT_PERCENT = int(round(DEFAULT_DENOISE_AMOUNT * 100))
_STEP_PERCENT = 25


class DenoisePanel(QWidget):
    enabled_toggled = Signal(bool)
    amount_changed = Signal(float)  # 0.0 .. 1.0

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.panel = CollapsiblePanel("AI Denoise", self)
        group_layout = self.panel.content_layout()

        self.checkbox = QCheckBox("Enable AI Denoise (GPU)")
        self.checkbox.toggled.connect(self.enabled_toggled)
        self.checkbox.toggled.connect(self._update_amount_enabled)
        group_layout.addWidget(self.checkbox)

        amount_row = QWidget()
        amount_layout = QHBoxLayout(amount_row)
        amount_layout.setContentsMargins(0, 0, 0, 0)

        self.amount_slider = ResettableSlider(default_value=DEFAULT_AMOUNT_PERCENT)
        self.amount_slider.setRange(0, 100)
        self.amount_slider.setValue(DEFAULT_AMOUNT_PERCENT)
        self.amount_slider.setTickInterval(_STEP_PERCENT)
        self.amount_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.amount_slider.setSingleStep(_STEP_PERCENT)
        self.amount_slider.setPageStep(_STEP_PERCENT)
        self.amount_slider.setToolTip(
            "How much of the denoise result to blend in.\n"
            "Lower values keep more fine detail. Double-click to reset."
        )
        self.amount_slider.valueChanged.connect(self._on_amount_changed)

        self.amount_label = QLabel(f"{DEFAULT_AMOUNT_PERCENT}%")
        self.amount_label.setFixedWidth(40)
        self.amount_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        amount_layout.addWidget(QLabel("Amount"))
        amount_layout.addWidget(self.amount_slider)
        amount_layout.addWidget(self.amount_label)
        group_layout.addWidget(amount_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        group_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        group_layout.addWidget(self.status_label)

        layout.addWidget(self.panel)
        self._update_amount_enabled(self.checkbox.isChecked())

    # ---------- amount ----------

    def amount(self) -> float:
        return self.amount_slider.value() / 100.0

    def set_amount_silently(self, amount: float) -> None:
        """Load a photo's stored strength without it echoing back as a user edit."""
        self.amount_slider.blockSignals(True)
        self.amount_slider.setValue(int(round(min(1.0, max(0.0, amount)) * 100)))
        self.amount_slider.blockSignals(False)
        self.amount_label.setText(f"{self.amount_slider.value()}%")

    def _on_amount_changed(self, percent: int) -> None:
        self.amount_label.setText(f"{percent}%")
        self.amount_changed.emit(percent / 100.0)

    def _update_amount_enabled(self, denoise_on: bool) -> None:
        # Strength is meaningless until there is a denoise result to blend.
        self.amount_slider.setEnabled(denoise_on)
        self.amount_label.setEnabled(denoise_on)

    # ---------- toggle / progress ----------

    def set_checkbox_checked_silently(self, checked: bool) -> None:
        self.checkbox.blockSignals(True)
        self.checkbox.setChecked(checked)
        self.checkbox.blockSignals(False)
        self._update_amount_enabled(checked)

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
