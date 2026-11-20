import math

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QImage, QColor

from mandalawerx.core import color, imageproc, render
from mandalawerx.core.export import ExportSpec, compose, export
from mandalawerx.core.model import (Document, Layer, Item, VECTOR, RASTER,
                                    RECT, ELLIPSE, PATH)
from mandalawerx.core.project import save_project, load_project
from mandalawerx.core.snap import (pixel_snap, snap_value, snap_span,
                                   polar_snap, ring_radii, spoke_angles)


def doc_with(**sym):
    doc = Document()
    doc.symmetry.update(sym)
    return doc


# ---------------------------------------------------------- symmetry
def test_group_transforms_counts():
    doc = doc_with(segments=8, mirror=False)
    assert len(render.group_transforms(doc)) == 8
    doc.symmetry["mirror"] = True
    assert len(render.group_transforms(doc)) == 16
    doc.symmetry["segments"] = 1
    assert len(render.group_transforms(doc)) == 2   # identity + mirror
    doc.symmetry["mirror"] = False
    assert len(render.group_transforms(doc)) == 1


def test_layer_opt_out_gives_single_transform():
    doc = doc_with(segments=8, mirror=True)
    lay = Layer("bg", VECTOR, symmetry=False)
    assert len(render.group_transforms(doc, lay)) == 1


def test_rotation_copy_lands_in_its_wedge():
    doc = doc_with(segments=8, mirror=False, angle=-90)
    c = doc.center
    src = QPointF(c, c - 300)          # straight up, inside wedge 0
    for t, w in render.group_transforms(doc):
        q = t.map(src)
        assert render.wedge_index(doc, q) == w


def test_mirrored_copy_is_mirror_image():
    doc = doc_with(segments=8, mirror=True, angle=-90)
    c = doc.center
    src = QPointF(c + 50, c - 300)
    copies = render.group_transforms(doc)
    # copy for wedge 1, rotated: point should sit in wedge 1
    t1 = copies[1][0]
    assert render.wedge_index(doc, t1.map(src)) == 1
    # a mirrored copy flips handedness: determinant < 0
    mt = copies[8][0]                  # first mirrored transform
    assert mt.m11() * mt.m22() - mt.m12() * mt.m21() < 0


def test_wedge_index():
    doc = doc_with(segments=4, angle=0)
    c = doc.center
    assert render.wedge_index(doc, QPointF(c + 10, c)) == 0       # east
    assert render.wedge_index(doc, QPointF(c, c + 10)) == 1       # south
    assert render.wedge_index(doc, QPointF(c - 10, c)) == 2       # west
    assert render.wedge_index(doc, QPointF(c, c - 10)) == 3       # north


def test_render_replicates_item():
    doc = doc_with(segments=8, mirror=False, angle=-90)
    doc.grid["show"] = False
    c = doc.center
    doc.layers[0].items.append(
        Item(RECT, cx=c, cy=c - 400, w=60, h=60, fill="#ff0000",
             stroke=None))
    img = render.render_document(doc, 512, background=False)
    s = 512 / doc.size
    # the 8 copies sit on a circle of radius 400 around the center
    hits = 0
    for k in range(8):
        a = math.radians(-90 + k * 45)
        x, y = int((c + 400 * math.cos(a)) * s), \
            int((c + 400 * math.sin(a)) * s)
        if img.pixelColor(x, y).alpha() > 128:
            hits += 1
    assert hits == 8


def test_render_clips_to_disc():
    doc = doc_with(segments=1, mirror=False)
    doc.grid["show"] = False
    doc.layers[0].items.append(
        Item(RECT, cx=10, cy=10, w=200, h=200, fill="#ff0000",
             stroke=None))
    img = render.render_document(doc, 256, clip_circle=True)
    # the square corner is outside the disc -> stays transparent
    assert img.pixelColor(1, 1).alpha() == 0


