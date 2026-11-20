"""Mandala-Werx main window."""

from __future__ import annotations

import random
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QSize, QSettings, QPoint, QEvent, QTimer, QRect
from PySide6.QtGui import (QAction, QActionGroup, QKeySequence, QIcon,
                           QPixmap, QPainter, QColor, QUndoStack)
from PySide6.QtWidgets import (QApplication, QMainWindow, QToolBar,
                               QDockWidget, QWidget, QVBoxLayout, QSplitter,
                               QLabel, QFileDialog, QMessageBox, QToolButton,
                               QSpinBox, QUndoView, QDialog,
                               QTextBrowser, QSplashScreen,
                               QDialogButtonBox, QGridLayout)

from . import __version__, __author__
from .core.model import (Document, Layer, Item, VECTOR, RASTER,
                         IMAGE, SVG, ELLIPSE, STAR, SHAPE_KINDS, PATH,
                         new_id)
from .core import project as project_io
from .core import render, imageproc
from .core import color as colors
from .core.snap import pixel_snap, edge
from .gui import theme
from .gui.canvas import MandalaCanvas, Tool
from .gui.commands import SnapshotCommand
from .gui.icons import icon
from .gui.layers_panel import LayersPanel
from .gui.settings_panel import SettingsPanel
from .gui.widgets import ColorButton, install_wheel_guard
from .gui.rulers import Ruler

