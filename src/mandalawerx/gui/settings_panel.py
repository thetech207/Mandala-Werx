"""Right-hand settings: Symmetry (segments + polar grid), Item, Document."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QTabWidget, QVBoxLayout, QHBoxLayout,
                               QFormLayout, QGroupBox, QLabel, QComboBox,
                               QSpinBox, QDoubleSpinBox, QCheckBox,
                               QPushButton, QScrollArea, QLineEdit,
                               QToolButton)

from ..core.model import VECTOR, RASTER, IMAGE, SVG, POLYGON, STAR, RECT
from ..core.snap import edge
from ..core import color as colors
from ..core import render
from .widgets import ColorButton, SliderSpin
from .icons import icon


def _scroll(inner: QWidget) -> QScrollArea:
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QScrollArea.Shape.NoFrame)
    sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    sa.setWidget(inner)
    return sa


def _combo(options: dict) -> QComboBox:
    c = QComboBox()
    for k, v in options.items():
        c.addItem(v, k)
    return c


def _dspin(lo, hi, step=1.0, dec=1, suffix="") -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setDecimals(dec)
    if suffix:
        s.setSuffix(suffix)
    s.setKeyboardTracking(False)
    return s


def _spin(lo, hi, suffix="") -> QSpinBox:
    s = QSpinBox()
    s.setRange(lo, hi)
    if suffix:
        s.setSuffix(suffix)
    s.setKeyboardTracking(False)
    return s


def _set_combo(c: QComboBox, data):
    i = c.findData(data)
    if i >= 0:
        c.setCurrentIndex(i)


class _Triple(QWidget):
    """Three spin boxes for 60-30-10 style triples."""

    def __init__(self, maker, labels=("L", "M", "S")):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.spins = []
        for lab in labels:
            s = maker()
            s.setToolTip(lab)
            lay.addWidget(s)
            self.spins.append(s)


class _SwatchButton(QToolButton):
    def __init__(self, color, win):
        super().__init__()
        self.c = color
        self.win = win
        from .icons import swatch_icon
        self.setIcon(swatch_icon(color))
        self.setFixedSize(24, 24)
        self.clicked.connect(self._use)

    def _use(self):
        from PySide6.QtWidgets import QApplication
        stroke = bool(QApplication.keyboardModifiers()
                      & Qt.KeyboardModifier.ShiftModifier)
        self.win.set_current_color(self.c, stroke)


class SettingsPanel(QTabWidget):
    def __init__(self, win, parent=None):
        super().__init__(parent)
        self.win = win
        self._loading = False
        self.addTab(_scroll(self._build_sym_tab()), "Symmetry")
        self.addTab(_scroll(self._build_item_tab()), "Item")
        self.addTab(_scroll(self._build_doc_tab()), "Document")

    # ================================================= symmetry tab
    def _build_sym_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(2, 2, 2, 2)
        v.setSpacing(4)

        # layer props (any layer kind)
        lg = QGroupBox("Layer")
        lf = QFormLayout(lg)
        self.layer_name = QLabel()
        lf.addRow("Active:", self.layer_name)
        self.layer_opacity = SliderSpin(0, 1, 0.01, 2)
        self.layer_opacity.value_changed.connect(
            lambda val: self._layer_prop("opacity", val))
        lf.addRow("Opacity:", self.layer_opacity)
        self.layer_sym = QCheckBox("Repeat in segments")
        self.layer_sym.setToolTip(
            "Copy this layer's items into every mandala segment. Turn it "
            "off for e.g. a centered background image.")
        self.layer_sym.toggled.connect(
            lambda on: self._layer_prop("symmetry", on))
        lf.addRow("", self.layer_sym)
        v.addWidget(lg)

        sg = QGroupBox("Symmetry")
        sf = QFormLayout(sg)
        self.s_segments = _spin(1, 64)
        self.s_segments.setToolTip("Split the circle into this many equal "
                                   "segments; each is a rotated copy")
        self.s_segments.valueChanged.connect(
            lambda val: self._sym_changed("segments", val))
        sf.addRow("Segments:", self.s_segments)
        self.s_mirror = QCheckBox("Mirror each segment")
        self.s_mirror.setToolTip("Reflect a copy inside every wedge, so "
                                 "strokes mirror smoothly across the "
                                 "segment bisector (kaleidoscope)")
        self.s_mirror.toggled.connect(
            lambda on: self._sym_changed("mirror", on))
        sf.addRow("", self.s_mirror)
        self.s_clip = QCheckBox("Clip to active segment")
        self.s_clip.setToolTip(
            "Only the part of each item inside the active (highlighted) "
            "segment is kept — you can draw across segment boundaries, "
            "but just the slice in the active segment registers and is "
            "copied to all the others. Draw a circle around the center "
            "and only its arc in the active segment is kept, repeating "
            "into a full circle.")
        self.s_clip.toggled.connect(
            lambda on: self._sym_changed("clip", on))
        sf.addRow("", self.s_clip)
        self.s_angle = _dspin(-360, 360, 5, 1, "°")
        self.s_angle.setToolTip("Direction of the active segment's center "
                                "line (-90° points it straight up)")
        self.s_angle.valueChanged.connect(
            lambda val: self._sym_changed("angle", val))
        sf.addRow("Rotation:", self.s_angle)
        self.s_highlight = QCheckBox("Highlight active segment")
        self.s_highlight.toggled.connect(
            lambda on: self._sym_changed("highlight", on))
        sf.addRow("", self.s_highlight)
        v.addWidget(sg)

        gg = QGroupBox("Polar grid && guides")
        gfm = QFormLayout(gg)
        self.g_show = QCheckBox("Show grid")
        self.g_show.toggled.connect(lambda on: self._grid_changed("show", on))
        gfm.addRow("", self.g_show)
        self.g_rings = _spin(1, 64)
        self.g_rings.setToolTip("Number of equal rings (radial bands)")
        self.g_rings.valueChanged.connect(
            lambda val: self._grid_changed("rings", val))
        gfm.addRow("Rings:", self.g_rings)
        self.g_sub = _spin(0, 16)
        self.g_sub.setToolTip("Faint rings between the major ones")
        self.g_sub.valueChanged.connect(
            lambda val: self._grid_changed("subdivisions", val))
        gfm.addRow("Subdivisions:", self.g_sub)
        self.g_spokes = _spin(0, 96)
        self.g_spokes.setSpecialValueText("Segments")
        self.g_spokes.setToolTip("Radial grid lines; “Segments” draws one "
                                 "spoke per segment boundary")
        self.g_spokes.valueChanged.connect(
            lambda val: self._grid_changed("spokes", val))
        gfm.addRow("Spokes:", self.g_spokes)
        self.g_color = ColorButton("#4a7ab5")
        self.g_color.color_changed.connect(
            lambda c: self._grid_changed("color", c or "#4a7ab5"))
        gfm.addRow("Color:", self.g_color)
        self.g_snap = QCheckBox("Snap to grid (rings & spokes)")
        self.g_snap.toggled.connect(lambda on: self._grid_changed("snap", on))
        gfm.addRow("", self.g_snap)
        self.g_guides = QCheckBox("Show guides")
        self.g_guides.toggled.connect(
            lambda on: self._grid_changed("show_guides", on))
        gfm.addRow("", self.g_guides)
        self.g_snap_guides = QCheckBox("Snap to guides, center and edges")
        self.g_snap_guides.toggled.connect(
            lambda on: self._grid_changed("snap_guides", on))
        gfm.addRow("", self.g_snap_guides)
        self.g_lock = QCheckBox("Lock guides")
        self.g_lock.toggled.connect(
            lambda on: self._grid_changed("lock_guides", on))
        gfm.addRow("", self.g_lock)
        hint = QLabel("Drag from a ruler to add a straight guide; drag a "
                      "guide off the canvas to remove it.")
        hint.setWordWrap(True)
        gfm.addRow(hint)
        v.addWidget(gg)
        v.addStretch(1)
        return w

    def _layer_prop(self, key, value):
        if self._loading:
            return
        lay = self.win.doc.layer(self.win.active_layer_id)
        if lay is None or getattr(lay, key) == value:
            return
        label = {"opacity": "Layer opacity",
                 "symmetry": "Repeat layer in segments"}[key]
        self.win.set_layer_prop(lay.id, key, value, label, merge=True)

    def _sym_changed(self, key, value):
        if self._loading:
            return
        self.win.set_symmetry(key, value)

    def _grid_changed(self, key, value):
        if self._loading:
            return
        self.win.set_grid_prop(key, value)

    # ===================================================== item tab
    def _build_item_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(2, 2, 2, 2)
        self.item_hint = QLabel("Nothing selected. Use the Select tool, "
                                "or draw a shape.")
        self.item_hint.setWordWrap(True)
        v.addWidget(self.item_hint)
        self.item_box = QWidget()
        iv = QVBoxLayout(self.item_box)
        iv.setContentsMargins(0, 0, 0, 0)

        sg = QGroupBox("Style")
        sf = QFormLayout(sg)
        self.i_fill = ColorButton("#4a7ab5", allow_none=True)
        self.i_fill.color_changed.connect(
            lambda c: self._item_changed("fill", c))
        sf.addRow("Fill:", self.i_fill)
        self.i_stroke = ColorButton("#1c1c1c", allow_none=True, stroke=True)
        self.i_stroke.color_changed.connect(
            lambda c: self._item_changed("stroke", c))
        sf.addRow("Outline:", self.i_stroke)
        self.i_sw = _spin(0, 200)
        self.i_sw.valueChanged.connect(
            lambda val: self._item_changed("stroke_width", float(val)))
        sf.addRow("Outline width:", self.i_sw)
        self.i_op = SliderSpin(0, 1, 0.01, 2)
        self.i_op.value_changed.connect(
            lambda val: self._item_changed("opacity", val))
        sf.addRow("Opacity:", self.i_op)
        iv.addWidget(sg)

        self.geo_group = QGroupBox("Geometry")
        gf = QFormLayout(self.geo_group)
        self.i_geo = {}
        for key, lab, lo, hi, suf, tip in (
                ("left", "X:", -99999, 99999, " px", "Left edge"),
                ("top", "Y:", -99999, 99999, " px", "Top edge"),
                ("w", "Width:", 1, 99999, " px", ""),
                ("h", "Height:", 1, 99999, " px", ""),
                ("rotation", "Rotation:", -360, 360, "°", "")):
            s = _spin(lo, hi, suf)
            if tip:
                s.setToolTip(tip)
            s.valueChanged.connect(
                lambda val, k=key: self._item_changed(k, float(val)))
            gf.addRow(lab, s)
            self.i_geo[key] = s
        self.i_sides = _spin(3, 64)
        self.i_sides.valueChanged.connect(
            lambda val: self._item_changed("sides", val))
        gf.addRow("Sides/points:", self.i_sides)
        self.i_inner = _spin(5, 95, "%")
        self.i_inner.setSingleStep(5)
        self.i_inner.valueChanged.connect(
            lambda val: self._item_changed("inner_ratio", val / 100))
        gf.addRow("Inner ratio:", self.i_inner)
        self.i_radius = _spin(0, 2000, " px")
        self.i_radius.valueChanged.connect(
            lambda val: self._item_changed("corner_radius", float(val)))
        gf.addRow("Corner radius:", self.i_radius)
        iv.addWidget(self.geo_group)

        row = QHBoxLayout()
        for ic, tip, fn in (
                ("flipx", "Flip horizontal",
                 lambda: self.win.flip_selection("x")),
                ("flipy", "Flip vertical",
                 lambda: self.win.flip_selection("y")),
                ("up", "Bring forward", lambda: self.win.arrange(1)),
                ("down", "Send backward", lambda: self.win.arrange(-1)),
                ("duplicate", "Duplicate", lambda: self.win.duplicate()),
                ("delete", "Delete", lambda: self.win.delete_selection())):
            b = QToolButton()
            b.setIcon(icon(ic, 18))
            b.setToolTip(tip)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        iv.addLayout(row)
        pal = QPushButton("Apply 60-30-10 palette to selection")
        pal.setToolTip("Recolor the selected shapes with the document "
                       "palette so color areas split 60/30/10")
        pal.clicked.connect(self.win.apply_palette_to_selection)
        iv.addWidget(pal)
        v.addWidget(self.item_box)
        v.addStretch(1)
        return w

    def _item_changed(self, key, value):
        if self._loading:
            return
        self.win.update_items(key, value)

    def refresh_item(self):
        sel = self.win.selected_items()
        self._loading = True
        try:
            self.item_hint.setVisible(not sel)
            self.item_box.setVisible(bool(sel))
            if not sel:
                return
            it = sel[0]
            if len(sel) > 1:
                self.item_hint.setVisible(True)
                self.item_hint.setText(f"{len(sel)} items selected — "
                                       "edits apply to all.")
            else:
                self.item_hint.setText("Nothing selected. Use the Select "
                                       "tool, or draw a shape.")
            shape = it.kind not in (IMAGE, SVG)
            self.i_fill.setEnabled(shape)
            self.i_stroke.setEnabled(shape)
            self.i_sw.setEnabled(shape)
            self.i_fill.set_color(it.fill)
            self.i_stroke.set_color(it.stroke)
            self.i_sw.setValue(int(round(it.stroke_width)))
            self.i_op.setValue(it.opacity)
            geo = {"left": edge(it, 0), "top": edge(it, 1),
                   "w": it.w, "h": it.h, "rotation": it.rotation}
            for k, s in self.i_geo.items():
                s.setValue(int(round(geo[k])))
            self.i_sides.setValue(it.sides)
            self.i_inner.setValue(int(round(it.inner_ratio * 100)))
            self.i_radius.setValue(int(round(it.corner_radius)))
            form = self.geo_group.layout()
            form.setRowVisible(self.i_sides, it.kind in (POLYGON, STAR))
            form.setRowVisible(self.i_inner, it.kind == STAR)
            form.setRowVisible(self.i_radius, it.kind == RECT)
        finally:
            self._loading = False

    # ================================================= document tab
    def _build_doc_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(2, 2, 2, 2)
        tg = QGroupBox("Canvas")
        tf = QFormLayout(tg)
        self.d_name = QLineEdit()
        self.d_name.editingFinished.connect(
            lambda: self._doc_changed("name", self.d_name.text().strip()
                                      or "Untitled"))
        tf.addRow("Name:", self.d_name)
        size_row = QWidget()
        tr = QHBoxLayout(size_row)
        tr.setContentsMargins(0, 0, 0, 0)
        self.d_size = _spin(64, 8192, " px")
        self.d_size.setSingleStep(64)
        self.d_scale = QCheckBox("Scale content")
        self.d_scale.setChecked(True)
        apply_size = QPushButton("Apply")
        apply_size.clicked.connect(lambda: self.win.set_canvas_size(
            self.d_size.value(), self.d_scale.isChecked()))
        tr.addWidget(self.d_size, 1)
        tr.addWidget(apply_size)
        tf.addRow("Diameter:", size_row)
        tf.addRow("", self.d_scale)
        self.d_bg = ColorButton("#ffffff", allow_none=True)
        self.d_bg.color_changed.connect(
            lambda c: self._doc_changed("background", c))
        tf.addRow("Background:", self.d_bg)
        self.d_bg_none = QCheckBox("Transparent background")
        self.d_bg_none.toggled.connect(
            lambda on: self._doc_changed(
                "background", None if on else (self.d_bg.color()
                                               or "#ffffff")))
        tf.addRow("", self.d_bg_none)
        v.addWidget(tg)

        pg = QGroupBox("Palette (color theory)")
        pf = QFormLayout(pg)
        self.p_harmony = _combo(colors.HARMONIES)
        self.p_harmony.currentIndexChanged.connect(
            lambda _i: self._palette_changed(
                "harmony", self.p_harmony.currentData()))
        pf.addRow("Harmony:", self.p_harmony)
        self.p_base = ColorButton("#2f6f8f")
        self.p_base.color_changed.connect(
            lambda c: self._palette_changed("base_color", c or "#2f6f8f"))
        pf.addRow("Base color:", self.p_base)
        self.p_shares = _Triple(lambda: _spin(0, 100, "%"),
                                ("Dominant", "Secondary", "Accent"))
        for s in self.p_shares.spins:
            s.valueChanged.connect(lambda _v: self._palette_changed(
                "shares", [x.value() / 100 for x in self.p_shares.spins]))
        pf.addRow("60-30-10:", self.p_shares)
        self.p_swatches = QWidget()
        self.p_sw_lay = QHBoxLayout(self.p_swatches)
        self.p_sw_lay.setContentsMargins(0, 0, 0, 0)
        self.p_sw_lay.setSpacing(3)
        pf.addRow("Colors:", self.p_swatches)
        hint = QLabel("Click a swatch to use it as the fill color "
                      "(Shift-click: outline).")
        hint.setWordWrap(True)
        pf.addRow(hint)
        bgbtn = QPushButton("Use dominant color as background")
        bgbtn.clicked.connect(self.win.dominant_to_background)
        pf.addRow(bgbtn)
        v.addWidget(pg)

        vg = QGroupBox("View")
        vf = QFormLayout(vg)
        self.v_dim = QCheckBox("Dim outside the circle")
        self.v_dim.toggled.connect(self.win.set_dim_outside)
        vf.addRow("", self.v_dim)
        self.v_border = QCheckBox("Show circle border")
        self.v_border.toggled.connect(self.win.set_show_border)
        vf.addRow("", self.v_border)
        v.addWidget(vg)
        v.addStretch(1)
        return w

    def _doc_changed(self, key, value):
        if self._loading:
            return
        self.win.set_doc_prop(key, value)

    def _palette_changed(self, key, value):
        if self._loading:
            return
        self.win.set_palette(key, value)

    # ====================================================== refresh
    def refresh(self):
        self.refresh_item()
        self.refresh_doc()
        self.refresh_layer()

    def refresh_layer(self):
        lay = self.win.doc.layer(self.win.active_layer_id)
        self._loading = True
        try:
            self.layer_name.setText(lay.name if lay else "—")
            self.layer_opacity.setEnabled(lay is not None)
            self.layer_sym.setEnabled(lay is not None)
            if lay:
                self.layer_opacity.setValue(lay.opacity)
                self.layer_sym.setChecked(lay.symmetry)
        finally:
            self._loading = False

    def refresh_doc(self):
        doc = self.win.doc
        cv = self.win.canvas
        self._loading = True
        try:
            self.d_name.setText(doc.name)
            self.d_size.setValue(doc.size)
            self.d_bg.set_color(doc.background or self.d_bg.color())
            self.d_bg_none.setChecked(doc.background is None)
            _set_combo(self.p_harmony, doc.palette["harmony"])
            self.p_base.set_color(doc.palette["base_color"])
            for s, x in zip(self.p_shares.spins, doc.palette["shares"]):
                s.setValue(int(round(x * 100)))
            self.v_dim.setChecked(cv.dim_outside)
            self.v_border.setChecked(cv.show_border)
            sym = doc.symmetry
            self.s_segments.setValue(doc.segments)
            self.s_mirror.setChecked(bool(sym.get("mirror")))
            self.s_clip.setChecked(bool(sym.get("clip")))
            self.s_angle.setValue(float(sym.get("angle") or 0))
            self.s_highlight.setChecked(bool(sym.get("highlight", True)))
            g = doc.grid
            self.g_show.setChecked(bool(g["show"]))
            self.g_rings.setValue(int(g["rings"]))
            self.g_sub.setValue(int(g["subdivisions"]))
            self.g_spokes.setValue(int(g["spokes"]))
            self.g_color.set_color(g["color"])
            self.g_snap.setChecked(bool(g["snap"]))
            self.g_guides.setChecked(bool(g["show_guides"]))
            self.g_snap_guides.setChecked(bool(g["snap_guides"]))
            self.g_lock.setChecked(bool(g["lock_guides"]))
            while self.p_sw_lay.count():
                it = self.p_sw_lay.takeAt(0)
                if it.widget():
                    it.widget().deleteLater()
            cols = colors.harmony(doc.palette["base_color"],
                                  doc.palette["harmony"])
            shares = colors.role_shares(cols, doc.palette["shares"])
            for c, sh in zip(cols, shares):
                b = _SwatchButton(c, self.win)
                b.setToolTip(f"{c} — {sh * 100:.0f}%")
                self.p_sw_lay.addWidget(b)
            self.p_sw_lay.addStretch(1)
        finally:
            self._loading = False
