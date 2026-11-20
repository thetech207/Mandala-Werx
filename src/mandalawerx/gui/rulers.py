"""Pixel rulers along the canvas; drag from one to pull out a guide."""

from __future__ import annotations

import math

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QPainter, QColor, QPen, QFont
from PySide6.QtWidgets import QWidget

RULER_PX = 22
NICE = (1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000)


def tick_step(zoom: float, min_px: float = 60) -> int:
    for s in NICE:
        if s * zoom >= min_px:
            return s
    return NICE[-1]


class Ruler(QWidget):
    """Horizontal ruler (top) measures x; vertical ruler (left) measures
    y. Values are document units (= pixels at 1:1 export), 0 at the
    canvas' top-left corner; the mandala center is marked."""

    def __init__(self, canvas, horizontal: bool, parent=None):
        super().__init__(parent)
        self.canvas = canvas
        self.horizontal = horizontal
        if horizontal:
            self.setFixedHeight(RULER_PX)
        else:
            self.setFixedWidth(RULER_PX)
        self.setCursor(Qt.CursorShape.SplitVCursor if horizontal
                       else Qt.CursorShape.SplitHCursor)
        self.setToolTip("Drag into the canvas to add a guide (snaps to "
                        "the center mark; hold Alt for no snapping)")
        self._dragging = False

    # canvas widget coords <-> this ruler's coords along its axis
    def _offset(self) -> int:
        o = self.canvas.mapTo(self.window(), self.canvas.rect().topLeft())
        m = self.mapTo(self.window(), self.rect().topLeft())
        return (o.x() - m.x()) if self.horizontal else (o.y() - m.y())

    def paintEvent(self, _ev):
        cv = self.canvas
        p = QPainter(self)
        pal = self.palette()
        bg = pal.color(pal.ColorRole.Window)
        fg = pal.color(pal.ColorRole.WindowText)
        p.fillRect(self.rect(), bg.darker(104))
        z = cv.zoom
        off = self._offset()
        origin = (cv.pan.x() if self.horizontal else cv.pan.y()) + off
        length = self.width() if self.horizontal else self.height()
        S = cv.S()
        # canvas extent highlighted
        a, b = origin, origin + S * z
        hl = pal.color(pal.ColorRole.Highlight)
        hl.setAlpha(40)
        if self.horizontal:
            p.fillRect(QRectF(a, 0, b - a, RULER_PX), hl)
        else:
            p.fillRect(QRectF(0, a, RULER_PX, b - a), hl)
        step = tick_step(z)
        minor = step / (5 if step % 5 == 0 else 2 if step % 2 == 0 else 1)
        f = QFont(self.font())
        f.setPointSizeF(max(6.5, f.pointSizeF() * 0.75))
        p.setFont(f)
        tick = QColor(fg)
        tick.setAlpha(150)
        p.setPen(QPen(tick, 1))
        first = math.floor(-origin / z / minor) * minor
        v = first
        while (v * z + origin) <= length:
            sp = math.floor(v * z + origin) + 0.5
            major = abs(v / step - round(v / step)) < 1e-6
            tl = RULER_PX * (0.55 if major else 0.25)
            if self.horizontal:
                p.drawLine(QPointF(sp, RULER_PX - tl), QPointF(sp, RULER_PX))
                if major:
                    p.drawText(QPointF(sp + 2, 9), f"{int(round(v))}")
            else:
                p.drawLine(QPointF(RULER_PX - tl, sp), QPointF(RULER_PX, sp))
                if major:
                    p.save()
                    p.translate(9, sp + 2)
                    p.rotate(-90)
                    p.drawText(QPointF(-p.fontMetrics().horizontalAdvance(
                        f"{int(round(v))}") - 2, 0), f"{int(round(v))}")
                    p.restore()
            v += minor
        # mandala center mark
        mark = QColor(230, 120, 30)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(mark)
        c = math.floor((S / 2) * z + origin) + 0.5
        if -6 <= c <= length + 6:
            if self.horizontal:
                p.drawPolygon([QPointF(c - 5, RULER_PX - 7),
                               QPointF(c + 5, RULER_PX - 7),
                               QPointF(c, RULER_PX - 1)])
            else:
                p.drawPolygon([QPointF(RULER_PX - 7, c - 5),
                               QPointF(RULER_PX - 7, c + 5),
                               QPointF(RULER_PX - 1, c)])
        p.setBrush(Qt.BrushStyle.NoBrush)
        # pointer position
        mp = cv.mouse_pos
        if mp is not None:
            c = (mp.x() if self.horizontal else mp.y()) + off
            p.setPen(QPen(pal.color(pal.ColorRole.Highlight), 1))
            if self.horizontal:
                p.drawLine(QPointF(c, 0), QPointF(c, RULER_PX))
            else:
                p.drawLine(QPointF(0, c), QPointF(RULER_PX, c))
        p.setPen(QPen(tick, 1))
        if self.horizontal:
            p.drawLine(0, RULER_PX - 1, self.width(), RULER_PX - 1)
        else:
            p.drawLine(RULER_PX - 1, 0, RULER_PX - 1, self.height())
        p.end()

    def _canvas_pos(self, ev) -> QPointF:
        return QPointF(self.canvas.mapFromGlobal(
            ev.globalPosition().toPoint()))

    def mousePressEvent(self, ev):
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        if not self.canvas.doc.grid.get("show_guides", True):
            self.canvas.win.set_grid_prop("show_guides", True)
        self._dragging = True
        # top ruler -> horizontal guide (a y position)
        self.canvas.guide_drag_begin("y" if self.horizontal else "x")
        self.canvas.guide_drag_move(self._canvas_pos(ev))

    def mouseMoveEvent(self, ev):
        if self._dragging:
            self.canvas.guide_drag_move(self._canvas_pos(ev))

    def mouseReleaseEvent(self, ev):
        if self._dragging:
            self._dragging = False
            self.canvas.guide_drag_end(self._canvas_pos(ev))
