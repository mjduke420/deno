"""RGB histogram with clipping indicators, as sits above the Basic panel in Lightroom.

Computed from the rendered preview rather than the RAW data, so it reflects what the
photo currently looks like with every adjustment applied — which is what you need when
deciding whether an exposure change has pushed anything to pure black or white.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

BINS = 256
_CLIP_CEILING = 254  # channel value at or above which a pixel counts as blown
_CLIP_FLOOR = 1  # ...and at or below which it counts as crushed
_CLIP_VISIBLE_FRACTION = 0.001  # a tenth of a percent of pixels is worth flagging

_CHANNEL_COLORS = (QColor(230, 80, 80), QColor(90, 210, 110), QColor(90, 150, 240))
_BACKGROUND = QColor(24, 24, 24)
_BORDER = QColor(70, 70, 70)
_GRID = QColor(48, 48, 48)
_CLIP_ON = QColor(245, 245, 245)
_CLIP_OFF = QColor(70, 70, 70)


def compute_histogram(srgb8: np.ndarray) -> np.ndarray:
    """Per-channel counts over 256 bins. Input is display-ready 8-bit sRGB."""
    if srgb8.ndim != 3 or srgb8.shape[2] < 3:
        raise ValueError("expected an HxWx3 8-bit image")
    return np.stack(
        [np.bincount(srgb8[..., channel].ravel(), minlength=BINS)[:BINS] for channel in range(3)]
    )


def clipping_fractions(srgb8: np.ndarray) -> tuple[float, float]:
    """Fraction of pixels crushed to black and blown to white, in any channel."""
    if srgb8.size == 0:
        return (0.0, 0.0)
    pixels = srgb8.shape[0] * srgb8.shape[1]
    shadows = float(np.any(srgb8[..., :3] <= _CLIP_FLOOR, axis=-1).sum()) / pixels
    highlights = float(np.any(srgb8[..., :3] >= _CLIP_CEILING, axis=-1).sum()) / pixels
    return (shadows, highlights)


class HistogramWidget(QWidget):
    """Draws the three channel curves plus the two clipping warning lamps."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._histogram: np.ndarray | None = None
        self._shadow_clip = 0.0
        self._highlight_clip = 0.0
        self.setMinimumHeight(110)
        self.setToolTip(
            "Tone distribution of the current render.\n"
            "Corner lamps light when shadows or highlights are clipping."
        )

    def set_image(self, srgb8: np.ndarray | None) -> None:
        if srgb8 is None or srgb8.size == 0:
            self._histogram = None
            self._shadow_clip = self._highlight_clip = 0.0
        else:
            self._histogram = compute_histogram(srgb8)
            self._shadow_clip, self._highlight_clip = clipping_fractions(srgb8)
        self.update()

    @property
    def shadows_clipped(self) -> bool:
        return self._shadow_clip > _CLIP_VISIBLE_FRACTION

    @property
    def highlights_clipped(self) -> bool:
        return self._highlight_clip > _CLIP_VISIBLE_FRACTION

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        area = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.fillRect(area, _BACKGROUND)

        self._draw_grid(painter, area)
        if self._histogram is not None:
            self._draw_curves(painter, area)
        self._draw_clipping_lamps(painter, area)

        painter.setPen(QPen(_BORDER, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(area)

    def _draw_grid(self, painter: QPainter, area: QRectF) -> None:
        painter.setPen(QPen(_GRID, 1))
        for step in range(1, 4):  # quarter-tone guides
            x = area.left() + area.width() * step / 4
            painter.drawLine(int(x), int(area.top()), int(x), int(area.bottom()))

    def _draw_curves(self, painter: QPainter, area: QRectF) -> None:
        # Square-root scaling: a linear axis is dominated by whichever tone happens to
        # be most common and flattens the shape everywhere else.
        scaled = np.sqrt(self._histogram.astype(np.float64))
        peak = scaled.max()
        if peak <= 0:
            return
        scaled = scaled / peak

        painter.setPen(Qt.PenStyle.NoPen)
        for channel, color in enumerate(_CHANNEL_COLORS):
            path = QPainterPath()
            path.moveTo(area.left(), area.bottom())
            for index in range(BINS):
                x = area.left() + area.width() * index / (BINS - 1)
                y = area.bottom() - area.height() * scaled[channel, index]
                path.lineTo(x, y)
            path.lineTo(area.right(), area.bottom())
            path.closeSubpath()

            fill = QColor(color)
            fill.setAlpha(110)  # overlapping channels blend, so neutrals read as grey
            painter.fillPath(path, fill)

    def _draw_clipping_lamps(self, painter: QPainter, area: QRectF) -> None:
        size = 9.0
        inset = 4.0
        painter.setPen(QPen(_BORDER, 1))

        painter.setBrush(_CLIP_ON if self.shadows_clipped else _CLIP_OFF)
        painter.drawRect(QRectF(area.left() + inset, area.top() + inset, size, size))

        painter.setBrush(_CLIP_ON if self.highlights_clipped else _CLIP_OFF)
        painter.drawRect(QRectF(area.right() - inset - size, area.top() + inset, size, size))
