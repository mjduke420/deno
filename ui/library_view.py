"""Library grid: a lazily-populated thumbnail view over the catalog.

At full library scale (~4,000 photos) neither thumbnails nor pixmaps can be loaded
eagerly, so:
  * `QListView` only asks the model for rows it is actually painting,
  * uncached thumbnails are requested from a background loader and filled in later,
  * decoded pixmaps live in a bounded LRU so scrolling can't grow memory without limit.
"""
from __future__ import annotations

from collections import OrderedDict

from PySide6.QtCore import QAbstractListModel, QModelIndex, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QListView

from core.catalog import Photo
from ui.photo_delegate import PhotoDelegate
from ui.workers import ThumbnailLoader

GRID_THUMB_SIZE = 220
CELL_PADDING = 26
PIXMAP_CACHE_LIMIT = 600  # ~220px pixmaps; bounds grid memory to roughly 80 MB

_FLAG_KEYS = {
    Qt.Key.Key_P: "pick",
    Qt.Key.Key_X: "reject",
    Qt.Key.Key_U: "none",
}
_COLOR_LABEL_KEYS = {
    Qt.Key.Key_6: "red",
    Qt.Key.Key_7: "yellow",
    Qt.Key.Key_8: "green",
    Qt.Key.Key_9: "blue",
    Qt.Key.Key_QuoteLeft: None,  # backtick clears the label
}


