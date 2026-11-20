"""Geometry + painting for items, layers and the whole mandala.

Symmetry is a set of document-space transforms: one rotation per
segment (and, with `mirror`, one reflection per segment). Every
transform is paired with the index of the wedge its copy lands in, so
hit-testing and "clip to segment" know which copy lives where.
"""

from __future__ import annotations

import base64
import math

from PySide6.QtCore import Qt, QRectF, QPointF, QByteArray
from PySide6.QtGui import (QPainter, QPainterPath, QTransform, QPen,
                           QBrush, QColor, QImage, QPolygonF)
from PySide6.QtSvg import QSvgRenderer

from .model import (Item, Layer, Document, RECT, ELLIPSE, POLYGON, STAR,
                    PATH, IMAGE, SVG)

UNIT = QRectF(-0.5, -0.5, 1.0, 1.0)

_image_cache: dict = {}
_svg_cache: dict = {}


# ------------------------------------------------------------- geometry
def regular_polygon(sides: int, inner: float | None = None) -> QPolygonF:
    """Unit-box polygon (or star when `inner` is given), point up."""
    sides = max(3, int(sides))
    pts = []
    count = sides * 2 if inner is not None else sides
    for k in range(count):
        a = -math.pi / 2 + k * math.pi * 2 / count
        r = 0.5 if (inner is None or k % 2 == 0) else 0.5 * inner
        pts.append(QPointF(r * math.cos(a), r * math.sin(a)))
    return QPolygonF(pts)


def segments_path(segments: list) -> QPainterPath:
    p = QPainterPath()
    for seg in segments:
        op = seg[0]
        if op == "M":
            p.moveTo(seg[1], seg[2])
        elif op == "L":
            p.lineTo(seg[1], seg[2])
        elif op == "C":
            p.cubicTo(seg[1], seg[2], seg[3], seg[4], seg[5], seg[6])
        elif op == "Z":
            p.closeSubpath()
    return p


def unit_path(item: Item) -> QPainterPath:
    p = QPainterPath()
    k = item.kind
    if k == RECT:
        if item.corner_radius > 0:
            r = min(item.corner_radius, min(item.w, item.h) / 2)
            p.addRoundedRect(UNIT, r / max(item.w, 1e-6),
                             r / max(item.h, 1e-6))
        else:
            p.addRect(UNIT)
    elif k == ELLIPSE:
        p.addEllipse(UNIT)
    elif k == POLYGON:
        p.addPolygon(regular_polygon(item.sides))
        p.closeSubpath()
    elif k == STAR:
        p.addPolygon(regular_polygon(item.sides, item.inner_ratio))
        p.closeSubpath()
    elif k == PATH:
        p = segments_path(item.segments)
    else:
        p.addRect(UNIT)
    return p


def item_transform(item: Item) -> QTransform:
    """Local unit box -> document coords."""
    t = QTransform()
    t.translate(item.cx, item.cy)
    t.rotate(item.rotation)
    t.scale(item.w * (-1 if item.flip_x else 1),
            item.h * (-1 if item.flip_y else 1))
    return t


def item_path(item: Item) -> QPainterPath:
    """Outline in document coords (stroke width is not scaled)."""
    return item_transform(item).map(unit_path(item))


def item_bounds(item: Item) -> QRectF:
    if item.kind in (IMAGE, SVG):
        r = item_transform(item).mapRect(UNIT)
    else:
        r = item_path(item).boundingRect()
    m = (item.stroke_width / 2 + 1) if item.stroke else 1
    return r.adjusted(-m, -m, m, m)


def is_closed(item: Item) -> bool:
    if item.kind != PATH:
        return True
    return bool(item.segments) and item.segments[-1][0] == "Z"


