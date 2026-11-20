"""Export dialog with live preview: the mandala as a square or
circle-cropped image, raster (PNG/JPEG/…) or vector (SVG/PDF)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, QSettings, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
                               QLabel, QSpinBox, QCheckBox, QComboBox,
                               QDialogButtonBox, QFileDialog, QMessageBox,
                               QGroupBox)

from ..core import export as exp

FORMATS = [("png", "PNG image"), ("jpg", "JPEG image"),
           ("tiff", "TIFF image"), ("webp", "WebP image"),
           ("bmp", "BMP image"), ("svg", "SVG vector"),
           ("pdf", "PDF document")]
PREVIEW = 360


class ExportDialog(QDialog):
    def __init__(self, doc, settings: QSettings, last_dir: str = "",
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export mandala")
        self.doc = doc
        self.settings = settings
        self.last_dir = last_dir
        self.exported_path = None
        lay = QHBoxLayout(self)

        og = QGroupBox("Options")
        f = QFormLayout(og)
        self.px = QSpinBox()
        self.px.setRange(16, 16384)
        self.px.setSingleStep(256)
        self.px.setSuffix(" px")
        f.addRow("Size:", self.px)
        self.fmt = QComboBox()
        for k, lab in FORMATS:
            self.fmt.addItem(lab, k)
        f.addRow("Format:", self.fmt)
        self.circle = QCheckBox("Crop to the circle")
        self.circle.setToolTip("Clip the artwork to the mandala disc; "
                               "the corners stay transparent")
        f.addRow("", self.circle)
        self.transparent = QCheckBox("Transparent background")
        f.addRow("", self.transparent)
        self.quality = QSpinBox()
        self.quality.setRange(10, 100)
        f.addRow("Quality:", self.quality)
        left = QVBoxLayout()
        left.addWidget(og)
        left.addStretch(1)
        lay.addLayout(left)
        self._form = f
        self.px.valueChanged.connect(self._changed)
        self.fmt.currentIndexChanged.connect(self._changed)
        for w in (self.circle, self.transparent):
            w.toggled.connect(self._changed)
        self.quality.valueChanged.connect(self._changed)

        right = QVBoxLayout()
        self.preview = QLabel()
        self.preview.setFixedSize(PREVIEW, PREVIEW)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet("background:#808080; border-radius:6px;")
        right.addWidget(self.preview)
        self.info = QLabel()
        right.addWidget(self.info)
        right.addStretch(1)
        bb = QDialogButtonBox()
        self.export_btn = bb.addButton(
            "Export…", QDialogButtonBox.ButtonRole.AcceptRole)
        bb.addButton(QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._export)
        bb.rejected.connect(self.reject)
        right.addWidget(bb)
        lay.addLayout(right)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self._update_preview)
        self._load()
        self._changed()

    # -------------------------------------------------------------
    def _load(self):
        s = self.settings
        self.px.setValue(int(s.value("export/px", self.doc.size)))
        i = self.fmt.findData(s.value("export/format", "png"))
        self.fmt.setCurrentIndex(max(0, i))
        self.circle.setChecked(s.value("export/circle", "true") == "true")
        self.transparent.setChecked(
            s.value("export/transparent", "false") == "true")
        self.quality.setValue(int(s.value("export/quality", 92)))

    def _save(self):
        s = self.settings
        sp = self.spec()
        s.setValue("export/px", int(sp.px))
        s.setValue("export/format", self.fmt.currentData())
        s.setValue("export/circle", "true" if sp.circle else "false")
        s.setValue("export/transparent",
                   "true" if self.transparent.isChecked() else "false")
        s.setValue("export/quality", sp.quality)

    def spec(self) -> exp.ExportSpec:
        fmt = self.fmt.currentData()
        return exp.ExportSpec(
            px=self.px.value(),
            background=not (self.transparent.isChecked()
                            and fmt in exp.ALPHA_FORMATS),
            circle=self.circle.isChecked(),
            quality=self.quality.value())

    def _changed(self, *_):
        sp = self.spec()
        f = self._form
        fmt = self.fmt.currentData()
        f.setRowVisible(self.transparent, fmt in exp.ALPHA_FORMATS)
        f.setRowVisible(self.quality, fmt in ("jpg", "webp"))
        self.info.setText(f"Output: <b>{sp.px} × {sp.px}</b> px")
        self._timer.start()

    def _update_preview(self):
        sp = self.spec()
        k = min(1.0, PREVIEW / sp.px)
        small = replace(sp, px=max(2, int(sp.px * k)))
        img = exp.compose(self.doc, small)
        self.preview.setPixmap(QPixmap.fromImage(img))

    def _export(self):
        fmt = self.fmt.currentData()
        label = dict(FORMATS)[fmt]
        start = str(Path(self.last_dir or Path.home())
                    / f"{self.doc.name}.{fmt}")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export mandala", start, f"{label} (*.{fmt})")
        if not path:
            return
        if not path.lower().endswith(f".{fmt}") and not (
                fmt in ("jpg", "tiff")
                and path.lower().endswith((".jpeg", ".tif"))):
            path += f".{fmt}"
        try:
            exp.export(self.doc, self.spec(), path)
        except Exception as e:      # noqa: BLE001 - surface any failure
            QMessageBox.critical(self, "Export failed", str(e))
            return
        self._save()
        self.exported_path = path
        self.accept()