class PhotoGridModel(QAbstractListModel):
    PhotoRole = Qt.ItemDataRole.UserRole + 1

    def __init__(self, loader: ThumbnailLoader, thumb_size: int = GRID_THUMB_SIZE, parent=None):
        super().__init__(parent)
        self._loader = loader
        self._thumb_size = thumb_size
        self._photos: list[Photo] = []
        self._row_by_path: dict[str, int] = {}
        self._pixmaps: OrderedDict[str, QPixmap] = OrderedDict()
        self._placeholder = _placeholder_pixmap(thumb_size)
        loader.thumbnail_ready.connect(self._on_thumbnail_ready)

    # ---------- model interface ----------

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._photos)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._photos):
            return None
        photo = self._photos[index.row()]

        if role == Qt.ItemDataRole.DecorationRole:
            return self._pixmap_for(photo)
        if role == Qt.ItemDataRole.DisplayRole:
            return photo.filename
        if role == Qt.ItemDataRole.ToolTipRole:
            return _tooltip(photo)
        if role == self.PhotoRole:
            return photo
        return None

    # ---------- contents ----------

    def set_photos(self, photos: list[Photo]) -> None:
        self.beginResetModel()
        self._photos = list(photos)
        self._row_by_path = {photo.path: row for row, photo in enumerate(self._photos)}
        self.endResetModel()

    def photo_at(self, row: int) -> Photo | None:
        return self._photos[row] if 0 <= row < len(self._photos) else None

    def row_for_photo_id(self, photo_id: int) -> int | None:
        for row, photo in enumerate(self._photos):
            if photo.id == photo_id:
                return row
        return None

    def update_photo(self, photo: Photo) -> None:
        """Refresh one row in place — used after a rating/flag/label change so the
        whole grid doesn't have to be rebuilt."""
        row = self._row_by_path.get(photo.path)
        if row is None:
            return
        self._photos[row] = photo
        index = self.index(row, 0)
        self.dataChanged.emit(index, index)

    # ---------- thumbnails ----------

    def _pixmap_for(self, photo: Photo) -> QPixmap:
        cached = self._pixmaps.get(photo.path)
        if cached is not None:
            self._pixmaps.move_to_end(photo.path)
            return cached
        self._loader.request(photo.path)  # de-duplicated inside the loader
        return self._placeholder

    def _on_thumbnail_ready(self, photo_path: str, thumbnail_path: str) -> None:
        pixmap = QPixmap(thumbnail_path)
        if pixmap.isNull():
            return
        pixmap = pixmap.scaled(
            self._thumb_size,
            self._thumb_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._remember(photo_path, pixmap)

        row = self._row_by_path.get(photo_path)
        if row is not None:
            index = self.index(row, 0)
            self.dataChanged.emit(index, index, [Qt.ItemDataRole.DecorationRole])

    def _remember(self, photo_path: str, pixmap: QPixmap) -> None:
        self._pixmaps[photo_path] = pixmap
        self._pixmaps.move_to_end(photo_path)
        while len(self._pixmaps) > PIXMAP_CACHE_LIMIT:
            self._pixmaps.popitem(last=False)


class LibraryView(QListView):
    photo_activated = Signal(object)  # Photo — double-click / Enter, opens in Develop
    photo_selected = Signal(object)  # Photo — single selection change
    # Culling actions apply to every selected photo, so these carry a list.
    rating_requested = Signal(list, int)  # photos, 0..5
    flag_requested = Signal(list, str)  # photos, none|pick|reject
    color_label_requested = Signal(list, object)  # photos, colour name or None

    def __init__(self, model: PhotoGridModel, thumb_size: int = GRID_THUMB_SIZE, parent=None):
        super().__init__(parent)
        self.setModel(model)
        self._model = model
        self.setItemDelegate(PhotoDelegate(PhotoGridModel.PhotoRole, self))

        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setUniformItemSizes(True)  # lets the view skip per-item size probing
        self.setIconSize(QSize(thumb_size, thumb_size))
        self.setGridSize(QSize(thumb_size + CELL_PADDING, thumb_size + CELL_PADDING + 18))
        self.setSpacing(4)
        self.setWordWrap(False)
        self.setSelectionMode(QListView.SelectionMode.ExtendedSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.doubleClicked.connect(self._emit_activated)

    def selectionChanged(self, selected, deselected) -> None:
        super().selectionChanged(selected, deselected)
        photo = self.current_photo()
        if photo is not None:
            self.photo_selected.emit(photo)

    def current_photo(self) -> Photo | None:
        index = self.currentIndex()
        return self._model.photo_at(index.row()) if index.isValid() else None

    def selected_photos(self) -> list[Photo]:
        photos = [self._model.photo_at(index.row()) for index in self.selectedIndexes()]
        return [photo for photo in photos if photo is not None]

    def _emit_activated(self, index: QModelIndex) -> None:
        photo = self._model.photo_at(index.row())
        if photo is not None:
            self.photo_activated.emit(photo)

    def keyPressEvent(self, event) -> None:
        """Lightroom-style culling keys: 0-5 rate, P/X/U flag, 6-9 colour label."""
        photos = self.selected_photos()
        if not photos:
            super().keyPressEvent(event)
            return

        key = event.key()
        if Qt.Key.Key_0 <= key <= Qt.Key.Key_5:
            self.rating_requested.emit(photos, key - Qt.Key.Key_0)
        elif key in _FLAG_KEYS:
            self.flag_requested.emit(photos, _FLAG_KEYS[key])
        elif key in _COLOR_LABEL_KEYS:
            self.color_label_requested.emit(photos, _COLOR_LABEL_KEYS[key])
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.photo_activated.emit(photos[0])
        else:
            super().keyPressEvent(event)


def _placeholder_pixmap(size: int) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(60, 60, 60))
    return pixmap


def _tooltip(photo: Photo) -> str:
    lines = [photo.filename]
    if photo.captured_at:
        lines.append(photo.captured_at)
    if photo.camera_model:
        lines.append(photo.camera_model)
    if photo.lens_model:
        lines.append(photo.lens_model)

    exposure = []
    if photo.iso:
        exposure.append(f"ISO {photo.iso:.0f}")
    if photo.aperture:
        exposure.append(f"f/{photo.aperture:.1f}")
    if photo.focal_length_mm:
        exposure.append(f"{photo.focal_length_mm:.0f}mm")
    if exposure:
        lines.append(" · ".join(exposure))

    if photo.is_missing:
        lines.append("(file missing)")
    return "\n".join(lines)
