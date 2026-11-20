"""Raster and vector export of the mandala (square or circle-cropped)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from PySide6.QtCore import Qt, QRectF, QSize, QSizeF, QMarginsF
from PySide6.QtGui import (QImage, QPainter, QPainterPath, QBrush, QColor,
                           QImageWriter, QPageSize, QPageLayout)

from .model import Document
from .render import render_document, paint_document

RASTER_FORMATS = {"png": "PNG", "jpg": "JPEG", "tiff": "TIFF",
                  "webp": "WebP", "bmp": "BMP"}
VECTOR_FORMATS = {"svg": "SVG", "pdf": "PDF"}
ALPHA_FORMATS = {"png", "tiff", "webp", "svg", "pdf"}


@dataclass
class ExportSpec:
    px: int = 2048              # output is px x px
    background: bool = True     # False = transparent where supported
    circle: bool = True         # clip artwork to the mandala disc
    quality: int = 92


def compose(doc: Document, spec: ExportSpec) -> QImage:
    img = render_document(doc, spec.px, spec.background,
                          clip_circle=spec.circle)
    if spec.circle:
        # guarantee a clean transparent rim outside the disc
        out = QImage(img.size(), QImage.Format.Format_ARGB32_Premultiplied)
        out.fill(Qt.GlobalColor.transparent)
        p = QPainter(out)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        disc = QPainterPath()
        disc.addEllipse(QRectF(0, 0, out.width(), out.height()))
        p.setClipPath(disc)
        p.drawImage(0, 0, img)
        p.end()
        img = out
    return img


def export_raster(doc: Document, spec: ExportSpec, path) -> Path:
    path = Path(path)
    ext = path.suffix.lower().lstrip(".")
    ext = {"jpeg": "jpg", "tif": "tiff"}.get(ext, ext)
    if ext not in RASTER_FORMATS:
        raise ValueError(f"unsupported image format: .{ext}")
    if ext not in ALPHA_FORMATS:
        spec = replace(spec, background=True)
    img = compose(doc, spec)
    if ext in ("jpg", "bmp"):
        flat = QImage(img.size(), QImage.Format.Format_RGB32)
        flat.fill(QColor(doc.background or "#ffffff"))
        p = QPainter(flat)
        p.drawImage(0, 0, img)
        p.end()
        img = flat
    w = QImageWriter(str(path), {"jpg": b"jpeg"}.get(ext, ext.encode()))
    if ext in ("jpg", "webp"):
        w.setQuality(int(spec.quality))
    if not w.write(img):
        raise IOError(w.errorString())
    return path


def export_vector(doc: Document, spec: ExportSpec, path) -> Path:
    path = Path(path)
    ext = path.suffix.lower().lstrip(".")
    w = h = int(spec.px)

    def paint(p: QPainter):
        p.setClipRect(QRectF(0, 0, w, h))
        p.scale(w / doc.size, h / doc.size)
        paint_document(p, doc, spec.background, clip_circle=spec.circle)

    if ext == "svg":
        from PySide6.QtSvg import QSvgGenerator
        gen = QSvgGenerator()
        gen.setFileName(str(path))
        gen.setSize(QSize(w, h))
        gen.setViewBox(QRectF(0, 0, w, h))
        gen.setTitle(doc.name)
        gen.setDescription("Created with Mandala-Werx")
        p = QPainter(gen)
        paint(p)
        p.end()
    elif ext == "pdf":
        from PySide6.QtGui import QPdfWriter
        pdf = QPdfWriter(str(path))
        pdf.setResolution(96)
        pdf.setPageSize(QPageSize(QSizeF(w * 72 / 96, h * 72 / 96),
                                  QPageSize.Unit.Point, "Mandala"))
        pdf.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Point)
        pdf.setTitle(doc.name)
        p = QPainter(pdf)
        paint(p)
        p.end()
    else:
        raise ValueError(f"unsupported vector format: .{ext}")
    return path


def export(doc: Document, spec: ExportSpec, path) -> Path:
    ext = Path(path).suffix.lower().lstrip(".")
    if ext in VECTOR_FORMATS:
        return export_vector(doc, spec, path)
    return export_raster(doc, spec, path)