TOOL_TIPS = [
    (Tool.SELECT, "select", "Select / move / scale / rotate  (V)", "V"),
    (Tool.RECT, "rect", "Rectangle — Shift: square, Alt: from center  (R)",
     "R"),
    (Tool.ELLIPSE, "ellipse", "Ellipse — Shift: circle, Alt: from center  "
     "(E)", "E"),
    (Tool.POLYGON, "polygon", "Regular polygon  (G)", "G"),
    (Tool.STAR, "star", "Star  (S)", "S"),
    (Tool.LINE, "line", "Line — Shift snaps to 45°  (L)", "L"),
    (Tool.PEN, "pen", "Pen — click for corners, drag for curves, click the "
     "first point to close, double-click/Enter to finish  (P)", "P"),
    (Tool.PENCIL, "pencil", "Pencil — freehand smooth stroke  (D)", "D"),
    (Tool.EYEDROPPER, "eyedropper", "Eyedropper — click: fill, "
     "Shift-click: outline  (I)", "I"),
    (Tool.PAN, "pan", "Pan — or hold Space / middle mouse  (H)", "H"),
]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.resize(1360, 860)
        self._settings = QSettings("MandalaWerx", "MandalaWerx")
        theme.apply_theme(self._settings.value("ui/theme", "system"))
        self.doc = Document()
        self.active_layer_id = self.doc.layers[-1].id
        self.selection: list[str] = []
        self.undo_stack = QUndoStack(self)
        self.undo_stack.cleanChanged.connect(self._on_clean_changed)
        self._edit_before = None
        self._clip: list = []
        self._clip_assets: dict = {}
        self._file_path: str | None = None
        self._style = {
            "fill": self._settings.value("style/fill", "#4a7ab5"),
            "stroke": self._settings.value("style/stroke", "#1c1c1c"),
            "stroke_width": float(round(float(
                self._settings.value("style/width", 2.0)))),
        }
        if self._style["fill"] == "none":
            self._style["fill"] = None
        if self._style["stroke"] == "none":
            self._style["stroke"] = None
        self.setAcceptDrops(True)
        install_wheel_guard()
        self._build_ui()
        self._build_menus()
        self.changed()

    # ============================================================ UI
    def _build_ui(self):
        self.canvas = MandalaCanvas(self)
        central = QWidget()
        grid = QGridLayout(central)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)
        self.ruler_corner = QWidget()
        self.ruler_corner.setFixedSize(22, 22)
        self.ruler_top = Ruler(self.canvas, True)
        self.ruler_left = Ruler(self.canvas, False)
        self.canvas.rulers = [self.ruler_top, self.ruler_left]
        grid.addWidget(self.ruler_corner, 0, 0)
        grid.addWidget(self.ruler_top, 0, 1)
        grid.addWidget(self.ruler_left, 1, 0)
        grid.addWidget(self.canvas, 1, 1)
        self.setCentralWidget(central)
        self._set_rulers_visible(
            self._settings.value("view/rulers", "true") == "true")
        self.canvas.color_picked.connect(self.set_current_color)
        self.canvas.tool_changed.connect(self._on_tool_changed)
        self.canvas.zoom_changed.connect(
            lambda z: self.zoom_label.setText(f"{z * 100:.0f}%"))
        self.canvas.dim_outside = \
            self._settings.value("view/dim", "true") == "true"
        self.canvas.show_border = \
            self._settings.value("view/border", "true") == "true"

        # left tools
        tb = QToolBar("Tools")
        tb.setObjectName("Tools")
        tb.setIconSize(QSize(26, 26))
        tb.setMovable(False)
        self._tools_bar = tb
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, tb)
        self.tool_actions = {}
        grp = QActionGroup(self)
        for tool, ic, tip, key in TOOL_TIPS:
            a = QAction(icon(ic), tip, self)
            a.setCheckable(True)
            a.setShortcut(QKeySequence(key))
            a.triggered.connect(lambda _=False, t=tool: self.canvas.set_tool(t))
            grp.addAction(a)
            tb.addAction(a)
            self.tool_actions[tool] = a
        self.tool_actions[Tool.SELECT].setChecked(True)
        tb.addSeparator()
        self.fill_btn = ColorButton(self._style["fill"], allow_none=True)
        self.fill_btn.setToolTip("Fill color (right-click for none)")
        self.fill_btn.color_changed.connect(
            lambda c: self._set_style("fill", c))
        self.stroke_btn = ColorButton(self._style["stroke"], allow_none=True,
                                      stroke=True)
        self.stroke_btn.color_changed.connect(
            lambda c: self._set_style("stroke", c))
        for b in (self.fill_btn, self.stroke_btn):
            b.setIconSize(QSize(24, 24))
            tb.addWidget(b)

        # top options bar
        ob = QToolBar("Options")
        ob.setObjectName("Options")
        ob.setMovable(False)
        ob.setIconSize(QSize(20, 20))
        self._opts_bar = ob
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, ob)
        ob.addWidget(QLabel("Outline"))
        self.sw_spin = QSpinBox()
        self.sw_spin.setRange(0, 200)
        self.sw_spin.setValue(int(self._style["stroke_width"]))
        self.sw_spin.valueChanged.connect(
            lambda v: self._set_style("stroke_width", float(v)))
        ob.addWidget(self.sw_spin)
        ob.addSeparator()
        ob.addWidget(QLabel("Segments"))
        self.seg_spin = QSpinBox()
        self.seg_spin.setRange(1, 64)
        self.seg_spin.setValue(self.doc.segments)
        self.seg_spin.setToolTip("Number of mandala segments")
        self.seg_spin.valueChanged.connect(
            lambda v: self.set_symmetry("segments", v))
        ob.addWidget(self.seg_spin)
        a = ob.addAction(icon("mandala"), "Mirror each segment")
        a.setCheckable(True)
        a.setChecked(bool(self.doc.symmetry.get("mirror")))
        a.toggled.connect(lambda on: self.set_symmetry("mirror", on))
        self.mirror_act = a
        ob.addSeparator()
        ob.addWidget(QLabel("Sides"))
        self.sides_spin = QSpinBox()
        self.sides_spin.setRange(3, 64)
        self.sides_spin.setValue(int(self._settings.value("shape/sides", 6)))
        ob.addWidget(self.sides_spin)
        ob.addWidget(QLabel("Points"))
        self.points_spin = QSpinBox()
        self.points_spin.setRange(3, 64)
        self.points_spin.setValue(int(self._settings.value("shape/points",
                                                           5)))
        ob.addWidget(self.points_spin)
        ob.addWidget(QLabel("Inner"))
        self.inner_spin = QSpinBox()
        self.inner_spin.setRange(5, 95)
        self.inner_spin.setSingleStep(5)
        self.inner_spin.setSuffix("%")
        inner = float(self._settings.value("shape/inner", 0.45))
        if inner > 1:        # saved as a percentage by an earlier build
            inner /= 100
        self.inner_spin.setValue(int(round(100 * inner)))
        ob.addWidget(self.inner_spin)
        ob.addWidget(QLabel("Corner"))
        self.radius_spin = QSpinBox()
        self.radius_spin.setRange(0, 1000)
        ob.addWidget(self.radius_spin)
        ob.addSeparator()
        for ic, tip, fn in (("import", "Import image or SVG…",
                             self.import_file),
                            ("export", "Export…", self.export)):
            a = ob.addAction(icon(ic), tip)
            a.triggered.connect(fn)
        ob.addSeparator()
        a = ob.addAction(icon("mandala"), "Fit the mandala")
        a.triggered.connect(self.canvas.fit)
        self.zoom_label = QLabel("100%")
        ob.addWidget(self.zoom_label)

        # right dock: layers + settings
        right = QWidget()
        right.setObjectName("SidePanel")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(6, 6, 6, 6)
        self.layers_panel = LayersPanel(self)
        self.settings_panel = SettingsPanel(self)
        self.right_splitter = QSplitter(Qt.Orientation.Vertical)
        self.right_splitter.setChildrenCollapsible(False)
        self.right_splitter.addWidget(self.layers_panel)
        self.right_splitter.addWidget(self.settings_panel)
        self.right_splitter.setStretchFactor(0, 0)
        self.right_splitter.setStretchFactor(1, 1)
        self.right_splitter.setSizes([230, 600])
        rl.addWidget(self.right_splitter)
        self._side_panel = right
        dock = QDockWidget("Layers && Settings", self)
        dock.setObjectName("SideDock")
        dock.setWidget(right)
        dock.setMinimumWidth(330)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable
                         | QDockWidget.DockWidgetFeature.DockWidgetFloatable
                         | QDockWidget.DockWidgetFeature.DockWidgetClosable)
        self.right_dock = dock
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)

        self.undo_view = QUndoView(self.undo_stack)
        hd = QDockWidget("History", self)
        hd.setObjectName("HistoryDock")
        hd.setWidget(self.undo_view)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, hd)
        hd.hide()
        self.history_dock = hd

        # collapse tab on the dock's left edge (as in Black-Werx)
        self.panel_tab = QToolButton(self)
        self.panel_tab.setFixedSize(12, 72)
        self.panel_tab.setCursor(Qt.CursorShape.PointingHandCursor)
        self.panel_tab.setToolTip("Collapse/expand the side panel")
        self.panel_tab.clicked.connect(self._toggle_right_panel)
        self.canvas.installEventFilter(self)

        self.status_coords = QLabel("")
        self.status_info = QLabel("")
        self.statusBar().addWidget(self.status_coords)
        self.statusBar().addPermanentWidget(self.status_info)
        self._apply_styles()
        geo = self._settings.value("ui/geometry")
        if geo:
            self.restoreGeometry(geo)
        st = self._settings.value("ui/state")
        if st:
            self.restoreState(st)
        QTimer.singleShot(0, self._position_panel_tab)

    def _apply_styles(self):
        self._tools_bar.setStyleSheet(theme.bar_qss("Tools", "right"))
        self._opts_bar.setStyleSheet(theme.bar_qss("Options", "bottom"))
        self._side_panel.setStyleSheet(theme.side_panel_qss())
        self.panel_tab.setStyleSheet(theme.panel_tab_qss())
        icons = {t: ic for t, ic, _tip, _k in TOOL_TIPS}
        for tool, a in self.tool_actions.items():
            a.setIcon(icon(icons[tool]))

    def _set_theme(self, mode):
        self._settings.setValue("ui/theme", mode)
        for m, a in self._theme_acts.items():
            a.setChecked(m == mode)
        theme.apply_theme(mode)
        self._apply_styles()
        self.layers_panel.refresh()
        self.canvas.update()

    def _toggle_right_panel(self):
        self.right_dock.setVisible(not self.right_dock.isVisible())
        QTimer.singleShot(0, self._position_panel_tab)

    def _position_panel_tab(self):
        tab = self.panel_tab
        cv = self.canvas
        right = cv.mapTo(self, QPoint(cv.width(), 0)).x()
        top = cv.mapTo(self, QPoint(0, 0)).y()
        tab.move(right - tab.width(),
                 top + max(0, (cv.height() - tab.height()) // 2))
        tab.setText("❯" if self.right_dock.isVisible() else "❮")
        tab.raise_()

    def eventFilter(self, obj, ev):
        if obj is self.canvas and ev.type() == QEvent.Type.Resize:
            self._position_panel_tab()
        return super().eventFilter(obj, ev)

    def _build_menus(self):
        mb = self.menuBar()
        m = mb.addMenu("&File")
        self._act(m, "&New", self.new_project, QKeySequence.StandardKey.New)
        self._act(m, "&Open…", self.open_project,
                  QKeySequence.StandardKey.Open)
        self.recent_menu = m.addMenu("Open &Recent")
        self._refresh_recent()
        self._act(m, "&Save", self.save_project,
                  QKeySequence.StandardKey.Save)
        self._act(m, "Save &As…", self.save_project_as,
                  QKeySequence.StandardKey.SaveAs)
        m.addSeparator()
        self._act(m, "&Import Image / SVG…", self.import_file, "Ctrl+I")
        self._act(m, "Re&load Imported Files", self.reload_all_assets,
                  "Ctrl+Shift+R")
        self._act(m, "&Export…", self.export, "Ctrl+E")
        m.addSeparator()
        self._act(m, "&Quit", self.close, QKeySequence.StandardKey.Quit)

        m = mb.addMenu("&Edit")
        u = self.undo_stack.createUndoAction(self, "&Undo")
        u.setShortcut(QKeySequence.StandardKey.Undo)
        r = self.undo_stack.createRedoAction(self, "&Redo")
        r.setShortcut(QKeySequence.StandardKey.Redo)
        m.addAction(u)
        m.addAction(r)
        m.addSeparator()
        self._act(m, "Cu&t", self.cut, QKeySequence.StandardKey.Cut)
        self._act(m, "&Copy", self.copy, QKeySequence.StandardKey.Copy)
        self._act(m, "&Paste", self.paste, QKeySequence.StandardKey.Paste)
        self._act(m, "&Duplicate", self.duplicate, "Ctrl+D")
        self._act(m, "De&lete", self.delete_selection)
        m.addSeparator()
        self._act(m, "Select &All", self.select_all,
                  QKeySequence.StandardKey.SelectAll)
        self._act(m, "Deselect", lambda: self.set_selection([]),
                  "Ctrl+Shift+A")

        m = mb.addMenu("&Arrange")
        self._act(m, "Bring to Front", lambda: self.arrange(999),
                  "Ctrl+Shift+]")
        self._act(m, "Bring Forward", lambda: self.arrange(1), "Ctrl+]")
        self._act(m, "Send Backward", lambda: self.arrange(-1), "Ctrl+[")
        self._act(m, "Send to Back", lambda: self.arrange(-999),
                  "Ctrl+Shift+[")
        m.addSeparator()
        self._act(m, "Flip Horizontal", lambda: self.flip_selection("x"))
        self._act(m, "Flip Vertical", lambda: self.flip_selection("y"))

        m = mb.addMenu("&Symmetry")
        self._act(m, "More segments", lambda: self.bump_segments(1),
                  "]")
        self._act(m, "Fewer segments", lambda: self.bump_segments(-1),
                  "[")
        a = self._act(m, "Mirror each segment",
                      lambda on: self.set_symmetry("mirror", on))
        a.setCheckable(True)
        self.mirror_menu_act = a
        a = self._act(m, "Clip to active segment",
                      lambda on: self.set_symmetry("clip", on))
        a.setCheckable(True)
        self.clip_menu_act = a
        a = self._act(m, "Highlight active segment",
                      lambda on: self.set_symmetry("highlight", on))
        a.setCheckable(True)
        self.highlight_menu_act = a

        m = mb.addMenu("&Layer")
        self._act(m, "New Vector Layer", lambda: self.add_layer(VECTOR),
                  "Ctrl+Shift+N")
        self._act(m, "New Raster Layer", lambda: self.add_layer(RASTER))
        m.addSeparator()
        self._act(m, "Duplicate Layer",
                  lambda: self.duplicate_layer(self.active_layer_id))
        self._act(m, "Merge Down",
                  lambda: self.merge_down(self.active_layer_id), "Ctrl+M")
        self._act(m, "Convert to Raster",
                  lambda: self.convert_to_raster(self.active_layer_id))
        self._act(m, "Delete Layer",
                  lambda: self.delete_layer(self.active_layer_id))

        m = mb.addMenu("&View")
        self._act(m, "Fit Mandala", self.canvas.fit, "Ctrl+0")
        self._act(m, "Zoom In", lambda: self.canvas.zoom_by(1.25),
                  QKeySequence.StandardKey.ZoomIn)
        self._act(m, "Zoom Out", lambda: self.canvas.zoom_by(0.8),
                  QKeySequence.StandardKey.ZoomOut)
        m.addSeparator()
        a = self._act(m, "Show &Rulers",
                      lambda on: self._set_rulers_visible(on), "Ctrl+R")
        a.setCheckable(True)
        a.setChecked(self.ruler_top.isVisible()
                     or self._settings.value("view/rulers", "true") == "true")
        self.rulers_act = a
        self.view_acts = {}

        def toggle(text, key, shortcut, fn):
            a = self._act(m, text, lambda on: fn(key, on), shortcut)
            a.setCheckable(True)
            self.view_acts[key] = a
            return a
        toggle("Show &Grid", "show", "Ctrl+'", self.set_grid_prop)
        toggle("&Snap to Grid", "snap", "Ctrl+Shift+'", self.set_grid_prop)
        toggle("Show G&uides", "show_guides", "Ctrl+;", self.set_grid_prop)
        toggle("Snap to Guides && Edges", "snap_guides",
               "Ctrl+Shift+;", self.set_grid_prop)
        toggle("&Lock Guides", "lock_guides", "Ctrl+Alt+;",
               self.set_grid_prop)
        self._act(m, "Clear Guides", self.clear_guides)
        m.addSeparator()
        tm = m.addMenu("&Theme")
        self._theme_acts = {}
        cur = self._settings.value("ui/theme", "system")
        for mode, lab in (("system", "System"), ("light", "Light"),
                          ("dark", "Dark")):
            a = tm.addAction(lab)
            a.setCheckable(True)
            a.setChecked(mode == cur)
            a.triggered.connect(lambda _=False, md=mode: self._set_theme(md))
            self._theme_acts[mode] = a
        m.addAction(self.history_dock.toggleViewAction())
        m.addAction(self.right_dock.toggleViewAction())

        m = mb.addMenu("&Help")
        self._act(m, "User Guide", self.user_guide, "F1")
        self._act(m, "About Mandala-Werx", self.about)

    def _act(self, menu, text, fn, shortcut=None):
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        a.triggered.connect(fn)
        menu.addAction(a)
        return a

    # ====================================================== state
    def changed(self):
        lids = {l.id for l in self.doc.layers}
        if self.active_layer_id not in lids:
            self.active_layer_id = self.doc.layers[-1].id \
                if self.doc.layers else None
        lay = self.doc.layer(self.active_layer_id)
        valid = {i.id for i in lay.items} if lay else set()
        self.selection = [i for i in self.selection if i in valid]
        self.canvas.invalidate()
        self.layers_panel.refresh()
        self.settings_panel.refresh()
        self._update_title()
        self._update_status()
        for k, a in getattr(self, "view_acts", {}).items():
            a.setChecked(bool(self.doc.grid.get(k)))
        if hasattr(self, "seg_spin"):
            self.seg_spin.blockSignals(True)
            self.seg_spin.setValue(self.doc.segments)
            self.seg_spin.blockSignals(False)
        if hasattr(self, "mirror_act"):
            self.mirror_act.setChecked(bool(self.doc.symmetry.get("mirror")))
        for attr, key in (("mirror_menu_act", "mirror"),
                          ("clip_menu_act", "clip"),
                          ("highlight_menu_act", "highlight")):
            if hasattr(self, attr):
                getattr(self, attr).setChecked(
                    bool(self.doc.symmetry.get(key)))

    def _on_clean_changed(self, _clean):
        try:
            self._update_title()
        except RuntimeError:
            pass

    def _update_title(self):
        name = Path(self._file_path).name if self._file_path else \
            self.doc.name
        dirty = "" if self.undo_stack.isClean() else " *"
        self.setWindowTitle(f"{name}{dirty} — Mandala-Werx")

    def _update_status(self):
        n = sum(len(l.items) for l in self.doc.layers)
        self.status_info.setText(
            f"⌀ {self.doc.size} · {self.doc.segments} segments · "
            f"{len(self.doc.layers)} layers · {n} items · "
            f"{len(self.selection)} selected")

    def show_coords(self, pt):
        r, ang = render.polar(self.doc, pt)
        self.status_coords.setText(
            f"x {pt.x():.0f}  y {pt.y():.0f}   r {r:.0f}  θ {ang:.0f}°")

    def restore_state(self, state, sel):
        self.doc.restore(state)
        self.selection = list(sel)
        self.changed()

    def _push(self, label, before, sel_before, merge_key=None):
        after = self.doc.state()
        if after == before:
            return False
        self.undo_stack.push(SnapshotCommand(
            self, label, before, after, sel_before, list(self.selection),
            merge_key))
        self.changed()
        return True

    def commit(self, label, fn, merge_key=None):
        before = self.doc.state()
        sel = list(self.selection)
        fn()
        return self._push(label, before, sel, merge_key)

    def begin_edit(self):
        self._edit_before = (self.doc.state(), list(self.selection))

    def end_edit(self, label):
        if self._edit_before is None:
            return
        before, sel = self._edit_before
        self._edit_before = None
        if not self._push(label, before, sel):
            self.changed()

    def cancel_edit(self):
        self._edit_before = None

    # ================================================== selection
    def selected_items(self):
        lay = self.doc.layer(self.active_layer_id)
        if not lay or lay.locked:
            return []
        ids = set(self.selection)
        return [it for it in lay.items if it.id in ids]

    def set_selection(self, ids):
        self.selection = list(ids)
        self.settings_panel.refresh_item()
        if ids:
            self.settings_panel.setCurrentIndex(1)
        self._update_status()
        self.canvas.update()

    def set_active_layer(self, lid, keep_selection=False):
        if lid == self.active_layer_id:
            return
        self.active_layer_id = lid
        if not keep_selection:
            self.selection = []
        self.layers_panel.refresh()
        self.settings_panel.refresh()
        self._update_status()
        self.canvas.update()

    def focus_item_settings(self):
        self.right_dock.show()
        self.settings_panel.setCurrentIndex(1)

    def select_all(self):
        lay = self.doc.layer(self.active_layer_id)
        if lay and not lay.locked:
            self.set_selection([i.id for i in lay.items])

    # ===================================================== styles
    def current_style(self):
        return dict(self._style)

    def shape_options(self):
        return {"sides": self.sides_spin.value(),
                "points": self.points_spin.value(),
                "inner_ratio": self.inner_spin.value() / 100,
                "corner_radius": float(self.radius_spin.value())}

    def _set_style(self, key, value):
        self._style[key] = value
        self._settings.setValue(
            {"fill": "style/fill", "stroke": "style/stroke",
             "stroke_width": "style/width"}[key],
            "none" if value is None else value)
        if self.selection:
            self.update_items(key, value)

    def set_current_color(self, color, stroke=False):
        if stroke:
            self.stroke_btn.set_color(color)
            self._set_style("stroke", color)
        else:
            self.fill_btn.set_color(color)
            self._set_style("fill", color)

    def _on_tool_changed(self, tool):
        a = self.tool_actions.get(tool)
        if a and not a.isChecked():
            a.setChecked(True)

    # ====================================================== items
    def _target_layer(self, kind):
        """Active layer if it accepts `kind` items, else a new layer."""
        want = RASTER if kind == IMAGE else VECTOR
        lay = self.doc.layer(self.active_layer_id)
        if lay and lay.kind == want and not lay.locked:
            return lay
        new = Layer(self.doc.unique_layer_name(
            "Raster" if want == RASTER else "Vector"), want)
        idx = self.doc.layer_index(self.active_layer_id)
        self.doc.layers.insert(idx + 1 if idx >= 0 else len(self.doc.layers),
                               new)
        self.active_layer_id = new.id
        return new

    def add_item(self, it: Item, label=None):
        def fn():
            lay = self._target_layer(it.kind)
            pixel_snap(it)
            lay.items.append(it)
            self.selection = [it.id]
        self.commit(label or f"Add {it.kind}", fn)
        self.settings_panel.setCurrentIndex(1)

    def update_items(self, key, value):
        sel = self.selected_items()
        if not sel:
            return
        lid = self.active_layer_id

        def fn():
            if key in ("left", "top"):
                c = "cx" if key == "left" else "cy"
                d = value - edge(sel[0], 0 if key == "left" else 1)
                for it in sel:
                    setattr(it, c, getattr(it, c) + d)
                    pixel_snap(it)
                return
            if key in ("cx", "cy") and len(sel) > 1:
                d = value - getattr(sel[0], key)
                for it in sel:
                    setattr(it, key, getattr(it, key) + d)
                    pixel_snap(it)
                return
            if key in ("w", "h"):
                c = "cx" if key == "w" else "cy"
                for it in sel:
                    lo = getattr(it, c) - getattr(it, key) / 2
                    setattr(it, key, float(value))
                    setattr(it, c, lo + value / 2)
                    pixel_snap(it)
                return
            for it in sel:
                if key in ("fill", "stroke", "stroke_width") \
                        and it.kind in (IMAGE, SVG):
                    continue
                if key == "fill" and it.kind not in SHAPE_KINDS:
                    continue
                setattr(it, key, value)
                if key in ("cx", "cy", "rotation"):
                    pixel_snap(it)
        self.commit(f"Change {key}", fn,
                    merge_key=f"item:{key}:{lid}:{','.join(self.selection)}")

    def delete_selection(self):
        if not self.selected_items():
            return
        ids = set(self.selection)

        def fn():
            lay = self.doc.layer(self.active_layer_id)
            lay.items = [i for i in lay.items if i.id not in ids]
            self.selection = []
        self.commit("Delete", fn)

    def nudge(self, dx, dy):
        def fn():
            for it in self.selected_items():
                it.cx += dx
                it.cy += dy
        self.commit("Nudge", fn, merge_key="nudge:" + ",".join(
            self.selection))

    def flip_selection(self, axis):
        def fn():
            for it in self.selected_items():
                if axis == "x":
                    it.flip_x = not it.flip_x
                else:
                    it.flip_y = not it.flip_y
        self.commit("Flip", fn)

    def arrange(self, delta):
        lay = self.doc.layer(self.active_layer_id)
        if not lay or not self.selection:
            return
        ids = set(self.selection)

        def fn():
            items = lay.items
            sel = [i for i in items if i.id in ids]
            rest = [i for i in items if i.id not in ids]
            if delta >= 999:
                lay.items = rest + sel
            elif delta <= -999:
                lay.items = sel + rest
            else:
                order = list(items)
                rng = range(len(order) - 2, -1, -1) if delta > 0 \
                    else range(1, len(order))
                for i in rng:
                    j = i + (1 if delta > 0 else -1)
                    if order[i].id in ids and order[j].id not in ids:
                        order[i], order[j] = order[j], order[i]
                lay.items = order
        self.commit("Arrange", fn)

    def copy(self):
        sel = self.selected_items()
        if sel:
            self._clip = [i.to_dict() for i in sel]
            self._clip_assets = {i.asset: self.doc.assets[i.asset]
                                 for i in sel if i.asset in self.doc.assets}

    def cut(self):
        self.copy()
        self.delete_selection()

    def paste(self, offset=20):
        if not self._clip:
            return
        items = [Item.from_dict(d).clone() for d in self._clip]

        def fn():
            self.doc.assets.update(self._clip_assets)
            lay = self._target_layer(items[0].kind)
            for it in items:
                it.cx += offset
                it.cy += offset
                lay.items.append(it)
            self.selection = [i.id for i in items]
        self.commit("Paste", fn)

    def duplicate(self):
        self.copy()
        self.paste(offset=0)

    def apply_palette_to_selection(self):
        sel = [i for i in self.selected_items() if i.kind in SHAPE_KINDS]
        if not sel:
            return
        pal = self.doc.palette
        cols = colors.harmony(pal["base_color"], pal["harmony"])
        shares = colors.role_shares(cols, pal["shares"])

        def area(it):
            t = it.clone()
            s = max(t.w, t.h, 1e-6)
            t.w, t.h = t.w / s, t.h / s
            p = render.item_path(t)
            r = p.boundingRect()
            return max(r.width() * r.height(), 1e-6) * s * s

        def fn():
            order = list(range(len(sel)))
            random.Random(len(sel)).shuffle(order)
            roles = colors.assign_roles([area(i) for i in sel], shares, order)
            for it, r in zip(sel, roles):
                if render.is_closed(it):
                    it.fill = cols[r]
                else:
                    it.stroke = cols[r]
        self.commit("Apply palette", fn)

    # ===================================================== layers
    def add_layer(self, kind):
        base = "Vector" if kind == VECTOR else "Raster"
        lay = Layer(self.doc.unique_layer_name(base), kind)

        def fn():
            idx = self.doc.layer_index(self.active_layer_id)
            self.doc.layers.insert(idx + 1 if idx >= 0
                                   else len(self.doc.layers), lay)
            self.active_layer_id = lay.id
            self.selection = []
        self.commit(f"New {base.lower()} layer", fn)
        self.settings_panel.setCurrentIndex(0)

    def delete_layer(self, lid):
        if self.doc.layer(lid) is None:
            return

        def fn():
            idx = self.doc.layer_index(lid)
            self.doc.layers.pop(idx)
            if not self.doc.layers:
                self.doc.layers.append(Layer("Layer 1", VECTOR))
            self.active_layer_id = self.doc.layers[max(0, idx - 1)].id
            self.selection = []
        self.commit("Delete layer", fn)

    def duplicate_layer(self, lid):
        src = self.doc.layer(lid)
        if src is None:
            return

        def fn():
            d = src.to_dict()
            d["id"] = new_id()
            d["name"] = f"{src.name} copy"
            for it in d["items"]:
                it["id"] = new_id()
            lay = Layer.from_dict(d)
            self.doc.layers.insert(self.doc.layer_index(lid) + 1, lay)
            self.active_layer_id = lay.id
            self.selection = []
        self.commit("Duplicate layer", fn)

    def move_layer(self, lid, delta):
        i = self.doc.layer_index(lid)
        j = i + delta
        if i < 0 or not 0 <= j < len(self.doc.layers):
            return

        def fn():
            L = self.doc.layers
            L[i], L[j] = L[j], L[i]
        self.commit("Reorder layers", fn)

    def reorder_layers(self, ids):
        by_id = {l.id: l for l in self.doc.layers}
        if set(ids) != set(by_id):
            self.layers_panel.refresh()
            return
        self.commit("Reorder layers",
                    lambda: setattr(self.doc, "layers",
                                    [by_id[i] for i in ids]))

    def set_layer_prop(self, lid, key, value, label, merge=False):
        lay = self.doc.layer(lid)
        if lay is None:
            return
        self.commit(label, lambda: setattr(lay, key, value),
                    merge_key=f"layer:{lid}:{key}" if merge else None)

    def toggle_layer_lock(self, lid):
        lay = self.doc.layer(lid)
        if lay:
            self.set_layer_prop(lid, "locked", not lay.locked,
                                "Unlock layer" if lay.locked
                                else "Lock layer")
            if lay.locked:
                self.selection = []

    def _rasterize(self, lay) -> Item:
        S = self.doc.size
        px = int(min(4096, S * 2))
        img = render.render_layer_image(self.doc, lay, px)
        key = imageproc.add_image_asset(self.doc, img, lay.name)
        return Item(IMAGE, cx=S / 2, cy=S / 2, w=S, h=S, fill=None,
                    stroke=None, stroke_width=0, asset=key)

    def convert_to_raster(self, lid):
        lay = self.doc.layer(lid)
        if lay is None or lay.kind == RASTER:
            return

        def fn():
            out = Layer(lay.name, RASTER, visible=lay.visible, id=lay.id,
                        symmetry=False)
            out.items = [self._rasterize(lay)]
            self.doc.layers[self.doc.layer_index(lid)] = out
            self.active_layer_id = out.id
            self.selection = []
        self.commit("Convert to raster", fn)

    def merge_down(self, lid):
        i = self.doc.layer_index(lid)
        if i <= 0:
            self.statusBar().showMessage("No layer below to merge into",
                                         3000)
            return
        upper, lower = self.doc.layers[i], self.doc.layers[i - 1]
        if upper.visible != lower.visible:
            QMessageBox.information(
                self, "Merge down",
                f"“{upper.name}” and “{lower.name}” differ in visibility.\n"
                "Show or hide both layers before merging.")
            return
        if upper.kind == RASTER and lower.kind == VECTOR:
            r = QMessageBox.question(
                self, "Merge down",
                f"“{upper.name}” is a raster layer and “{lower.name}” is "
                "vector.\nConvert the result to a raster layer?")
            if r != QMessageBox.StandardButton.Yes:
                return

        def faded(layer, factor):
            out = []
            for it in layer.items:
                c = it.clone()
                c.opacity = c.opacity * factor
                out.append(c)
            return out

        def fn():
            up, lo = upper, lower
            if up.kind == lo.kind and up.opacity == lo.opacity:
                items = faded(lo, 1.0) + faded(up, 1.0)
                opacity = lo.opacity
            elif up.kind == lo.kind:
                items = faded(lo, lo.opacity) + faded(up, up.opacity)
                opacity = 1.0
            elif lo.kind == RASTER:
                items = faded(lo, lo.opacity) + [self._rasterize(up)]
                opacity = 1.0
            else:
                items = [self._rasterize(lo)] + faded(up, up.opacity)
                opacity = 1.0
            kind = lo.kind if up.kind == lo.kind else RASTER
            result = Layer(lower.name, kind, visible=lower.visible,
                           locked=lower.locked, opacity=opacity,
                           items=items, id=lower.id,
                           symmetry=lower.symmetry and upper.symmetry)
            self.doc.layers[i - 1] = result
            self.doc.layers.pop(i)
            self.active_layer_id = result.id
            self.selection = []
        self.commit("Merge down", fn)

    # ================================================== document
    def set_doc_prop(self, key, value):
        self.commit(f"Document {key}",
                    lambda: setattr(self.doc, key, value),
                    merge_key=f"doc:{key}")

    def set_palette(self, key, value):
        def fn():
            pal = dict(self.doc.palette)
            pal[key] = value
            self.doc.palette = pal
        self.commit("Palette", fn, merge_key=f"palette:{key}")

    def dominant_to_background(self):
        pal = self.doc.palette
        tint = colors.rotate(pal["base_color"], 0, 0.38, -0.25)
        self.set_doc_prop("background", tint)

    def set_symmetry(self, key, value):
        if self.doc.symmetry.get(key) == value:
            return
        self.commit(f"Symmetry {key}",
                    lambda: self.doc.symmetry.__setitem__(key, value),
                    merge_key=f"sym:{key}")

    def bump_segments(self, delta):
        self.set_symmetry("segments",
                          max(1, min(64, self.doc.segments + delta)))

    def set_canvas_size(self, size, scale_content=True):
        old = self.doc.size
        if size == old:
            return
        f = size / old

        def fn():
            self.doc.size = int(size)
            if not scale_content:
                return
            for lay in self.doc.layers:
                for it in lay.items:
                    it.cx *= f
                    it.cy *= f
                    it.w *= f
                    it.h *= f
                    it.stroke_width *= f
                    it.corner_radius *= f
        self.commit("Canvas size", fn)
        self.canvas.fit()

    def set_dim_outside(self, on):
        self.canvas.dim_outside = bool(on)
        self._settings.setValue("view/dim", "true" if on else "false")
        self.canvas.update()

    def set_show_border(self, on):
        self.canvas.show_border = bool(on)
        self._settings.setValue("view/border", "true" if on else "false")
        self.canvas.update()

    # ===================================================== files
    def _last_dir(self) -> Path:
        d = self._settings.value("io/last_dir", "")
        return Path(d) if d and Path(d).is_dir() else Path.home()

    def _confirm_discard(self) -> bool:
        if self.undo_stack.isClean():
            return True
        r = QMessageBox.question(
            self, "Unsaved changes", "Save changes to the current mandala?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel)
        if r == QMessageBox.StandardButton.Save:
            return self.save_project()
        return r == QMessageBox.StandardButton.Discard

    def _set_document(self, doc, path=None):
        self.doc = doc
        self.active_layer_id = doc.layers[-1].id
        self.selection = []
        self._file_path = path
        self.undo_stack.clear()
        self.undo_stack.setClean()
        self.changed()
        self.canvas.fit()

    def new_project(self):
        if self._confirm_discard():
            self._set_document(Document())

    def open_project(self):
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open mandala", str(self._last_dir()),
            "Mandala-Werx design (*.mwpx)")
        if path:
            self.load_path(path)

    def load_path(self, path):
        try:
            doc = project_io.load_project(path)
        except Exception as e:     # noqa: BLE001
            QMessageBox.critical(self, "Open mandala", str(e))
            return
        self._set_document(doc, path)
        self._add_recent(path)

    def save_project(self) -> bool:
        if not self._file_path:
            return self.save_project_as()
        project_io.save_project(self.doc, self._file_path)
        self.undo_stack.setClean()
        self._update_title()
        self.statusBar().showMessage(f"Saved {self._file_path}", 3000)
        return True

    def save_project_as(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save mandala", str(self._last_dir() /
                                      f"{self.doc.name}.mwpx"),
            "Mandala-Werx design (*.mwpx)")
        if not path:
            return False
        p = project_io.save_project(self.doc, path)
        self._file_path = str(p)
        self._settings.setValue("io/last_dir", str(p.parent))
        self._add_recent(str(p))
        self.undo_stack.setClean()
        self._update_title()
        return True

    def _recent(self):
        v = self._settings.value("io/recent", [])
        return [v] if isinstance(v, str) else list(v or [])

    def _add_recent(self, path):
        r = [path] + [p for p in self._recent() if p != path]
        self._settings.setValue("io/recent", r[:10])
        self._refresh_recent()

    def _refresh_recent(self):
        self.recent_menu.clear()
        for p in self._recent():
            self.recent_menu.addAction(
                p, lambda _=False, path=p: self._confirm_discard()
                and self.load_path(path))
        self.recent_menu.setEnabled(bool(self._recent()))

    def import_file(self, path=None):
        if not path:
            filt = imageproc.raster_filter().replace(
                "Images (", "Images and SVG (*.svg ")
            path, _ = QFileDialog.getOpenFileName(
                self, "Import image or SVG", str(self._last_dir()),
                f"{filt};;SVG (*.svg);;{imageproc.raster_filter()}")
        if not path:
            return
        self._settings.setValue("io/last_dir", str(Path(path).parent))
        S = self.doc.size
        name = Path(path).stem
        if path.lower().endswith(".svg"):
            try:
                text = Path(path).read_text(encoding="utf-8")
                key, w, h = imageproc.add_svg_asset(self.doc, text, name)
            except Exception as e:     # noqa: BLE001
                QMessageBox.critical(self, "Import SVG", str(e))
                return
            self.doc.assets[key]["path"] = str(Path(path).resolve())
            s = S * 0.5 / max(w, h, 1)
            self.add_item(Item(SVG, cx=S / 2, cy=S / 2, w=w * s, h=h * s,
                               fill=None, stroke=None, stroke_width=0,
                               asset=key), "Import SVG")
            return
        act = self.doc.layer(self.active_layer_id)
        try:
            dlg = ImageImportDialogProxy(path, bool(
                act and act.kind == RASTER and not act.locked), self)
        except Exception as e:     # noqa: BLE001
            QMessageBox.critical(self, "Import image", str(e))
            return
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        img = dlg.result_image()
        key = imageproc.add_image_asset(self.doc, img, name)
        self.doc.assets[key]["path"] = str(Path(path).resolve())
        self.doc.assets[key]["keying"] = dlg.keying()
        s = S * dlg.size_fraction() / max(img.width(), img.height(), 1)
        it = Item(IMAGE, cx=S / 2, cy=S / 2, w=img.width() * s,
                  h=img.height() * s, fill=None, stroke=None,
                  stroke_width=0, asset=key)
        if dlg.target_mode() == "new":
            def fn():
                lay = Layer(name or self.doc.unique_layer_name("Raster"),
                            RASTER, items=[it])
                idx = self.doc.layer_index(self.active_layer_id)
                self.doc.layers.insert(idx + 1, lay)
                self.active_layer_id = lay.id
                self.selection = [it.id]
            self.commit("Import image", fn)
        else:
            self.add_item(it, "Import image")

    # ---------------------------------------------------- reloading
    def reload_all_assets(self):
        used = [k for k in self.doc.used_assets() if k in self.doc.assets]
        if not used:
            self.statusBar().showMessage("No imported files to reload", 3000)
            return
        self.reload_assets(used)

    def _asset_source(self, key):
        a = self.doc.assets.get(key) or {}
        path = a.get("path")
        if path and Path(path).is_file():
            return path
        name = a.get("name") or key
        ext = "*.svg" if a.get("type") == "svg" else \
            imageproc.raster_filter()
        start = str(Path(path).parent) if path else str(self._last_dir())
        QMessageBox.information(
            self, "Reload", f"The source file for “{name}” was not found"
            + (f":\n{path}" if path else ".") + "\nPlease locate it.")
        filt = f"SVG ({ext})" if a.get("type") == "svg" else ext
        found, _ = QFileDialog.getOpenFileName(self, f"Locate {name}",
                                               start, filt)
        return found or None

    def _load_asset(self, old_key, path):
        a = self.doc.assets[old_key]
        name = a.get("name", "")
        if a.get("type") == "svg":
            text = Path(path).read_text(encoding="utf-8")
            key, w, h = imageproc.add_svg_asset(self.doc, text, name)
        else:
            img = imageproc.load_image(path)
            k = a.get("keying")
            if k:
                col = imageproc.detect_background(img) if k.get("auto") \
                    else k.get("color")
                img = imageproc.key_out(img, col, k.get("tolerance", 40),
                                        k.get("feather", 20),
                                        k.get("contiguous", True))
            key = imageproc.add_image_asset(self.doc, img, name)
            w, h = img.width(), img.height()
        new = self.doc.assets[key]
        new["path"] = str(Path(path).resolve())
        if a.get("keying"):
            new["keying"] = dict(a["keying"])
        return key, w, h

    def reload_assets(self, keys):
        """Re-read imported SVG/raster files from disk and swap them into
        every item that uses them (size and position are kept)."""
        swaps = {}
        for key in dict.fromkeys(keys):
            if key not in self.doc.assets:
                continue
            path = self._asset_source(key)
            if not path:
                continue
            try:
                swaps[key] = self._load_asset(key, path)
            except Exception as e:     # noqa: BLE001
                QMessageBox.critical(self, "Reload", str(e))
        if not swaps:
            return

        def fn():
            for lay in self.doc.layers:
                for it in lay.items:
                    if it.asset not in swaps:
                        continue
                    key, w, h = swaps[it.asset]
                    old = self.doc.assets.get(it.asset, {})
                    ow, oh = old.get("w") or w, old.get("h") or h
                    it.asset = key
                    if w and h and abs(w / h - ow / max(oh, 1)) > 1e-3:
                        it.h = it.w * h / w
                    pixel_snap(it)
            for old, (key, _w, _h) in swaps.items():
                if old != key:
                    render._svg_cache.pop(old, None)
                    render._image_cache.pop(old, None)
        if self.commit("Reload imported file", fn):
            self.statusBar().showMessage(
                f"Reloaded {len(swaps)} file(s)", 3000)
        else:
            self.statusBar().showMessage("Imported files are unchanged",
                                         3000)

    # ------------------------------------------------ grid and guides
    def set_grid_prop(self, key, value):
        if self.doc.grid.get(key) == value:
            return
        self.commit("Grid settings",
                    lambda: self.doc.grid.__setitem__(key, value),
                    merge_key=f"grid:{key}")

    def delete_guide(self, axis, index):
        self.commit("Delete guide",
                    lambda: self.doc.guides[axis].pop(index))

    def clear_guides(self):
        def fn():
            self.doc.guides["x"] = []
            self.doc.guides["y"] = []
        self.commit("Clear guides", fn)

    def _set_rulers_visible(self, on):
        on = bool(on)
        self._settings.setValue("view/rulers", "true" if on else "false")
        for w in (self.ruler_top, self.ruler_left, self.ruler_corner):
            w.setVisible(on)
        if hasattr(self, "rulers_act"):
            self.rulers_act.setChecked(on)

    def export(self):
        from .gui.export_dialog import ExportDialog
        dlg = ExportDialog(self.doc, self._settings, str(self._last_dir()),
                           self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.exported_path:
            self.statusBar().showMessage(f"Exported {dlg.exported_path}",
                                         5000)

    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        for url in ev.mimeData().urls():
            p = url.toLocalFile()
            if p.lower().endswith(".mwpx"):
                if self._confirm_discard():
                    self.load_path(p)
                return
            if p:
                self.import_file(p)

    def closeEvent(self, ev):
        if not getattr(self, "_skip_discard_check", False) \
                and not self._confirm_discard():
            ev.ignore()
            return
        self._settings.setValue("ui/geometry", self.saveGeometry())
        self._settings.setValue("ui/state", self.saveState())
        self._settings.setValue("shape/sides", self.sides_spin.value())
        self._settings.setValue("shape/points", self.points_spin.value())
        self._settings.setValue("shape/inner",
                                self.inner_spin.value() / 100)
        super().closeEvent(ev)

    # ====================================================== help
    def user_guide(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Mandala-Werx User Guide")
        dlg.resize(640, 640)
        lay = QVBoxLayout(dlg)
        tb = QTextBrowser()
        tb.setHtml(USER_GUIDE)
        lay.addWidget(tb)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        dlg.exec()

    def about(self):
        QMessageBox.about(
            self, "About Mandala-Werx",
            f"<h3>Mandala-Werx {__version__}</h3>"
            "<p>Circular mandala illustration on a customizable polar "
            "grid: draw once in the active segment and every stroke is "
            "rotated — optionally mirrored — into the rest of the "
            "circle.</p>"
            f"<p>© {__author__}</p>")


def ImageImportDialogProxy(path, can_use_active, parent):
    from .gui.import_dialog import ImageImportDialog
    return ImageImportDialog(path, can_use_active, parent)


USER_GUIDE = """
<h2>Mandala-Werx</h2>
<p>Draw inside a <b>circular workspace</b> split into equal segments.
Everything you draw is copied and rotated into every other segment, so
a single stroke becomes a full mandala. Turn on <b>Mirror each
segment</b> for a reflected copy inside every wedge (a kaleidoscope),
or <b>Clip to segment</b> to confine drawing to the active wedge —
strokes then stop cleanly at the segment edges.</p>
<h3>Tools (left)</h3>
<ul>
<li><b>Select (V)</b> — click any copy of an item (Shift-click adds, or
drag a box). Drag to move, corner/edge handles to scale (Shift keeps
proportions), round handle to rotate (Shift snaps 15°). Arrow keys
nudge 1 px, Shift+arrow 5 px. Grabbing a rotated or mirrored copy moves
its source correctly.</li>
<li><b>Rectangle, Ellipse, Polygon, Star</b> — drag to draw. Shift
constrains, Alt draws from the center, and starting the drag on the
mandala's center always draws centered on it (the mandala-friendly
way to make a concentric circle). A single click makes a
default-size shape. Sides, points, inner ratio and corner radius are on
the top bar.</li>
<li><b>Line</b>, <b>Pen</b> and <b>Pencil</b> — pen: click for corners,
drag for curves, click the first point to close, double-click or Enter
to finish. Pencil draws a smooth freehand stroke. Previews show every
symmetry copy while you draw.</li>
<li><b>Eyedropper</b> — sample a color (Shift for outline).</li>
<li>The two swatches set fill and outline (right-click for none).</li>
</ul>
<h3>Symmetry &amp; the polar grid</h3>
<p><b>Segments</b> (top bar or Symmetry tab) sets the wedge count,
<b>Rotation</b> spins the wedge frame, and each layer can opt out with
<i>Repeat in segments</i> — handy for a centered background. The
<b>polar grid</b> draws rings and spokes; set spokes to “Segments” to
line up with the wedge boundaries, or pick any count. <b>Snap to
grid</b> snaps the radius to rings and the angle to spokes.
<b>Rulers</b> (Ctrl+R) measure pixels from the canvas corner with a
center mark; drag from a ruler to pull out a straight guide, drag a
guide to move it, or drag it off the canvas to delete it. Drawing and
moving snap to guides, the center and the circle edge.</p>
<h3>Layers</h3>
<p><b>Vector</b> layers hold shapes, paths and SVGs; <b>Raster</b>
layers hold images. Drag to reorder; the checkbox shows/hides;
double-click renames. <b>Merge down</b> joins same-type layers
directly; a vector merged into a raster is rasterized, and
raster-into-vector converts the result to raster. <b>Convert to
raster</b> bakes a layer (with its symmetry) into a single image.</p>
<h3>Import</h3>
<p>SVG imports as vector. Raster images (PNG, JPEG, WebP, TIFF, BMP,
GIF…) open a dialog where the background is auto-detected or picked by
clicking, then made transparent with tolerance and soft edge.
<b>Edit an imported file elsewhere, then right-click it → Reload from
File</b> (or File → Reload Imported Files, Ctrl+Shift+R) to pick up the
changes; size, position and background removal are kept.</p>
<h3>Files &amp; export</h3>
<p><b>.mwpx</b> designs keep everything editable (images embedded).
Export the mandala square or circle-cropped (transparent corners) as
PNG, JPEG, TIFF, WebP, BMP, SVG or PDF.</p>
"""


# ================================================================ startup
def _asset(name: str):
    here = Path(__file__).resolve()
    for d in (here.parents[2] / "Images", here.parents[1] / "Images",
              Path(sys.executable).resolve().parent / "Images"):
        if (d / name).exists():
            return d / name
    return None


def _demo_doc() -> Document:
    """A small generated mandala for the splash screen."""
    doc = Document(size=640, background="#f4f1ea")
    doc.symmetry.update({"segments": 12, "mirror": True, "angle": -90.0})
    doc.grid["show"] = False
    lay = doc.layers[0]
    c = doc.center
    rng = random.Random(7)
    cols = ["#3d6fb4", "#d08a1e", "#5b8a3a", "#c8433a"]
    for k in range(9):
        r = 70 + k * 24
        it = Item(ELLIPSE, cx=c, cy=c - r, w=10 + rng.random() * 26,
                  h=26 + rng.random() * 40,
                  rotation=0, fill=cols[k % len(cols)], stroke=None,
                  opacity=0.85)
        lay.items.append(it)
    star = Item(STAR, cx=c, cy=c, w=120, h=120, sides=8, inner_ratio=0.55,
                fill="#d08a1e", stroke="#1c1c1c", stroke_width=2,
                opacity=0.9)
    lay.items.append(star)
    return doc


def _splash_pixmap() -> QPixmap:
    from .core.render import render_document
    img = render_document(_demo_doc(), 640)
    pm = QPixmap.fromImage(img)
    canvas = QPixmap(640, 380)
    canvas.fill(QColor("#2e2b27"))
    p = QPainter(canvas)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.drawImage(190, 30, img.scaled(320, 320,
                                    Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode
                                    .SmoothTransformation))
    p.end()
    pm = canvas
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    panel = QRect(90, 120, 460, 140)
    p.setBrush(QColor(30, 28, 25, 215))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(panel, 18, 18)
    f = p.font()
    f.setPointSize(30)
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor("#ffffff"))
    p.drawText(panel.adjusted(0, 18, 0, -50), Qt.AlignmentFlag.AlignCenter,
               "Mandala-Werx")
    f.setPointSize(11)
    f.setBold(False)
    p.setFont(f)
    p.setPen(QColor("#d9d4c8"))
    p.drawText(panel.adjusted(0, 80, 0, -10), Qt.AlignmentFlag.AlignCenter,
               f"v{__version__}  ·  {__author__}")
    p.end()
    return pm


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Mandala-Werx")
    app.setDesktopFileName("mandalawerx")
    src = _asset("mandalawerx-icon-1024.png") \
        or _asset("mandalawerx-icon.svg")
    if src is not None:
        app.setWindowIcon(QIcon(str(src)))
    splash = QSplashScreen(_splash_pixmap())
    splash.show()
    app.processEvents()
    win = MainWindow()

    def reveal():
        splash.finish(win)
        win.show()
    QTimer.singleShot(1800, reveal)
    if len(sys.argv) > 1 and Path(sys.argv[1]).is_file():
        QTimer.singleShot(0, lambda: win.load_path(sys.argv[1]))
    sys.exit(app.exec())