def hit_test(item: Item, x: float, y: float, tol: float = 4.0) -> bool:
    if item.kind in (IMAGE, SVG):
        inv, ok = item_transform(item).inverted()
        if not ok:
            return False
        lp = inv.map(QPointF(x, y))
        return UNIT.contains(lp)
    path = item_path(item)
    if is_closed(item) and (item.fill or not item.stroke) \
            and path.contains(QPointF(x, y)):
        return True
    from PySide6.QtGui import QPainterPathStroker
    st = QPainterPathStroker()
    st.setWidth(max(item.stroke_width if item.stroke else 0, 0) + tol * 2)
    return st.createStroke(path).contains(QPointF(x, y))


# -------------------------------------------------------------- symmetry
def _rot(doc: Document, deg: float) -> QTransform:
    """Rotation by `deg` around the mandala center."""
    c = doc.center
    t = QTransform()
    t.translate(c, c)
    t.rotate(deg)
    t.translate(-c, -c)
    return t


def _mirrored(doc: Document, deg: float) -> QTransform:
    """Rotation `deg` composed with a reflection across the bisector of
    the active wedge — every wedge then holds a mirrored pair, the
    classic kaleidoscope look."""
    c = doc.center
    b = float(doc.symmetry.get("angle") or 0.0)   # bisector of wedge 0
    t = QTransform()
    t.translate(c, c)
    t.rotate(b + deg)
    t.scale(1, -1)
    t.rotate(-b)
    t.translate(-c, -c)
    return t


def group_transforms(doc: Document, layer: Layer | None = None) -> list:
    """[(QTransform, wedge_index)] for every symmetry copy.

    Copy 0 is the item itself, drawn in place; copy k is it rotated by
    k segments, landing in wedge k. Mirrored copy k is the item
    reflected across the active wedge's bisector, then rotated into
    wedge k. Layers that opt out of symmetry get just the identity.
    """
    if layer is not None and not layer.symmetry:
        return [(QTransform(), 0)]
    n = doc.segments
    step = doc.segment_angle
    out = [(_rot(doc, k * step), k) for k in range(n)]
    if doc.symmetry.get("mirror"):
        out += [(_mirrored(doc, k * step), k) for k in range(n)]
    return out


def wedge_index(doc: Document, pt: QPointF) -> int:
    """Which wedge document point `pt` falls in. Wedge 0 — the active
    segment — is centered on the symmetry angle (its bisector)."""
    a = float(doc.symmetry.get("angle") or 0.0) - doc.segment_angle / 2
    ang = math.degrees(math.atan2(pt.y() - doc.center,
                                pt.x() - doc.center))
    return int(math.floor((ang - a) / doc.segment_angle)) % doc.segments


def wedge_path(doc: Document, w: int, radius_scale: float = 4.0
               ) -> QPainterPath:
    """Pie path for wedge `w`, oversized so only the angle matters.

    Wedge w is centered on angle + w·segment_angle; arcTo's positive
    span covers atan2 [A − span, A], so the start angle is the wedge's
    far (clockwise) boundary."""
    c = QPointF(doc.center, doc.center)
    r = doc.radius * radius_scale
    p = QPainterPath(c)
    # Wedge w spans atan2 [a − step/2 + w·step, + step]. arcTo(A, span)
    # sweeps the OPPOSITE way: it covers [−A, −A−span], so to cover
    # [s0, s0 + step] we start at −s0 and sweep −step.
    s0 = (float(doc.symmetry.get("angle") or 0.0)
          + (w - 0.5) * doc.segment_angle)
    p.arcTo(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r),
            -s0, -doc.segment_angle)
    p.closeSubpath()
    return p


def polar(doc: Document, pt: QPointF):
    """(radius, angle_degrees) of `pt` relative to the center."""
    dx, dy = pt.x() - doc.center, pt.y() - doc.center
    return math.hypot(dx, dy), math.degrees(math.atan2(dy, dx))


