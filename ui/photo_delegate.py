"""Grid cell painting: thumbnail plus its rating, flag and colour-label badges.

Culling is a visual, at-a-glance activity, so the badges are drawn directly onto the
cell rather than hidden behind a selection or an inspector panel.
"""
from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

from core.catalog import Photo

LABEL_COLORS = {
    "red": QColor(220, 70, 70),
    "yellow": QColor(220, 190, 60),
    "green": QColor(90, 190, 90),
    "blue": QColor(80, 140, 230),
    "purple": QColor(160, 100, 210),
}

_STAR_FILLED = "★"
_STAR_EMPTY = "☆"
_FLAG_PICK = "⚑"
_FLAG_REJECT = "✗"

_BADGE_HEIGHT = 18
_SWATCH_SIZE = 12
_MARGIN = 4


class PhotoDelegate(QStyledItemDelegate):
    def __init__(self, photo_role: int, parent=None):
        super().__init__(parent)
        self._photo_role = photo_role

    def paint(self, painter: QPainter, option, index) -> None:
        photo = index.data(self._photo_role)
        pixmap = index.data(Qt.ItemDataRole.DecorationRole)
        if photo is None or not isinstance(pixmap, QPixmap):
            super().paint(painter, option, index)
            return

        painter.save()
        rect = option.rect

        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(rect, option.palette.highlight())
        else:
            painter.fillRect(rect, QColor(38, 38, 38))

        image_area = QRect(
            rect.left() + _MARGIN,
            rect.top() + _MARGIN,
            rect.width() - 2 * _MARGIN,
            rect.height() - 2 * _MARGIN - _BADGE_HEIGHT,
        )
        self._draw_thumbnail(painter, image_area, pixmap, photo)
        self._draw_badges(painter, rect, image_area, photo)

        painter.restore()

    def _draw_thumbnail(self, painter: QPainter, area: QRect, pixmap: QPixmap, photo: Photo) -> None:
        scaled = pixmap.scaled(
            area.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
        target = QRect(0, 0, scaled.width(), scaled.height())
        target.moveCenter(area.center())

        if photo.is_missing:
            painter.setOpacity(0.35)  # greyed out rather than crashing the grid
        painter.drawPixmap(target, scaled)
        painter.setOpacity(1.0)

        if photo.is_missing:
            painter.setPen(QColor(230, 120, 120))
            painter.drawText(area, Qt.AlignmentFlag.AlignCenter, "missing")

    def _draw_badges(self, painter: QPainter, cell: QRect, image_area: QRect, photo: Photo) -> None:
        badge_row = QRect(cell.left() + _MARGIN, image_area.bottom() + 2, cell.width() - 2 * _MARGIN, _BADGE_HEIGHT)

        font = QFont(painter.font())
        font.setPointSize(9)
        painter.setFont(font)

        stars = _STAR_FILLED * photo.rating + _STAR_EMPTY * (5 - photo.rating)
        painter.setPen(QColor(235, 200, 90) if photo.rating else QColor(120, 120, 120))
        painter.drawText(badge_row, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, stars)

        if photo.flag == "pick":
            painter.setPen(QColor(120, 220, 120))
            painter.drawText(badge_row, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, _FLAG_PICK)
        elif photo.flag == "reject":
            painter.setPen(QColor(230, 110, 110))
            painter.drawText(badge_row, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, _FLAG_REJECT)

        color = LABEL_COLORS.get(photo.color_label or "")
        if color is not None:
            swatch = QRect(image_area.right() - _SWATCH_SIZE - 2, image_area.top() + 2, _SWATCH_SIZE, _SWATCH_SIZE)
            painter.fillRect(swatch, color)
            painter.setPen(QColor(20, 20, 20))
            painter.drawRect(swatch)
