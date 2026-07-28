"""A panel whose title bar is part of the panel, and which collapses when clicked.

Qt's QGroupBox floats its title on the frame's top border, which reads as a stray
label sitting above the box rather than a heading belonging to it. This draws the
title as a header row inside the same frame, the way editing applications present
their adjustment sections — and makes it clickable to collapse the contents, so a
long panel column can be reduced to the sections you are actually using.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

_ARROW_EXPANDED = "▾"
_ARROW_COLLAPSED = "▸"


class PanelHeader(QWidget):
    """Clickable title row. A separate widget so the stylesheet can target it."""

    clicked = Signal()

    def __init__(self, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("panelHeader")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(6)

        self.arrow_label = QLabel(_ARROW_EXPANDED)
        self.arrow_label.setObjectName("panelArrow")
        self.title_label = QLabel(title)
        self.title_label.setObjectName("panelTitle")

        layout.addWidget(self.arrow_label)
        layout.addWidget(self.title_label)
        layout.addStretch()

    def set_expanded(self, expanded: bool) -> None:
        self.arrow_label.setText(_ARROW_EXPANDED if expanded else _ARROW_COLLAPSED)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class CollapsiblePanel(QFrame):
    toggled = Signal(bool)

    def __init__(self, title: str, parent: QWidget | None = None, expanded: bool = True):
        super().__init__(parent)
        self.setObjectName("collapsiblePanel")
        self.setFrameShape(QFrame.Shape.NoFrame)

        self._title = title
        self._expanded = expanded

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.header = PanelHeader(title, self)
        self.header.clicked.connect(self.toggle)
        outer.addWidget(self.header)

        self._content = QWidget(self)
        self._content.setObjectName("panelContent")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(8, 8, 8, 8)
        self._content_layout.setSpacing(4)
        outer.addWidget(self._content)

        self.set_expanded(expanded)

    @property
    def title(self) -> str:
        return self._title

    def content_layout(self) -> QVBoxLayout:
        """Layout that callers add their controls to."""
        return self._content_layout

    def add_widget(self, widget: QWidget) -> None:
        self._content_layout.addWidget(widget)

    def is_expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self._content.setVisible(expanded)
        self.header.set_expanded(expanded)

    def toggle(self) -> None:
        self.set_expanded(not self._expanded)
        self.toggled.emit(self._expanded)