# --------------------------------------------------------------- assets
def asset_image(doc: Document, key: str) -> QImage | None:
    img = _image_cache.get(key)
    if img is None:
        a = doc.assets.get(key)
        if not a or a.get("type") != "png":
            return None
        img = QImage.fromData(base64.b64decode(a["data"]), "PNG")
        _image_cache[key] = img
    return img


def asset_svg(doc: Document, key: str) -> QSvgRenderer | None:
    r = _svg_cache.get(key)
    if r is None:
        a = doc.assets.get(key)
        if not a or a.get("type") != "svg":
            return None
        r = QSvgRenderer(QByteArray(a["data"].encode("utf-8")))
        _svg_cache[key] = r
    return r


# -------------------------------------------------------------- painting
def make_pen(item: Item) -> QPen:
    if not item.stroke or item.stroke_width <= 0:
        return QPen(Qt.PenStyle.NoPen)
    pen = QPen(QColor(item.stroke), item.stroke_width)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    return pen


def draw_item(p: QPainter, item: Item, doc: Document):
    p.save()
    if item.opacity < 1:
        p.setOpacity(p.opacity() * item.opacity)
    if item.kind == IMAGE:
        img = asset_image(doc, item.asset) if item.asset else None
        if img is not None:
            p.setTransform(item_transform(item), True)
            p.drawImage(UNIT, img)
    elif item.kind == SVG:
        r = asset_svg(doc, item.asset) if item.asset else None
        if r is not None:
            p.setTransform(item_transform(item), True)
            r.render(p, UNIT)
    else:
        path = item_path(item)
        p.setPen(make_pen(item))
        if item.fill and is_closed(item):
            p.setBrush(QBrush(QColor(item.fill)))
        else:
            p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
    p.restore()


def paint_layer(p: QPainter, layer: Layer, doc: Document):
    """Paint one layer with its symmetry copies. When `clip` is on, each
    copy is confined to the wedge it lands in — which means only the
    part of an item inside the active wedge (wedge 0) is ever painted,
    then replicated into every segment."""
    p.save()
    p.setOpacity(layer.opacity)
    copies = group_transforms(doc, layer)
    clip = bool(doc.symmetry.get("clip")) and len(copies) > 1
    for it in layer.items:
        if clip:
            for w in range(doc.segments):
                for t, tw in copies:
                    if tw != w:
                        continue
                    p.save()
                    p.setClipPath(wedge_path(doc, w),
                                  Qt.ClipOperation.IntersectClip)
                    p.setTransform(t, True)
                    draw_item(p, it, doc)
                    p.restore()
        else:
            for t, _w in copies:
                p.save()
                p.setTransform(t, True)
                draw_item(p, it, doc)
                p.restore()
    p.restore()


def paint_document(p: QPainter, doc: Document, background: bool = True,
                   layers=None, clip_circle: bool = True):
    """Paint the whole mandala in document units (caller sets scale)."""
    R = doc.radius
    disc = QPainterPath()
    disc.addEllipse(QRectF(0, 0, doc.size, doc.size))
    p.save()
    p.setClipRect(QRectF(-doc.size, -doc.size, doc.size * 3, doc.size * 3))
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    if background and doc.background:
        p.fillPath(disc, QBrush(QColor(doc.background)))
    if clip_circle:
        p.setClipPath(disc)
    for lay in (layers if layers is not None else doc.layers):
        if lay.visible:
            paint_layer(p, lay, doc)
    p.restore()


def render_document(doc: Document, px: int, background: bool = True,
                    layers=None, clip_circle: bool = True) -> QImage:
    px = max(1, int(px))
    img = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.scale(px / doc.size, px / doc.size)
    paint_document(p, doc, background, layers, clip_circle)
    p.end()
    return img


def render_layer_image(doc: Document, layer: Layer, px: int) -> QImage:
    """One layer with its copies, transparent elsewhere."""
    img = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.scale(px / doc.size, px / doc.size)
    paint_layer(p, layer, doc)
    p.end()
    return img
