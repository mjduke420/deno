"""Presets: save the current adjustments under a name and apply them to other photos."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.catalog import Preset
from ui.collapsible_panel import CollapsiblePanel

_NO_PRESET = "— none —"


class PresetPanel(QWidget):
    apply_requested = Signal(int)  # preset id
    save_requested = Signal(str)  # preset name
    delete_requested = Signal(int)  # preset id

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.panel = CollapsiblePanel("Presets", self)
        body = self.panel.content_layout()

        self.preset_combo = QComboBox()
        self.preset_combo.setToolTip("Saved adjustment presets")
        self.preset_combo.activated.connect(self._on_preset_activated)
        body.addWidget(self.preset_combo)

        buttons = QWidget()
        button_layout = QHBoxLayout(buttons)
        button_layout.setContentsMargins(0, 0, 0, 0)

        self.save_button = QPushButton("Save…")
        self.save_button.setToolTip("Save the current adjustments as a preset")
        self.save_button.clicked.connect(self._on_save_clicked)

        self.delete_button = QPushButton("Delete")
        self.delete_button.setToolTip("Delete the selected preset")
        self.delete_button.clicked.connect(self._on_delete_clicked)

        button_layout.addWidget(self.save_button)
        button_layout.addWidget(self.delete_button)
        body.addWidget(buttons)

        layout.addWidget(self.panel)
        self.set_presets([])

    # ---------- state ----------

    def set_presets(self, presets: list[Preset]) -> None:
        """Repopulate the list, keeping the current selection where it still exists."""
        previous = self.current_preset_id()
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItem(_NO_PRESET, None)
        for preset in presets:
            self.preset_combo.addItem(preset.name, preset.id)

        if previous is not None:
            index = self.preset_combo.findData(previous)
            if index >= 0:
                self.preset_combo.setCurrentIndex(index)
        self.preset_combo.blockSignals(False)
        self.delete_button.setEnabled(bool(presets))

    def current_preset_id(self) -> int | None:
        return self.preset_combo.currentData()

    def select_none(self) -> None:
        """Used when a photo's own edits no longer match any applied preset."""
        self.preset_combo.blockSignals(True)
        self.preset_combo.setCurrentIndex(0)
        self.preset_combo.blockSignals(False)

    # ---------- actions ----------

    def _on_preset_activated(self, index: int) -> None:
        preset_id = self.preset_combo.itemData(index)
        if preset_id is not None:
            self.apply_requested.emit(preset_id)

    def _on_save_clicked(self) -> None:
        name, accepted = QInputDialog.getText(self, "Save preset", "Preset name:")
        if not accepted:
            return
        name = name.strip()
        if not name:
            QMessageBox.warning(self, "Name required", "Give the preset a name.")
            return
        self.save_requested.emit(name)

    def _on_delete_clicked(self) -> None:
        preset_id = self.current_preset_id()
        if preset_id is None:
            QMessageBox.information(self, "No preset selected", "Select a preset to delete.")
            return
        if (
            QMessageBox.question(self, "Delete preset?", f"Delete '{self.preset_combo.currentText()}'?")
            == QMessageBox.StandardButton.Yes
        ):
            self.delete_requested.emit(preset_id)
