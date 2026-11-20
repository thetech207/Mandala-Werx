"""Mandala canvas: a circular workspace with a polar grid, split into
equal segments. Items are drawn once and replicated into every segment
(plus a mirrored copy when mirror symmetry is on).

Everything is edited in document units (0..size, center = size/2).
Selection and dragging understand the symmetry copies: grabbing a copy
in another segment drags its source item correctly.
"""

from __future__ import annotations

import json
import math
from enum import Enum

from PySide6.QtCore import Qt, QPointF, QRectF, Signal, QTimer
from PySide6.QtGui import (QPainter, QColor, QPen, QBrush, QImage,
                           QTransform, QPainterPath, QPolygonF)
from PySide6.QtWidgets import QWidget, QMenu, QApplication

from ..core.model import (Item, RECT, ELLIPSE, POLYGON, STAR, PATH, IMAGE,
                          SVG)
from ..core import render
from ..core.snap import (pixel_snap, snap_value, snap_span, snap_point,
                         is_flat, ring_radii, spoke_angles)


class Tool(Enum):
    SELECT = "select"
    RECT = "rect"
    ELLIPSE = "ellipse"
    POLYGON = "polygon"
    STAR = "star"
    LINE = "line"
    PEN = "pen"
    PENCIL = "pencil"
    EYEDROPPER = "eyedropper"
    PAN = "pan"


SHAPE_TOOLS = {Tool.RECT: RECT, Tool.ELLIPSE: ELLIPSE,
               Tool.POLYGON: POLYGON, Tool.STAR: STAR}
HANDLE_PX = 7
SNAP_PX = 8
CENTER_SNAP_PX = 5
STRAIGHTEN_PX = 6
GUIDE_PX = 4
GUIDE_COLOR = QColor(0, 168, 232)
SEGMENT_COLOR = QColor(230, 120, 30)
PENCIL_GAP = 2.0            # document units between pencil samples


def make_path_item(segments_doc: list, style: dict) -> Item:
    """Build a PATH item from segments given in document coordinates."""
    xs, ys = [], []
    for s in segments_doc:
        xs += s[1::2]
        ys += s[2::2]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    w, h = max(x1 - x0, 1.0), max(y1 - y0, 1.0)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    unit = []
    for s in segments_doc:
        out = [s[0]]
        for k in range(1, len(s), 2):
            out += [(s[k] - cx) / w, (s[k + 1] - cy) / h]
        unit.append(out)
    closed = bool(unit) and unit[-1][0] == "Z"
    return Item(PATH, cx=cx, cy=cy, w=w, h=h, segments=unit,
                fill=style["fill"] if closed else None,
                stroke=style["stroke"] or ("#1c1c1c" if not closed
                                           else None),
                stroke_width=style["stroke_width"])


def _smooth_segments(points: list, closed: bool = False) -> list:
    """Catmull-Rom -> cubic Bezier through `points` (doc coords)."""
    n = len(points)
    if n < 2:
        return []
    pts = [QPointF(p) for p in points]
    segs = [["M", pts[0].x(), pts[0].y()]]
    rng = range(n - 1) if not closed else range(n)
    for i in rng:
        p0 = pts[i - 1] if i > 0 or closed else pts[0]
        p1 = pts[i]
        p2 = pts[(i + 1) % n]
        p3 = pts[(i + 2) % n] if closed or i + 2 < n else p2
        c1 = QPointF(p1.x() + (p2.x() - p0.x()) / 6,
                     p1.y() + (p2.y() - p0.y()) / 6)
        c2 = QPointF(p2.x() - (p3.x() - p1.x()) / 6,
                     p2.y() - (p3.y() - p1.y()) / 6)
        segs.append(["C", c1.x(), c1.y(), c2.x(), c2.y(), p2.x(), p2.y()])
    if closed:
        segs.append(["Z"])
    return segs


