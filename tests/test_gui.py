import pytest

pytest.importorskip("pytestqt")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QApplication

from mandalawerx.app import MainWindow
from mandalawerx.gui.canvas import Tool
from mandalawerx.core.model import Item, RECT, ELLIPSE


@pytest.fixture(scope="session")
def qapp(qapp):
    return qapp


@pytest.fixture()
def win(qtbot):
    w = MainWindow()
    w._skip_discard_check = True   # qtbot teardown calls close()
    qtbot.addWidget(w)
    return w


def test_window_builds(win):
    assert win.doc.layers and win.canvas is not None
    assert win.seg_spin.value() == win.doc.segments


def test_add_item_selects_and_replicates(win):
    c = win.doc.center
    it = Item(ELLIPSE, cx=c, cy=c - 300, w=80, h=80, fill="#ff0000")
    win.add_item(it)
    assert win.selection == [it.id]
    img = win.canvas.doc_image()
    assert img is not None


def test_segment_spin_updates_doc(win):
    win.seg_spin.setValue(12)
    assert win.doc.segments == 12
    win.undo_stack.undo()
    assert win.doc.segments == 8


def test_mirror_toggle(win):
    win.set_symmetry("mirror", False)
    assert win.doc.symmetry["mirror"] is False
    win.undo_stack.undo()
    assert win.doc.symmetry["mirror"] is True


def test_hit_test_through_copies(win):
    c = win.doc.center
    it = Item(RECT, cx=c, cy=c - 400, w=80, h=80, fill="#ff0000",
              stroke=None)
    win.add_item(it)
    # a copy 2 segments over (90 deg): rotated position
    import math
    a = math.radians(-90 + 2 * win.doc.segment_angle)
    pt = QPointF(c + 400 * math.cos(a), c + 400 * math.sin(a))
    lay, hit, t = win.canvas.item_at(pt)
    assert hit is it and lay is win.doc.layers[0]


def test_layer_symmetry_toggle(win):
    lay = win.doc.layers[0]
    win.set_layer_prop(lay.id, "symmetry", False, "Stop repeating")
    assert lay.symmetry is False
    win.undo_stack.undo()
    assert win.doc.layers[0].symmetry is True   # restore() rebuilds layers


def test_set_canvas_size_scales_items(win):
    it = Item(RECT, cx=500, cy=600, w=100, h=50)
    win.add_item(it)
    win.set_canvas_size(1024)
    assert win.doc.size == 1024
    assert it.w == 50 and it.cx == 250


def test_save_and_load(win, tmp_path):
    win.add_item(Item(RECT, cx=300, cy=400, w=60, h=60))
    p = win.doc.to_dict()
    path = tmp_path / "t.mwpx"
    from mandalawerx.core.project import save_project, load_project
    save_project(win.doc, path)
    back = load_project(path)
    assert back.state() == win.doc.state()
