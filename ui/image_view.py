"""Pannable, zoomable canvas for displaying a decoded image."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsScene, QGraphicsView


class ImageView(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pixmap_item = QGraphicsPixmapItem()
        self._scene.addItem(self._pixmap_item)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._has_image = False
        # While the photo is simply "fitted" it should keep filling the window as the
        # window changes size. Once the user zooms, their zoom is theirs to keep.
        self._user_zoomed = False

    def set_image(self, qimage: QImage) -> None:
        pixmap = QPixmap.fromImage(qimage)
        first_image = not self._has_image
        self._pixmap_item.setPixmap(pixmap)
        self._scene.setSceneRect(pixmap.rect())
        if first_image or not self._user_zoomed:
            self.fit_to_window()
            self._has_image = True

    def fit_to_window(self) -> None:
        if not self._pixmap_item.pixmap().isNull():
            self.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)
            self._user_zoomed = False

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._has_image and not self._user_zoomed:
            self.fit_to_window()

    def wheelEvent(self, event) -> None:
        zoom_factor = 1.25 if event.angleDelta().y() > 0 else 0.8
        self.scale(zoom_factor, zoom_factor)
        self._user_zoomed = True

    def mouseDoubleClickEvent(self, event) -> None:
        """Double-click returns a zoomed photo to fitting the window."""
        self.fit_to_window()
        event.accept()