class MandalaCanvas(QWidget):
    tool_changed = Signal(object)
    color_picked = Signal(str, bool)       # color, is_stroke
    zoom_changed = Signal(float)

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(300, 300)
        self.tool = Tool.SELECT
        self.zoom = 0.25
        self.pan = QPointF(0, 0)
        self.dim_outside = True
        self.show_border = True
        self._layer_cache: dict = {}       # lid -> (key, px, QImage)
        self._doc_img: QImage | None = None
        self._dirty = True
        self._drag = None                  # active drag state dict
        self._pen_nodes: list = []         # [(x, y, hx, hy)]
        self._pencil_pts: list = []
        self._hover = None
        self._space = False
        self._fitted = False
        self.rulers: list = []
        self.mouse_pos: QPointF | None = None   # widget coords

    # -------------------------------------------------------- view math
    @property
    def doc(self):
        return self.win.doc

    def S(self) -> float:
        return float(self.doc.size)

    def to_doc(self, pos) -> QPointF:
        return QPointF((pos.x() - self.pan.x()) / self.zoom,
                       (pos.y() - self.pan.y()) / self.zoom)

    def to_screen(self, pt) -> QPointF:
        return QPointF(pt.x() * self.zoom + self.pan.x(),
                       pt.y() * self.zoom + self.pan.y())

    def center_screen(self) -> QPointF:
        return self.to_screen(QPointF(self.doc.center, self.doc.center))

    def fit(self):
        S = self.S()
        avail = min(self.width(), self.height()) - 60
        self.zoom = max(0.02, avail / S)
        self.pan = QPointF(self.width() / 2 - S * self.zoom / 2,
                           self.height() / 2 - S * self.zoom / 2)
        self._snap_view()
        self.zoom_changed.emit(self.zoom)
        self.update()

    def zoom_by(self, factor, anchor=None):
        anchor = anchor or QPointF(self.width() / 2, self.height() / 2)
        before = self.to_doc(anchor)
        self.zoom = max(0.02, min(16.0, self.zoom * factor))
        self.pan = QPointF(anchor.x() - before.x() * self.zoom,
                           anchor.y() - before.y() * self.zoom)
        self._snap_view()
        self.zoom_changed.emit(self.zoom)
        self.update()

    def set_tool(self, tool: Tool):
        if self._pen_nodes and tool is not Tool.PEN:
            self._finish_pen(False)
        self.tool = tool
        self._drag = None
        cur = {Tool.PAN: Qt.CursorShape.OpenHandCursor,
               Tool.SELECT: Qt.CursorShape.ArrowCursor,
               Tool.EYEDROPPER: Qt.CursorShape.PointingHandCursor}
        self.setCursor(cur.get(tool, Qt.CursorShape.CrossCursor))
        self.tool_changed.emit(tool)
        self.update()

    # -------------------------------------------------------- doc cache
    def invalidate(self):
        self._dirty = True
        self.update()

    def _snap_view(self):
        dpr = self.devicePixelRatioF() or 1.0
        S = self.S()
        if S * self.zoom * dpr <= 4096:
            self.zoom = max(1.0, round(S * self.zoom * dpr)) / (S * dpr)
        self.pan = QPointF(round(self.pan.x() * dpr) / dpr,
                           round(self.pan.y() * dpr) / dpr)

    def _render_px(self) -> int:
        want = self.S() * self.zoom * self.devicePixelRatioF()
        return int(max(1, min(4096, round(want))))

    def _layer_key(self, lay) -> str:
        base = json.dumps([i.to_dict() for i in lay.items], sort_keys=True)
        sym = json.dumps(self.doc.symmetry, sort_keys=True)
        return (f"{lay.opacity}|{lay.symmetry}|{self.doc.size}|{sym}|"
                f"{base}")

    def doc_image(self) -> QImage:
        px = self._render_px()
        if not self._dirty and self._doc_img is not None \
                and self._doc_img.width() == px:
            return self._doc_img
        doc = self.doc
        img = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        scale = px / doc.size
        disc = QPainterPath()
        disc.addEllipse(QRectF(0, 0, px, px))
        p.setClipPath(disc)
        if doc.background:
            p.fillPath(disc, QBrush(QColor(doc.background)))
        live = set()
        for lay in doc.layers:
            if not lay.visible:
                continue
            live.add(lay.id)
            key = self._layer_key(lay)
            hit = self._layer_cache.get(lay.id)
            if hit and hit[0] == key and hit[1] == px:
                limg = hit[2]
            else:
                limg = render.render_layer_image(doc, lay, px)
                self._layer_cache[lay.id] = (key, px, limg)
            p.drawImage(0, 0, limg)
        p.end()
        for lid in list(self._layer_cache):
            if lid not in live:
                del self._layer_cache[lid]
        self._doc_img = img
        self._dirty = False
        return img

    # -------------------------------------------------------- painting
    def paintEvent(self, _ev):
        self._snap_view()
        p = QPainter(self)
        p.fillRect(self.rect(), self.palette().color(
            self.backgroundRole()).darker(115))
        S = self.S()
        sw = S * self.zoom
        disc_screen = QPainterPath()
        disc_screen.addEllipse(QRectF(self.pan.x(), self.pan.y(), sw, sw))
        img = self.doc_image()
        if not self.doc.background:
            p.save()
            p.setClipPath(disc_screen)
            self._checker(p, QRectF(self.pan.x(), self.pan.y(), sw, sw))
            p.restore()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawImage(QRectF(self.pan.x(), self.pan.y(), sw, sw), img)
        # dim everything outside the disc
        if self.dim_outside:
            ring = QPainterPath()
            ring.setFillRule(Qt.FillRule.OddEvenFill)
            ring.addRect(QRectF(self.rect()))
            ring.addPath(disc_screen)
            p.fillPath(ring, QColor(60, 60, 60, 90))
        # circle border
        if self.show_border:
            p.setPen(QPen(QColor(0, 0, 0, 160), 1, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(disc_screen)
        self._paint_wedges(p, disc_screen)
        self._paint_grid(p, disc_screen)
        self._paint_guides(p)
        self._paint_overlay(p)
        p.end()
        for r in self.rulers:
            r.update()

    def _paint_wedges(self, p: QPainter, disc: QPainterPath):
        """Segment boundaries + the active-wedge highlight. Wedge 0 (the
        active segment) is centered on the symmetry angle — straight up
        by default."""
        doc = self.doc
        n = doc.segments
        if n < 2:
            return
        c = self.center_screen()
        r = doc.radius * self.zoom
        a = float(doc.symmetry.get("angle") or 0.0)
        step = doc.segment_angle
        start = a - step / 2          # first boundary of the active wedge
        hi = self.palette().color(self.palette().ColorRole.Highlight)
        p.save()
        p.setClipPath(disc)
        if doc.symmetry.get("highlight"):
            # dim everything outside the active wedge and tint it
            ring = QPainterPath()
            ring.setFillRule(Qt.FillRule.OddEvenFill)
            ring.addPath(disc)
            ring.addPath(self._screen_wedge(0))
            p.fillPath(ring, QColor(0, 0, 0, 45))
            p.fillPath(self._screen_wedge(0),
                       QColor(hi.red(), hi.green(), hi.blue(), 28))
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.setPen(QPen(QColor(SEGMENT_COLOR.red(), SEGMENT_COLOR.green(),
                             SEGMENT_COLOR.blue(), 170), 1,
                      Qt.PenStyle.DashLine))
        for k in range(n):
            rad = math.radians(start + k * step)
            p.drawLine(c, QPointF(c.x() + r * math.cos(rad),
                                  c.y() + r * math.sin(rad)))
        if doc.symmetry.get("highlight"):
            # the active wedge's boundaries and bisector stand out
            p.setPen(QPen(hi, 1.6))
            for k in (0, 1):
                rad = math.radians(start + k * step)
                p.drawLine(c, QPointF(c.x() + r * math.cos(rad),
                                      c.y() + r * math.sin(rad)))
            p.setPen(QPen(hi, 1.2, Qt.PenStyle.DashLine))
            rad = math.radians(a)
            p.drawLine(c, QPointF(c.x() + r * math.cos(rad),
                                  c.y() + r * math.sin(rad)))
        p.restore()

    def _screen_wedge(self, w: int) -> QPainterPath:
        """Wedge `w` as a screen-space pie path (clipped to the disc by
        the caller). Same arc convention as render.wedge_path."""
        doc = self.doc
        c = self.center_screen()
        r = doc.radius * self.zoom
        a = (float(doc.symmetry.get("angle") or 0.0)
             + (w - 0.5) * doc.segment_angle)
        path = QPainterPath(c)
        path.arcTo(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r),
                   -a, -doc.segment_angle)
        path.closeSubpath()
        return path

    def _paint_grid(self, p: QPainter, disc: QPainterPath):
        g = self.doc.grid
        if not g.get("show"):
            return
        doc = self.doc
        c = self.center_screen()
        R = doc.radius
        base = QColor(g.get("color") or "#4a7ab5")
        minor, major = QColor(base), QColor(base)
        minor.setAlpha(45)
        major.setAlpha(120)
        p.save()
        p.setClipPath(disc)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        rings = max(1, int(g.get("rings") or 1))
        sub = max(0, int(g.get("subdivisions") or 0))
        band = R / rings
        # minor rings between the major ones
        if sub:
            p.setPen(QPen(minor, 1))
            for k in range(rings):
                for j in range(1, sub + 1):
                    rr = (k + j / (sub + 1)) * band * self.zoom
                    if rr > 2:
                        p.drawEllipse(c, rr, rr)
        p.setPen(QPen(major, 1))
        for rr in ring_radii(doc):
            r = rr * self.zoom
            if r > 2:
                p.drawEllipse(c, r, r)
        # spokes (only when the user set an explicit count; spokes=0
        # follows the segments, which already show as orange lines)
        spokes = int(g.get("spokes") or 0)
        if spokes:
            ang0 = float(doc.symmetry.get("angle") or 0.0)
            r = R * self.zoom
            for j in range(spokes):
                rad = math.radians(ang0 + j * 360.0 / spokes)
                p.drawLine(c, QPointF(c.x() + r * math.cos(rad),
                                      c.y() + r * math.sin(rad)))
        # center dot
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(major)
        p.drawEllipse(c, 2, 2)
        p.restore()

    def _paint_guides(self, p: QPainter):
        if not self.doc.grid.get("show_guides", True):
            return
        d = self._drag
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.setPen(QPen(GUIDE_COLOR, 1))
        for axis in ("x", "y"):
            for idx, gp in enumerate(self.doc.guides.get(axis, [])):
                if d and d.get("mode") == "guide" and d["axis"] == axis \
                        and d["index"] == idx and not d.get("inside"):
                    continue
                v = math.floor(self.to_screen(
                    QPointF(gp, gp)).x() if axis == "x" else
                    self.to_screen(QPointF(gp, gp)).y()) + 0.5
                if axis == "x":
                    p.drawLine(QPointF(v, 0), QPointF(v, self.height()))
                else:
                    p.drawLine(QPointF(0, v), QPointF(self.width(), v))
        p.restore()

    def _guide_at(self, pos):
        g = self.doc.grid
        if not g.get("show_guides", True) or g.get("lock_guides"):
            return None
        for axis in ("x", "y"):
            c = pos.x() if axis == "x" else pos.y()
            for idx, gp in enumerate(self.doc.guides.get(axis, [])):
                sp = self.to_screen(QPointF(gp, gp))
                v = sp.x() if axis == "x" else sp.y()
                if abs(v - c) <= GUIDE_PX:
                    return axis, idx
        return None

    # guides are dragged from the rulers or moved on the canvas
    def guide_drag_begin(self, axis, index=None):
        self.win.begin_edit()
        new = index is None
        if new:
            self.doc.guides.setdefault(axis, []).append(0)
            index = len(self.doc.guides[axis]) - 1
        self._drag = {"mode": "guide", "axis": axis, "index": index,
                      "new": new, "inside": not new}
        self.update()

    def guide_drag_move(self, pos):
        d = self._drag
        if not d or d.get("mode") != "guide":
            return
        pt = self.to_doc(pos)
        axis = d["axis"]
        v = pt.x() if axis == "x" else pt.y()
        c = self.doc.center
        free = bool(QApplication.keyboardModifiers()
                    & Qt.KeyboardModifier.AltModifier)
        if not free and abs(c - v) * self.zoom <= CENTER_SNAP_PX:
            v = c                          # mandala center (ruler mark)
        self.doc.guides[axis][d["index"]] = int(round(v))
        d["inside"] = self.rect().contains(pos.toPoint())
        self.win.show_coords(pt)
        self.update()

    def guide_drag_end(self, pos):
        d = self._drag
        self._drag = None
        if not d or d.get("mode") != "guide":
            return
        inside = self.rect().contains(pos.toPoint())
        if not inside:
            del self.doc.guides[d["axis"]][d["index"]]
            label = "Delete guide"
        else:
            label = "Add guide" if d["new"] else "Move guide"
        self.win.end_edit(label)
        self.update()

    # ---------------------------------------------------------- snapping
    def _snap_thr(self) -> float:
        return SNAP_PX / self.zoom

    def snap_pt(self, pt: QPointF) -> QPointF:
        """Snap a document point to guides/edges/center, then the polar
        grid (rings, spokes), else a whole unit."""
        return snap_point(self.doc, pt, self._snap_thr())

    def _straighten(self, a, b: QPointF) -> QPointF:
        """A segment within a few screen px of horizontal/vertical
        becomes exactly so."""
        ax, ay = (a[0], a[1]) if isinstance(a, (list, tuple)) \
            else (a.x(), a.y())
        dx, dy = b.x() - ax, b.y() - ay
        lim = STRAIGHTEN_PX / self.zoom
        if abs(dx) <= lim and abs(dy) > abs(dx):
            return QPointF(ax, b.y())
        if abs(dy) <= lim and abs(dx) > abs(dy):
            return QPointF(b.x(), ay)
        return b

    @staticmethod
    def _geom_bounds(items) -> QRectF:
        r = QRectF()
        for it in items:
            b = render.item_transform(it).mapRect(render.UNIT)
            r = b if r.isNull() else r.united(b)
        return r

    def _checker(self, p, rect):
        p.save()
        p.setClipRect(rect)
        s = 10
        p.fillRect(rect, QColor("#ffffff"))
        c = QColor("#d8d8d8")
        y = int(rect.top())
        row = 0
        while y < rect.bottom():
            x = int(rect.left()) + (s if row % 2 else 0)
            while x < rect.right():
                p.fillRect(x, y, s, s, c)
                x += 2 * s
            y += s
            row += 1
        p.restore()

    def _view_transform(self) -> QTransform:
        t = QTransform()
        t.translate(self.pan.x(), self.pan.y())
        t.scale(self.zoom, self.zoom)
        return t

    def _copies(self, layer) -> list:
        return render.group_transforms(self.doc, layer)

    def _paint_overlay(self, p: QPainter):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        vt = self._view_transform()
        sel = self.win.selected_items()
        lay = self.doc.layer(self.win.active_layer_id)
        hi = self.palette().color(self.palette().ColorRole.Highlight)
        # selection outlines on every symmetry copy
        copies = self._copies(lay) if lay else [(QTransform(), 0)]
        for it in sel:
            outline = self._outline(it)
            for t, _w in copies:
                path = vt.map(t.map(outline))
                p.setPen(QPen(QColor(255, 255, 255, 200), 3))
                p.drawPath(path)
                p.setPen(QPen(hi, 1.5))
                p.drawPath(path)
            if it.kind == PATH:
                self._paint_path_ends(p, it, vt, hi)
        if sel and self.tool is Tool.SELECT:
            self._paint_handles(p, sel, hi)
        d = self._drag
        if d and d.get("mode") == "rubber":
            r = QRectF(self.to_screen(d["start"]),
                       self.to_screen(d["cur"])).normalized()
            p.setPen(QPen(hi, 1, Qt.PenStyle.DashLine))
            p.setBrush(QColor(hi.red(), hi.green(), hi.blue(), 40))
            p.drawRect(r)
        # live previews show the symmetry copies too
        ghost = None
        if d and d.get("mode") == "create" and d.get("preview"):
            ghost = render.item_path(d["preview"])
        elif self._pencil_pts and len(self._pencil_pts) > 1:
            ghost = render.segments_path(
                _smooth_segments(self._pencil_pts))
        elif self._pen_nodes:
            ghost = render.segments_path(
                self._pen_segments(closed=False, preview=self._hover))
        if ghost is not None:
            clip = bool(self.doc.symmetry.get("clip"))
            for t, w in self._copies(self.doc.layer(
                    self.win.active_layer_id)):
                p.save()
                if clip:
                    # each copy is confined to its wedge, so only the
                    # active-wedge slice registers
                    disc = QPainterPath()
                    disc.addEllipse(
                        QRectF(0, 0, self.doc.size, self.doc.size))
                    p.setClipPath(vt.map(disc),
                                  Qt.ClipOperation.IntersectClip)
                    p.setClipPath(vt.map(render.wedge_path(self.doc, w)),
                                  Qt.ClipOperation.IntersectClip)
                p.setPen(QPen(hi, 1.5, Qt.PenStyle.DashLine))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPath(vt.map(t.map(ghost)))
                p.restore()
        if self._pen_nodes:
            p.setBrush(QColor("#ffffff"))
            p.setPen(QPen(hi, 1))
            for n in self._pen_nodes:
                sp = self.to_screen(QPointF(n[0], n[1]))
                p.drawRect(QRectF(sp.x() - 3, sp.y() - 3, 6, 6))
                if n[2] or n[3]:
                    for s in (1, -1):
                        hp = self.to_screen(QPointF(n[0] + s * n[2],
                                                    n[1] + s * n[3]))
                        p.drawLine(sp, hp)
                        p.drawEllipse(hp, 2.5, 2.5)

    def _outline(self, it: Item) -> QPainterPath:
        if it.kind == PATH:
            return render.item_path(it)
        if it.kind in (IMAGE, SVG):
            path = QPainterPath()
            path.addPolygon(render.item_transform(it).map(_unit_poly()))
            path.closeSubpath()
            return path
        return render.item_path(it)

    def _paint_path_ends(self, p: QPainter, it: Item, vt, hi):
        """Start/end node markers for a selected path — a pen path is a
        line between two endpoints, not a bounding box."""
        pts = []
        for s in it.segments:
            if s[0] == "Z":
                continue
            pts.append(QPointF(s[-2], s[-1]))
        if not pts:
            return
        t = render.item_transform(it)
        first = t.map(pts[0])
        last = t.map(pts[-1])
        for pt, filled in ((first, True), (last, False)):
            sp = self.to_screen(pt)
            p.setPen(QPen(hi, 1.5))
            p.setBrush(QColor(hi) if filled
                       else QColor("#ffffff"))
            p.drawRect(QRectF(sp.x() - 3.5, sp.y() - 3.5, 7, 7))

    # handles: list of (kind, screen_point, data)
    def _handles(self, sel):
        if not sel:
            return []
        if len(sel) == 1:
            it = sel[0]
            t = render.item_transform(it)
            out = []
            if it.kind != PATH:     # paths get endpoint markers, no box
                for hx in (-1, 0, 1):
                    for hy in (-1, 0, 1):
                        if hx == 0 and hy == 0:
                            continue
                        pt = t.map(QPointF(0.5 * hx, 0.5 * hy))
                        out.append(("scale", self.to_screen(pt),
                                    (hx, hy)))
            top = t.map(QPointF(0, -0.5))
            ctr = QPointF(it.cx, it.cy)
            v = top - ctr
            ln = math.hypot(v.x(), v.y()) or 1
            rot_pt = top + v * (24 / self.zoom / ln)
            out.append(("rotate", self.to_screen(rot_pt), None))
            return out
        r = self._sel_bounds(sel)
        out = []
        for hx in (-1, 0, 1):
            for hy in (-1, 0, 1):
                if hx == 0 and hy == 0:
                    continue
                pt = QPointF(r.center().x() + hx * r.width() / 2,
                             r.center().y() + hy * r.height() / 2)
                out.append(("scale", self.to_screen(pt), (hx, hy)))
        out.append(("rotate", self.to_screen(
            QPointF(r.center().x(), r.top() - 24 / self.zoom)), None))
        return out

    def _sel_bounds(self, sel) -> QRectF:
        r = QRectF()
        for it in sel:
            b = render.item_transform(it).mapRect(render.UNIT) \
                if it.kind in (IMAGE, SVG) else \
                render.item_path(it).boundingRect()
            r = b if r.isNull() else r.united(b)
        return r

    def _paint_handles(self, p, sel, hi):
        p.setPen(QPen(hi, 1.2))
        hs = self._handles(sel)
        for kind, sp, _d in hs:
            if kind == "rotate":
                p.setBrush(QColor("#ffffff"))
                p.drawEllipse(sp, HANDLE_PX / 2 + 1, HANDLE_PX / 2 + 1)
            else:
                p.setBrush(QColor("#ffffff"))
                p.drawRect(QRectF(sp.x() - HANDLE_PX / 2,
                                  sp.y() - HANDLE_PX / 2,
                                  HANDLE_PX, HANDLE_PX))

    # ------------------------------------------------------ hit testing
    def item_at(self, pt: QPointF, layers=None):
        """Topmost (layer, item, copy_transform) under doc point `pt`.
        Symmetry-aware: a hit on any rotated/mirrored copy selects the
        source item, and the returned transform maps item -> that copy."""
        tol = 4 / self.zoom
        order = layers if layers is not None else self._pick_order()
        clip = bool(self.doc.symmetry.get("clip"))
        for lay in order:
            copies = self._copies(lay)
            for it in reversed(lay.items):
                for t, w in copies:
                    if clip and len(copies) > 1 \
                            and render.wedge_index(self.doc, pt) != w:
                        continue
                    inv, ok = t.inverted()
                    if not ok:
                        continue
                    q = inv.map(pt)
                    if render.hit_test(it, q.x(), q.y(), tol):
                        return lay, it, t
        return None, None, None

    def _pick_order(self):
        doc = self.doc
        act = doc.layer(self.win.active_layer_id)
        rest = [l for l in reversed(doc.layers) if l is not act]
        cands = ([act] if act else []) + rest
        return [l for l in cands if l.visible and not l.locked]

    def _handle_at(self, pos):
        sel = self.win.selected_items()
        for kind, sp, data in self._handles(sel):
            if abs(sp.x() - pos.x()) <= HANDLE_PX and \
                    abs(sp.y() - pos.y()) <= HANDLE_PX:
                return kind, data
        return None

    # ----------------------------------------------------------- mouse
    def mousePressEvent(self, ev):
        self.setFocus()
        pos = ev.position()
        pt = self.to_doc(pos)
        if ev.button() == Qt.MouseButton.MiddleButton or self._space or (
                self.tool is Tool.PAN
                and ev.button() == Qt.MouseButton.LeftButton):
            self._drag = {"mode": "pan", "last": pos}
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        shift = bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if self.tool is Tool.SELECT:
            self._press_select(pos, pt, shift)
        elif self.tool in SHAPE_TOOLS or self.tool is Tool.LINE:
            w = self.snap_pt(pt)
            self._drag = {"mode": "create", "start": w, "cur": w,
                          "preview": None}
        elif self.tool is Tool.PEN:
            w = self.snap_pt(pt)
            if self._pen_nodes and not (
                    ev.modifiers() & Qt.KeyboardModifier.AltModifier):
                w = self._straighten(self._pen_nodes[-1], w)
            if len(self._pen_nodes) > 2:
                first = self._pen_nodes[0]
                fs = self.to_screen(QPointF(first[0], first[1]))
                if math.hypot(fs.x() - pos.x(), fs.y() - pos.y()) < 8:
                    self._finish_pen(True)
                    return
            self._pen_nodes.append([w.x(), w.y(), 0.0, 0.0])
            self._drag = {"mode": "pen", "start": w}
            self.update()
        elif self.tool is Tool.PENCIL:
            self._pencil_pts = [self.snap_pt(pt)]
            self._drag = {"mode": "pencil"}
            self.update()
        elif self.tool is Tool.EYEDROPPER:
            self._pick_color(pt, shift)

    def _press_select(self, pos, pt, shift):
        h = self._handle_at(pos)
        sel = self.win.selected_items()
        if not (h and sel):
            g = self._guide_at(pos)
            if g:
                self.guide_drag_begin(*g)
                return
        if h and sel:
            kind, data = h
            self.win.begin_edit()
            self._drag = {"mode": kind, "start": pt, "handle": data,
                          "orig": [i.to_dict() for i in sel],
                          "bounds": self._sel_bounds(sel),
                          "ids": [i.id for i in sel]}
            return
        lay, it, xform = self.item_at(pt)
        if it is not None:
            if lay.id != self.win.active_layer_id:
                self.win.set_active_layer(lay.id, keep_selection=False)
            ids = list(self.win.selection)
            if shift:
                if it.id in ids:
                    ids.remove(it.id)
                else:
                    ids.append(it.id)
                self.win.set_selection(ids)
                return
            if it.id not in ids:
                self.win.set_selection([it.id])
            sel = self.win.selected_items()
            self.win.begin_edit()
            # anchor the drag to the copy that was grabbed so it follows
            # the pointer in its own rotated/mirrored frame
            inv, _ok = (xform or QTransform()).inverted()
            self._drag = {"mode": "move", "start": inv.map(pt),
                          "inv": inv, "orig": [i.to_dict() for i in sel],
                          "gbounds": self._geom_bounds(sel),
                          "ids": [i.id for i in sel], "moved": False}
            return
        if not shift:
            self.win.set_selection([])
        self._drag = {"mode": "rubber", "start": pt, "cur": pt,
                      "add": shift}

    def mouseMoveEvent(self, ev):
        pos = ev.position()
        pt = self.to_doc(pos)
        self.mouse_pos = pos
        self.win.show_coords(pt)
        for r in self.rulers:
            r.update()
        d = self._drag
        if self._pen_nodes:
            self._hover = self.snap_pt(pt)
            if not (ev.modifiers() & Qt.KeyboardModifier.AltModifier):
                self._hover = self._straighten(self._pen_nodes[-1],
                                               self._hover)
        if not d:
            if self.tool is Tool.SELECT:
                h = self._handle_at(pos)
                g = None if h else self._guide_at(pos)
                if h:
                    self.setCursor(Qt.CursorShape.CrossCursor
                                   if h[0] == "rotate"
                                   else Qt.CursorShape.SizeAllCursor)
                elif g:
                    self.setCursor(Qt.CursorShape.SplitHCursor
                                   if g[0] == "x"
                                   else Qt.CursorShape.SplitVCursor)
                else:
                    self.setCursor(Qt.CursorShape.ArrowCursor)
            if self._pen_nodes:
                self.update()
            return
        mode = d["mode"]
        shift = bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        alt = bool(ev.modifiers() & Qt.KeyboardModifier.AltModifier)
        if mode == "pan":
            delta = pos - d["last"]
            d["last"] = pos
            self.pan += delta
            self.update()
        elif mode == "guide":
            self.guide_drag_move(pos)
        elif mode == "move":
            cur = d["inv"].map(pt)
            dx, dy = cur.x() - d["start"].x(), cur.y() - d["start"].y()
            if shift:
                if abs(dx) > abs(dy):
                    dy = 0
                else:
                    dx = 0
            r, thr = d["gbounds"], self._snap_thr()
            if dx:
                adj = snap_span(self.doc, r.left() + dx, r.right() + dx,
                                "x", thr)
                dx = dx + adj if adj else round(dx)
            if dy:
                adj = snap_span(self.doc, r.top() + dy, r.bottom() + dy,
                                "y", thr)
                dy = dy + adj if adj else round(dy)
            for it, o in zip(self.win.selected_items(), d["orig"]):
                it.cx, it.cy = o["cx"] + dx, o["cy"] + dy
            d["moved"] = True
            self.invalidate()
        elif mode == "scale":
            self._drag_scale(self.snap_pt(pt), shift)
            for it in self.win.selected_items():
                pixel_snap(it)
            self.invalidate()
        elif mode == "rotate":
            self._drag_rotate(pt, shift)
            self.invalidate()
        elif mode == "rubber":
            d["cur"] = pt
            self.update()
        elif mode == "create":
            cur = self.snap_pt(pt)
            d["cur"] = cur
            d["preview"] = self._shape_from_drag(d["start"], cur, shift,
                                                 alt)
            self.update()
        elif mode == "pencil":
            last = self._pencil_pts[-1]
            gap = max(PENCIL_GAP, 1.5 / self.zoom)
            if math.hypot(pt.x() - last.x(), pt.y() - last.y()) >= gap:
                self._pencil_pts.append(pt)
                self.update()
        elif mode == "pen":
            n = self._pen_nodes[-1]
            n[2], n[3] = round(pt.x() - n[0]), round(pt.y() - n[1])
            self.update()

    def mouseReleaseEvent(self, ev):
        d = self._drag
        self._drag = None
        if not d:
            return
        mode = d["mode"]
        if mode == "pan":
            self.set_tool(self.tool) if not self._space else \
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            return
        if mode == "guide":
            self._drag = d
            self.guide_drag_end(ev.position())
            return
        if mode == "move":
            if d.get("moved"):
                self._normalize_selection()
                self.win.end_edit("Move")
            else:
                self.win.cancel_edit()
        elif mode in ("scale", "rotate"):
            self._normalize_selection()
            self.win.end_edit("Scale" if mode == "scale" else "Rotate")
        elif mode == "rubber":
            r = QRectF(d["start"], d["cur"]).normalized()
            lay = self.doc.layer(self.win.active_layer_id)
            if lay and r.width() > 1 / self.zoom:
                copies = self._copies(lay)
                hits = []
                for it in lay.items:
                    bounds = render.item_bounds(it)
                    if any(t.mapRect(bounds).intersects(r)
                           for t, _w in copies):
                        hits.append(it.id)
                ids = list(self.win.selection) if d["add"] else []
                self.win.set_selection(ids + [h for h in hits
                                              if h not in ids])
            self.update()
        elif mode == "create":
            shift = bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            alt = bool(ev.modifiers() & Qt.KeyboardModifier.AltModifier)
            it = self._shape_from_drag(d["start"], d["cur"], shift, alt)
            if max(it.w, it.h) * self.zoom < 4:
                it = self._shape_from_drag(d["start"], d["start"], shift,
                                           alt, default=True)
            self.win.add_item(it)
        elif mode == "pencil":
            pts = self._pencil_pts
            self._pencil_pts = []
            if len(pts) >= 2:
                segs = _smooth_segments(pts)
                it = make_path_item(segs, self.win.current_style())
                self.win.add_item(it, "Pencil stroke")
            self.update()
        elif mode == "pen":
            self.update()

    def mouseDoubleClickEvent(self, ev):
        if self.tool is Tool.PEN and self._pen_nodes:
            # the double-click's first press already added a node
            if len(self._pen_nodes) > 1:
                self._pen_nodes.pop()
            self._finish_pen(False)
            return
        if self.tool is Tool.SELECT:
            lay, it, _t = self.item_at(self.to_doc(ev.position()))
            if it is not None:
                self.win.focus_item_settings()

    def wheelEvent(self, ev):
        delta = ev.angleDelta().y()
        if ev.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.pan += QPointF(delta / 2, 0)
            self.update()
            return
        if not delta:
            return
        self.zoom_by(1.15 if delta > 0 else 1 / 1.15, ev.position())

    def leaveEvent(self, ev):
        self.mouse_pos = None
        for r in self.rulers:
            r.update()
        super().leaveEvent(ev)

    def contextMenuEvent(self, ev):
        if self._drag or self._pen_nodes:
            return
        pos = QPointF(ev.pos())
        win = self.win
        m = QMenu(self)
        g = self._guide_at(pos)
        if g:
            axis, idx = g
            m.addAction("Delete Guide", lambda: win.delete_guide(axis, idx))
        else:
            lay, it, _t = self.item_at(self.to_doc(pos))
            if it is not None:
                if lay.id != win.active_layer_id:
                    win.set_active_layer(lay.id, keep_selection=False)
                if it.id not in win.selection:
                    win.set_selection([it.id])
                if it.kind in (IMAGE, SVG):
                    m.addAction("Reload from File",
                                lambda: win.reload_assets([it.asset]))
                    m.addSeparator()
                m.addAction("Duplicate", win.duplicate)
                m.addAction("Bring Forward", lambda: win.arrange(1))
                m.addAction("Send Backward", lambda: win.arrange(-1))
                m.addAction("Delete", win.delete_selection)
                m.addSeparator()
            m.addAction("Paste", win.paste)
        m.addSeparator()
        m.addAction("Reload All Imported Files", win.reload_all_assets)
        if any(self.doc.guides.get(a) for a in ("x", "y")):
            m.addAction("Clear Guides", win.clear_guides)
        m.exec(ev.globalPos())

    def keyPressEvent(self, ev):
        k = ev.key()
        if k == Qt.Key.Key_Space and not ev.isAutoRepeat():
            self._space = True
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            return
        if self._pen_nodes and k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._finish_pen(False)
            return
        if k == Qt.Key.Key_Escape:
            if self._pen_nodes:
                self._pen_nodes = []
                self.update()
            else:
                self.win.set_selection([])
            return
        if k in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.win.delete_selection()
            return
        arrows = {Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0),
                  Qt.Key.Key_Up: (0, -1), Qt.Key.Key_Down: (0, 1)}
        if k in arrows and self.win.selection:
            step = 5 if ev.modifiers() & Qt.KeyboardModifier.ShiftModifier \
                else 1
            dx, dy = arrows[k]
            self.win.nudge(dx * step, dy * step)
            return
        super().keyPressEvent(ev)

    def keyReleaseEvent(self, ev):
        if ev.key() == Qt.Key.Key_Space and not ev.isAutoRepeat():
            self._space = False
            self.set_tool(self.tool)
            return
        super().keyReleaseEvent(ev)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if not self._fitted and self.width() > 100:
            self._fitted = True
            QTimer.singleShot(0, self.fit)

    # ------------------------------------------------------ tool logic
    def _shape_from_drag(self, a: QPointF, b: QPointF, square: bool,
                         from_center: bool, default: bool = False) -> Item:
        style = self.win.current_style()
        if default:
            s = 120.0
            b = QPointF(a.x() + s / 2, a.y() + s / 2)
            from_center = True
        dx, dy = b.x() - a.x(), b.y() - a.y()
        if self.tool is Tool.LINE:
            if not square and not from_center and not default:
                s = self._straighten((a.x(), a.y()), b)
                dx, dy = s.x() - a.x(), s.y() - a.y()
            if square:   # snap to 45 degrees
                ang = round(math.atan2(dy, dx) / (math.pi / 4)) * math.pi / 4
                ln = math.hypot(dx, dy)
                dx, dy = ln * math.cos(ang), ln * math.sin(ang)
            if default:
                dx, dy = 120.0, 0.0
            return make_path_item([["M", a.x(), a.y()],
                                   ["L", a.x() + dx, a.y() + dy]],
                                  style)
        # a shape dragged out of the mandala center is drawn centered —
        # nobody wants a circle whose corner is the grid center
        if abs(a.x() - self.doc.center) < 1.5 \
                and abs(a.y() - self.doc.center) < 1.5:
            from_center = True
        if square:
            s = max(abs(dx), abs(dy))
            dx = math.copysign(s, dx or 1)
            dy = math.copysign(s, dy or 1)
        if from_center:
            cx, cy, w, h = a.x(), a.y(), abs(dx) * 2, abs(dy) * 2
        else:
            cx, cy = a.x() + dx / 2, a.y() + dy / 2
            w, h = abs(dx), abs(dy)
        kind = SHAPE_TOOLS.get(self.tool, RECT)
        opts = self.win.shape_options()
        return Item(kind, cx=cx, cy=cy, w=max(w, 1), h=max(h, 1),
                    fill=style["fill"], stroke=style["stroke"],
                    stroke_width=style["stroke_width"],
                    sides=opts["sides"] if kind == POLYGON
                    else opts["points"],
                    inner_ratio=opts["inner_ratio"],
                    corner_radius=opts["corner_radius"]
                    if kind == RECT else 0.0)

    def _pen_segments(self, closed: bool, preview=None) -> list:
        nodes = [list(n) for n in self._pen_nodes]
        if preview is not None and self._drag is None:
            nodes.append([preview.x(), preview.y(), 0.0, 0.0])
        if not nodes:
            return []
        segs = [["M", nodes[0][0], nodes[0][1]]]
        pairs = list(zip(nodes, nodes[1:]))
        if closed and len(nodes) > 2:
            pairs.append((nodes[-1], nodes[0]))
        for a, b in pairs:
            if a[2] or a[3] or b[2] or b[3]:
                segs.append(["C", a[0] + a[2], a[1] + a[3],
                             b[0] - b[2], b[1] - b[3], b[0], b[1]])
            else:
                segs.append(["L", b[0], b[1]])
        if closed:
            segs.append(["Z"])
        return segs

    def _finish_pen(self, closed: bool):
        if len(self._pen_nodes) >= 2:
            segs = self._pen_segments(closed)
            it = make_path_item(segs, self.win.current_style())
            self._pen_nodes = []
            self.win.add_item(it)
        else:
            self._pen_nodes = []
        self._hover = None
        self.update()

    def _pick_color(self, pt, stroke: bool):
        img = self.doc_image()
        s = img.width() / self.S()
        x = int(min(img.width() - 1, max(0, pt.x() * s)))
        y = int(min(img.height() - 1, max(0, pt.y() * s)))
        c = img.pixelColor(x, y)
        self.color_picked.emit(c.name(), stroke)

    def _normalize_selection(self):
        for it in self.win.selected_items():
            pixel_snap(it)

    def _drag_scale(self, pt, keep_aspect):
        d = self._drag
        sel = self.win.selected_items()
        hx, hy = d["handle"]
        if len(sel) == 1:
            o = d["orig"][0]
            it = sel[0]
            if it.kind == PATH:
                # a straight line has no width to drag; keep it in place
                hx = 0 if is_flat(it, 0) else hx
                hy = 0 if is_flat(it, 1) else hy
            a = math.radians(o["rotation"])
            ca, sa = math.cos(a), math.sin(a)
            mx, my = pt.x() - o["cx"], pt.y() - o["cy"]
            lx, ly = mx * ca + my * sa, -mx * sa + my * ca
            w0, h0 = o["w"], o["h"]
            ax, ay = -hx * w0 / 2, -hy * h0 / 2
            nw = abs(lx - ax) if hx else w0
            nh = abs(ly - ay) if hy else h0
            if keep_aspect and hx and hy:
                s = max(nw / max(w0, 1e-6), nh / max(h0, 1e-6))
                nw, nh = w0 * s, h0 * s
            nw, nh = max(nw, 1.0), max(nh, 1.0)
            ncx = ax + hx * nw / 2 if hx else 0.0
            ncy = ay + hy * nh / 2 if hy else 0.0
            it.w, it.h = nw, nh
            it.cx = o["cx"] + ncx * ca - ncy * sa
            it.cy = o["cy"] + ncx * sa + ncy * ca
            return
        r = d["bounds"]
        ax = r.center().x() - hx * r.width() / 2
        ay = r.center().y() - hy * r.height() / 2
        sx0 = d["start"].x() - ax
        sy0 = d["start"].y() - ay
        sx = (pt.x() - ax) / sx0 if hx and abs(sx0) > 1e-6 else 1.0
        sy = (pt.y() - ay) / sy0 if hy and abs(sy0) > 1e-6 else 1.0
        if keep_aspect:
            s = max(abs(sx), abs(sy)) if hx and hy else (
                abs(sx) if hx else abs(sy))
            sx = sy = s
        sx, sy = max(abs(sx), 0.01), max(abs(sy), 0.01)
        for it, o in zip(sel, d["orig"]):
            it.cx = ax + (o["cx"] - ax) * sx
            it.cy = ay + (o["cy"] - ay) * sy
            rot = math.radians(o["rotation"])
            c2, s2 = math.cos(rot) ** 2, math.sin(rot) ** 2
            it.w = o["w"] * (sx * c2 + sy * s2)
            it.h = o["h"] * (sy * c2 + sx * s2)

    def _drag_rotate(self, pt, snap):
        d = self._drag
        sel = self.win.selected_items()
        if len(sel) == 1:
            c = QPointF(d["orig"][0]["cx"], d["orig"][0]["cy"])
        else:
            c = d["bounds"].center()
        a0 = math.atan2(d["start"].y() - c.y(), d["start"].x() - c.x())
        a1 = math.atan2(pt.y() - c.y(), pt.x() - c.x())
        da = math.degrees(a1 - a0)
        if snap:
            if len(sel) == 1:
                tgt = round((d["orig"][0]["rotation"] + da) / 15) * 15
                da = tgt - d["orig"][0]["rotation"]
            else:
                da = round(da / 15) * 15
        r = math.radians(da)
        cr, sr = math.cos(r), math.sin(r)
        for it, o in zip(sel, d["orig"]):
            dx, dy = o["cx"] - c.x(), o["cy"] - c.y()
            it.cx = c.x() + dx * cr - dy * sr
            it.cy = c.y() + dx * sr + dy * cr
            it.rotation = float(round((o["rotation"] + da) % 360) % 360)


def _unit_poly():
    from PySide6.QtGui import QPolygonF
    return QPolygonF([QPointF(-0.5, -0.5), QPointF(0.5, -0.5),
                      QPointF(0.5, 0.5), QPointF(-0.5, 0.5)])
