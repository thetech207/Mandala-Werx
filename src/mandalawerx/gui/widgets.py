"""Small shared widgets."""

from __future__ import annotations

from PySide6.QtCore import Signal, Qt, QObject, QEvent
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QToolButton, QColorDialog, QMenu, QWidget,
                               QHBoxLayout, QSlider, QDoubleSpinBox,
                               QAbstractSpinBox, QComboBox, QAbstractSlider,
                               QAbstractScrollArea, QApplication)

from .icons import swatch_icon


class ColorButton(QToolButton):
    """Swatch button; click opens a color dialog. Optional 'None'."""
    color_changed = Signal(object)     # str | None

    def __init__(self, color: str | None = "#000000", allow_none=False,
                 stroke=False, parent=None):
        super().__init__(parent)
        self._color = color
        self._allow_none = allow_none
        self._stroke = stroke
        self.setAutoRaise(False)
        self.clicked.connect(self._pick)
        if allow_none:
            self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.customContextMenuRequested.connect(self._menu)
        self._refresh()

    def color(self):
        return self._color

    def set_color(self, c, emit=False):
        self._color = c
        self._refresh()
        if emit:
            self.color_changed.emit(c)

    def _refresh(self):
        self.setIcon(swatch_icon(self._color, stroke=self._stroke))
        tip = self._color or "None"
        if self._allow_none:
            tip += "  (right-click for None)"
        self.setToolTip(tip)

    def _menu(self, pos):
        m = QMenu(self)
        m.addAction("Choose color…", self._pick)
        m.addAction("None", lambda: self.set_color(None, emit=True))
        m.exec(self.mapToGlobal(pos))

    def _pick(self):
        start = QColor(self._color or "#ffffff")
        c = QColorDialog.getColor(start, self, "Choose color")
        if c.isValid():
            self.set_color(c.name(), emit=True)


class SliderSpin(QWidget):
    """Slider + spin box bound to the same float value."""
    value_changed = Signal(float)

    def __init__(self, lo, hi, step=0.01, decimals=2, parent=None):
        super().__init__(parent)
        self._scale = 1 / step
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(int(lo * self._scale), int(hi * self._scale))
        self.spin = QDoubleSpinBox()
        self.spin.setRange(lo, hi)
        self.spin.setSingleStep(step)
        self.spin.setDecimals(decimals)
        self.spin.setFixedWidth(70)
        self.spin.setKeyboardTracking(False)
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.spin)
        self.slider.valueChanged.connect(self._from_slider)
        self.spin.valueChanged.connect(self._from_spin)

    def _from_slider(self, v):
        val = v / self._scale
        self.spin.blockSignals(True)
        self.spin.setValue(val)
        self.spin.blockSignals(False)
        self.value_changed.emit(val)

    def _from_spin(self, v):
        self.slider.blockSignals(True)
        self.slider.setValue(int(round(v * self._scale)))
        self.slider.blockSignals(False)
        self.value_changed.emit(v)

    def value(self) -> float:
        return self.spin.value()

    def setValue(self, v: float):
        self.blockSignals(True)
        self.spin.blockSignals(True)
        self.slider.blockSignals(True)
        self.spin.setValue(v)
        self.slider.setValue(int(round(v * self._scale)))
        self.spin.blockSignals(False)
        self.slider.blockSignals(False)
        self.blockSignals(False)


_WHEEL_TYPES = (QAbstractSpinBox, QComboBox, QAbstractSlider)


class WheelGuard(QObject):
    """App-wide filter: spin boxes, combos and sliders only react to the
    mouse wheel while they have keyboard focus, and the wheel never gives
    them focus. Otherwise the wheel scrolls the enclosing panel."""

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.Type.Polish and isinstance(obj, _WHEEL_TYPES):
            if obj.focusPolicy() == Qt.FocusPolicy.WheelFocus:
                obj.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        elif t == QEvent.Type.Wheel and isinstance(obj, QWidget):
            w = obj
            while w is not None and not isinstance(w, _WHEEL_TYPES):
                if isinstance(w, QAbstractScrollArea):
                    return False      # e.g. a combo's popup list
                w = w.parentWidget()
            if w is None or w.hasFocus() or (
                    w.focusProxy() is not None and w.focusProxy().hasFocus()):
                return False
            if isinstance(w, QAbstractScrollArea):
                return False
            area = w.parentWidget()
            while area is not None and not isinstance(area,
                                                      QAbstractScrollArea):
                area = area.parentWidget()
            if area is not None:
                bar = area.verticalScrollBar()
                if ev.angleDelta().y() == 0 or not bar.isVisible():
                    bar = area.horizontalScrollBar() \
                        if ev.angleDelta().x() else bar
                delta = ev.angleDelta().y() or ev.angleDelta().x()
                lines = QApplication.wheelScrollLines()
                bar.setValue(bar.value() - round(
                    delta / 120 * lines * bar.singleStep()))
            return True
        return False


_guard = None


def install_wheel_guard():
    global _guard
    app = QApplication.instance()
    if app is not None and _guard is None:
        _guard = WheelGuard(app)
        app.installEventFilter(_guard)
