"""Pixel, polar-grid and guide snapping in document units."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF

from .model import Document, Item, PATH


def is_flat(it: Item, axis: int) -> bool:
    """True when a path has no extent along `axis` (a straight line)."""
    vals = [v for s in it.segments for v in s[1 + axis::2]]
    return bool(vals) and max(vals) - min(vals) < 1e-9


def edge(it: Item, axis: int) -> float:
    """Left (axis 0) or top (axis 1) edge as shown in the Item tab; a
    straight line's position along its flat axis is the line itself."""
    c, s = (it.cx, it.w) if axis == 0 else (it.cy, it.h)
    if it.kind == PATH and is_flat(it, axis):
        return c
    return c - s / 2


def pixel_snap(it: Item):
    """Whole-unit sizes, edges on whole units, whole-degree rotation."""
    it.rotation = float(round(it.rotation))
    for c, s, axis in (("cx", "w", 0), ("cy", "h", 1)):
        if it.kind == PATH and is_flat(it, axis):
            setattr(it, c, float(round(getattr(it, c))))
            setattr(it, s, 1.0)
            continue
        size = max(1.0, float(round(getattr(it, s))))
        lo = round(getattr(it, c) - size / 2)
        setattr(it, s, size)
        setattr(it, c, lo + size / 2)


def ring_radii(doc: Document) -> list:
    """Radii of the major polar-grid rings, center to edge."""
    rings = max(1, int(doc.grid.get("rings") or 1))
    return [doc.radius * k / rings for k in range(1, rings + 1)]


def spoke_angles(doc: Document) -> list:
    """Angles (degrees) of the polar-grid spokes; `spokes` = 0 follows
    the segment count."""
    n = int(doc.grid.get("spokes") or 0) or doc.segments
    a = float(doc.symmetry.get("angle") or 0.0)
    return [a + j * 360.0 / n for j in range(n)]


def _axis_candidates(doc: Document, v: float, axis: str) -> list:
    """Linear snap targets near `v` along `axis` ("x" or "y")."""
    g = doc.grid
    c = doc.center
    out = [0.0, float(doc.size)]
    if g.get("snap_guides"):
        out.append(c)                      # center lines
        if g.get("show_guides", True):
            out += list(doc.guides.get(axis, []))
    return out


def snap_value(doc: Document, v: float, axis: str, threshold: float):
    """(snapped value, True) if a linear target (guide, center, edge) is
    within `threshold`, else (v rounded to a whole unit, False)."""
    best = None
    for c in _axis_candidates(doc, v, axis):
        d = abs(c - v)
        if d <= threshold and (best is None or d < abs(best - v)):
            best = c
    if best is None:
        return float(round(v)), False
    return float(best), True


def snap_span(doc: Document, lo: float, hi: float, axis: str,
              threshold: float) -> float:
    """Offset that snaps the nearest of lo/center/hi to a linear target
    (0 if none is within threshold)."""
    best = None
    for v in (lo, (lo + hi) / 2, hi):
        s, ok = snap_value(doc, v, axis, threshold)
        if ok and (best is None or abs(s - v) < abs(best)):
            best = s - v
    return best or 0.0


def polar_snap(doc: Document, pt: QPointF, threshold: float):
    """Snap `pt` to the polar grid: radius to the nearest ring, angle to
    the nearest spoke. Returns (point, snapped?) — snapping needs the
    grid's "snap" flag; the circle center and rim always count."""
    g = doc.grid
    if not g.get("snap"):
        return pt, False
    c = doc.center
    dx, dy = pt.x() - c, pt.y() - c
    r, ang = math.hypot(dx, dy), math.degrees(math.atan2(dy, dx))
    snapped = False
    # radius -> nearest ring (including center r=0 and rim r=R)
    best_r, best_rd = r, threshold
    for cand in [0.0] + ring_radii(doc):
        d = abs(cand - r)
        if d <= best_rd:
            best_r, best_rd, snapped = cand, d, True
    # angle -> nearest spoke (arc-length distance at this radius)
    best_a, best_ad = ang, threshold
    for a in spoke_angles(doc):
        d = ((a - ang + 180) % 360 - 180)
        arc = abs(d) * math.pi / 180 * max(r, 1.0)
        if arc <= best_ad:
            ang, best_ad, snapped = a, arc, True
    if not snapped:
        return pt, False
    rad = math.radians(ang)
    return QPointF(c + best_r * math.cos(rad),
                   c + best_r * math.sin(rad)), True


def snap_point(doc: Document, pt: QPointF, threshold: float) -> QPointF:
    """Best snap for a point: guides/edges first (per axis), then the
    polar grid, else whole units."""
    x, xok = snap_value(doc, pt.x(), "x", threshold)
    y, yok = snap_value(doc, pt.y(), "y", threshold)
    if xok or yok:
        return QPointF(x, y)
    p, ok = polar_snap(doc, pt, threshold)
    if ok:
        return p
    return QPointF(x, y)
