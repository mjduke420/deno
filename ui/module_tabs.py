"""Module switcher across the top right: Library / Develop.

Photo applications separate browsing from editing, and the switch between them is
frequent enough to deserve a permanent control rather than a menu item.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget


class ModuleTabs(QWidget):
    module_selected = Signal(int)  # index of the chosen module

    def __init__(self, names: list[str], parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("moduleTabs")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 6, 0)
        layout.setSpacing(2)
        layout.addStretch()

        self._buttons: list[QPushButton] = []
        for index, name in enumerate(names):
            button = QPushButton(name)
            button.setObjectName("moduleTab")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFlat(True)
            button.clicked.connect(lambda _checked, i=index: self._on_clicked(i))
            layout.addWidget(button)
            self._buttons.append(button)

        if self._buttons:
            self.set_current(0)

    def set_current(self, index: int) -> None:
        """Reflect the active module without re-emitting — the window drives this."""
        for position, button in enumerate(self._buttons):
            button.setChecked(position == index)

    def _on_clicked(self, index: int) -> None:
        self.set_current(index)
        self.module_selected.emit(index)