def test_clip_keeps_only_the_active_wedge():
    """Clip mode: only content inside the active wedge (wedge 0, centered
    on `angle`) registers; that slice is then replicated into every
    segment. Content elsewhere is not drawn at all."""
    doc = doc_with(segments=4, mirror=False, angle=0, clip=True)
    doc.grid["show"] = False
    c = doc.center
    s = 512 / doc.size

    def probe(img):
        hits = 0
        for k in range(4):
            a = math.radians(k * 90)
            x = int((c + 400 * math.cos(a)) * s)
            y = int((c + 400 * math.sin(a)) * s)
            if img.pixelColor(x, y).alpha() > 128:
                hits += 1
        return hits

    # item fully inside the active wedge (angle=0 -> wedge 0 spans -45..45)
    doc.layers[0].items.append(
        Item(RECT, cx=c + 400, cy=c, w=60, h=60, fill="#ff0000",
             stroke=None))
    assert probe(render.render_document(doc, 512, background=False)) == 4
    # same item moved entirely into wedge 2 (west): nothing registers
    doc.layers[0].items[0].cx = c - 400
    assert probe(render.render_document(doc, 512, background=False)) == 0


def test_clip_circle_becomes_full_ring():
    """Draw a circle around the whole grid with clip on: only the arc in
    the active segment registers, then repeats into a full circle."""
    doc = doc_with(segments=8, mirror=False, angle=-90, clip=True)
    doc.grid["show"] = False
    c = doc.center
    doc.layers[0].items.append(
        Item(ELLIPSE, cx=c, cy=c, w=1500, h=1500, fill=None,
             stroke="#000000", stroke_width=30))
    img = render.render_document(doc, 512, background=False)
    s = 512 / doc.size
    R = 750 * s
    hits = 0
    for k in range(64):
        a = math.radians(k * 360 / 64)
        x = int(256 + R * math.cos(a))
        y = int(256 + R * math.sin(a))
        if img.pixelColor(x, y).alpha() > 128:
            hits += 1
    assert hits == 64


# ------------------------------------------------------------- snapping
def test_pixel_snap_whole_units():
    it = Item("rect", cx=100.3, cy=50.8, w=40.6, h=21.2, rotation=12.6)
    pixel_snap(it)
    assert (it.w, it.h, it.rotation) == (41, 21, 13)
    assert (it.cx - it.w / 2) == int(it.cx - it.w / 2)


def test_polar_snap_to_ring_and_spoke():
    doc = doc_with(segments=8, angle=-90)
    doc.grid.update(snap=True, rings=8, spokes=0)
    c = doc.center
    R = doc.radius
    # near the 4th ring (r = R/2), near spoke 0 (angle -90, straight up)
    pt = QPointF(c + 3, c - R / 2 - 4)
    out, ok = polar_snap(doc, pt, 20)
    assert ok
    assert out.y() == pytest.approx(c - R / 2, abs=1e-6)
    assert out.x() == pytest.approx(c, abs=1e-6)
    # far off-grid -> no snap
    out, ok = polar_snap(doc, QPointF(c + 100, c - 137), 5)
    assert not ok


def test_snap_point_center_and_edges():
    doc = doc_with()
    c = doc.center
    doc.grid.update(snap=False, snap_guides=True)
    from mandalawerx.core.snap import snap_point
    p = snap_point(doc, QPointF(c + 3, c - 2), 8)
    assert p.x() == c and p.y() == c
    doc.guides["x"] = [300]
    p = snap_point(doc, QPointF(296.0, 700.0), 8)
    assert p.x() == 300.0
    assert snap_span(doc, 294.0, 344.0, "x", 8) == 6.0


def test_spoke_angles_follow_segments():
    doc = doc_with(segments=6, angle=-90)
    assert spoke_angles(doc) == pytest.approx(
        [-90, -30, 30, 90, 150, 210])
    doc.grid["spokes"] = 12
    assert len(spoke_angles(doc)) == 12


def test_ring_radii():
    doc = Document(size=1000)
    doc.grid["rings"] = 4
    assert ring_radii(doc) == pytest.approx([125, 250, 375, 500])


