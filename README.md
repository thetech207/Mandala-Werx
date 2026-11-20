# Mandala-Werx

Circular mandala illustration tool built on **live rotational symmetry**:
a round workspace on a customizable polar grid, split into any number of
equal segments. Draw in the active segment and every stroke is copied and
rotated into all the others — like a kaleidoscope you can edit.

Sibling project to [Repeat-Werx](https://github.com/thetech207/Repeat-Werx)
and [Black-Werx](https://github.com/thetech207/Black-Werx).

## Features

- **Circular workspace**: a polar grid of concentric rings and radial
  spokes divides the canvas into N equal wedge segments (1–64). Drawing
  in the active wedge is replicated into every other wedge in real time.
- **Symmetry modes**: plain rotation, or *mirror each segment* so each
  wedge also contains a reflected copy (kaleidoscope). *Clip to segment*
  confines drawing to the active wedge — strokes stop cleanly at the
  boundaries. Each layer can opt out of repetition entirely (e.g. for a
  centered background). The wedge frame can be rotated to any angle.
- **Full vector tool suite**: select/move/scale/rotate, rectangle,
  ellipse, polygon, star, line, pen (Bézier), pencil (freehand smooth
  strokes) and eyedropper — with fill, outline, width, opacity,
  corner radius, and flip.
- **Import**: SVG stays vector. PNG, JPEG, WebP, TIFF, BMP, GIF and other
  raster formats import with automatic or click-picked background
  removal, tolerance and soft-edge controls. Right-click an imported
  item → *Reload from File* to pick up edits made in another program.
- **Polar grid & snapping**: configurable ring count and spoke count
  (or "spokes = segment count"), snap-to-grid on radius and angle,
  straight guides pulled from pixel rulers, center/edge/guide snapping.
- **Layers**: vector and raster layers. Reorder by dragging, show/hide,
  lock, opacity, duplicate, merge down, convert to raster (bakes
  symmetry into a single image).
- **Files & export**: `.mwpx` project files keep everything editable
  (images embedded). Export the mandala square or circle-cropped
  (transparent corners) as PNG, JPEG, TIFF, WebP, BMP, SVG or PDF.
- **Undo/redo** on everything, with a history panel.

## Getting started

```sh
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/mandalawerx
```

Requires Python ≥ 3.10 and a Qt6-capable display (X11/Wayland).

### Quick tour

1. Set the **Segments** count on the top bar (e.g. 12) — the polar grid
   updates live. Enable *Mirror each segment* for a kaleidoscope.
2. Pick a tool (pencil `D`, pen `P`, ellipse `E`, …) and draw anywhere.
   Your stroke appears in every segment as you draw.
3. Turn on *Snap to Grid* (`Ctrl+Shift+'`) to snap radii to rings and
   angles to spokes.
4. Export via File → Export (`Ctrl+E`); enable *Crop to the circle* for
   a round sticker-style image with transparent corners.

## Tests

```sh
.venv/bin/pip install -e '.[dev]'
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
```

## Packaging

- Linux `.deb`: `pyinstaller packaging/mandalawerx.spec` then
  `packaging/build-deb.sh <version>`
- Windows installer: `packaging\build-windows.ps1 <version>`
  (requires Inno Setup 6)

## Project layout

```
src/mandalawerx/
├── app.py               main window, menus, undo wiring
├── core/                GUI-independent logic
│   ├── model.py         document, layers, items, .mwpx state
│   ├── render.py        painting, wedge geometry, symmetry transforms
│   ├── snap.py          polar grid, guides and pixel snapping
│   ├── imageproc.py     raster loading, background keying
│   ├── color.py         palettes and harmonies
│   ├── project.py       save/load .mwpx
│   └── export.py        PNG/JPEG/SVG/PDF export
└── gui/                 Qt widgets: canvas, panels, rulers, dialogs
```