# ------------------------------------------------------------- files
def test_project_roundtrip(tmp_path):
    doc = doc_with(segments=12, mirror=False, angle=30, clip=True)
    doc.layers[0].items.append(Item(RECT, cx=100, cy=200, w=50, h=60))
    img = QImage(8, 8, QImage.Format.Format_ARGB32)
    img.fill(QColor("#00ff00"))
    key = imageproc.add_image_asset(doc, img, "green")
    r = Layer("Raster", RASTER, symmetry=False)
    r.items.append(Item("image", cx=10, cy=10, w=8, h=8, asset=key))
    doc.layers.append(r)
    p = save_project(doc, tmp_path / "design")
    assert p.suffix == ".mwpx"
    back = load_project(p)
    assert back.state() == doc.state()
    assert back.segments == 12 and back.symmetry["clip"] is True
    assert back.layers[1].symmetry is False
    assert key in back.assets


def test_load_rejects_other_formats(tmp_path):
    p = tmp_path / "x.mwpx"
    p.write_text('{"format": "rwpx"}')
    with pytest.raises(Exception):
        load_project(p)


def test_grid_and_guides_roundtrip(tmp_path):
    doc = Document()
    doc.grid.update(show=True, rings=16, spokes=24, snap=True)
    doc.guides = {"x": [100], "y": [200, 300]}
    p = tmp_path / "g.mwpx"
    save_project(doc, p)
    back = load_project(p)
    assert back.grid["rings"] == 16 and back.grid["spokes"] == 24
    assert back.guides == {"x": [100], "y": [200, 300]}


def test_key_out_background():
    img = QImage(20, 20, QImage.Format.Format_ARGB32)
    img.fill(QColor("#ffffff"))
    for x in range(8, 12):
        for y in range(8, 12):
            img.setPixelColor(x, y, QColor("#000000"))
    assert imageproc.detect_background(img) == "#ffffff"
    out = imageproc.key_out(img, "#ffffff", tolerance=10, feather=0)
    assert out.pixelColor(0, 0).alpha() == 0
    assert out.pixelColor(10, 10).alpha() == 255


# ------------------------------------------------------------- export
def test_compose_size():
    doc = doc_with(seed=2) if False else doc_with()
    img = compose(doc, ExportSpec(px=300))
    assert (img.width(), img.height()) == (300, 300)


def test_compose_circle_keeps_corners_transparent():
    doc = doc_with(segments=1)
    doc.layers[0].items.append(
        Item(RECT, cx=0, cy=0, w=400, h=400, fill="#ff0000", stroke=None))
    img = compose(doc, ExportSpec(px=128, circle=True))
    assert img.pixelColor(1, 1).alpha() == 0


@pytest.mark.parametrize("ext", ["png", "jpg", "webp", "svg", "pdf"])
def test_export_formats(tmp_path, ext):
    doc = doc_with()
    p = export(doc, ExportSpec(px=64), tmp_path / f"out.{ext}")
    assert p.exists() and p.stat().st_size > 0


def test_export_does_not_mutate_spec(tmp_path):
    doc = doc_with()
    spec = ExportSpec(px=32, background=False)
    export(doc, spec, tmp_path / "a.jpg")
    assert spec.background is False


def test_default_background_is_white():
    assert Document().background == "#ffffff"


@pytest.mark.parametrize("scheme", list(color.HARMONIES))
def test_harmonies(scheme):
    cols = color.harmony("#4a7ab5", scheme)
    assert len(cols) >= 3
    assert all(c.startswith("#") and len(c) == 7 for c in cols)


def test_assign_roles_approaches_60_30_10():
    roles = color.assign_roles([1.0] * 200, [0.6, 0.3, 0.1])
    counts = [roles.count(i) for i in range(3)]
    assert counts == pytest.approx([120, 60, 20], abs=4)


# --------------------------------------------------------- path utils
def test_pencil_path_roundtrip():
    from mandalawerx.gui.canvas import _smooth_segments, make_path_item
    pts = [QPointF(100, 100), QPointF(150, 120), QPointF(220, 200),
           QPointF(300, 180)]
    segs = _smooth_segments(pts)
    assert segs[0][0] == "M" and all(s[0] == "C" for s in segs[1:])
    it = make_path_item(segs, {"fill": None, "stroke": "#000",
                               "stroke_width": 3})
    assert it.kind == PATH and it.w > 0 and it.segments[0][0] == "M"
