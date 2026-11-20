"""Document model: a circular workspace holding an ordered layer stack.

The document is a square `size` x `size` canvas whose inscribed circle
(center = radius = size/2) is the mandala. Every item is positioned by
its center (cx, cy), size (w, h) and rotation (degrees); geometry is
defined in a local unit box [-0.5, 0.5]^2 and scaled by (w, h).

Items on symmetric layers are drawn once per segment: the document is
split into `segments` equal wedges around the center and each item is
copied and rotated into every wedge. With `mirror` on, each wedge also
gets a reflected copy (dihedral symmetry), so strokes crossing a wedge
boundary mirror back smoothly. With `clip` on, only the part of each
item inside the active wedge is replicated.
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field, asdict

DEFAULT_SIZE = 2048

# item kinds
RECT, ELLIPSE, POLYGON, STAR, PATH, IMAGE, SVG = (
    "rect", "ellipse", "polygon", "star", "path", "image", "svg")
SHAPE_KINDS = (RECT, ELLIPSE, POLYGON, STAR, PATH)

# layer kinds
VECTOR, RASTER = "vector", "raster"
LAYER_KINDS = (VECTOR, RASTER)


def new_id() -> str:
    return uuid.uuid4().hex[:10]


@dataclass
class Item:
    kind: str
    cx: float = 0.0
    cy: float = 0.0
    w: float = 100.0
    h: float = 100.0
    rotation: float = 0.0
    fill: str | None = "#4a7ab5"
    stroke: str | None = "#1c1c1c"
    stroke_width: float = 2.0
    opacity: float = 1.0
    # polygon/star
    sides: int = 6
    inner_ratio: float = 0.5
    corner_radius: float = 0.0
    # path: list of segments in unit-box coords:
    #   ["M", x, y] ["L", x, y] ["C", x1, y1, x2, y2, x, y] ["Z"]
    segments: list = field(default_factory=list)
    # image / svg: key into Document.assets
    asset: str | None = None
    flip_x: bool = False
    flip_y: bool = False
    id: str = field(default_factory=new_id)

    def to_dict(self) -> dict:
        d = asdict(self)
        # drop defaults that don't apply to this kind to keep files small
        if self.kind != PATH:
            d.pop("segments")
        if self.kind not in (IMAGE, SVG):
            d.pop("asset")
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Item":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: copy.deepcopy(v) for k, v in d.items()
                      if k in known})

    def clone(self, new_identity: bool = True) -> "Item":
        it = Item.from_dict(self.to_dict())
        if new_identity:
            it.id = new_id()
        return it


@dataclass
class Layer:
    name: str
    kind: str = VECTOR
    visible: bool = True
    locked: bool = False
    opacity: float = 1.0
    items: list = field(default_factory=list)
    symmetry: bool = True       # replicate into every segment
    id: str = field(default_factory=new_id)

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "kind": self.kind,
                "visible": self.visible, "locked": self.locked,
                "opacity": self.opacity,
                "items": [it.to_dict() for it in self.items],
                "symmetry": self.symmetry}

    @classmethod
    def from_dict(cls, d: dict) -> "Layer":
        return cls(name=d.get("name", "Layer"), kind=d.get("kind", VECTOR),
                   visible=d.get("visible", True),
                   locked=d.get("locked", False),
                   opacity=d.get("opacity", 1.0),
                   items=[Item.from_dict(i) for i in d.get("items", [])],
                   symmetry=d.get("symmetry", True),
                   id=d.get("id") or new_id())


def default_grid() -> dict:
    # Polar grid: `rings` equal radial bands, `subdivisions` faint rings
    # per band, `spokes` radial lines (0 = same count as the segments).
    return {"show": True, "rings": 8, "subdivisions": 0, "spokes": 0,
            "color": "#4a7ab5", "snap": False, "show_guides": True,
            "snap_guides": True, "lock_guides": False}


def default_guides() -> dict:
    # "x": vertical guides at these x positions, "y": horizontal guides
    return {"x": [], "y": []}


def default_symmetry() -> dict:
    # The circle is split into `segments` wedges. `angle` is the
    # direction of the active segment's center line (degrees; -90 puts
    # its bisector at 12 o'clock). `mirror` adds a reflected copy inside
    # every wedge. `clip` keeps only the part of each item inside the
    # active wedge.
    return {"segments": 8, "mirror": True, "angle": -90.0, "clip": False,
            "highlight": True}


def default_palette() -> dict:
    return {"harmony": "triadic", "base_color": "#2f6f8f",
            "shares": [0.6, 0.3, 0.1]}


@dataclass
class Document:
    size: int = DEFAULT_SIZE
    background: str | None = "#ffffff"
    layers: list = field(default_factory=list)   # bottom -> top
    # assets: id -> {"type": "png"|"svg", "data": base64-png | svg text,
    #                "w": px, "h": px, "name": str}
    assets: dict = field(default_factory=dict)
    palette: dict = field(default_factory=default_palette)
    name: str = "Untitled"
    symmetry: dict = field(default_factory=default_symmetry)
    grid: dict = field(default_factory=default_grid)
    guides: dict = field(default_factory=default_guides)

    def __post_init__(self):
        if not self.layers:
            self.layers.append(Layer("Layer 1", VECTOR))

    # -- geometry ------------------------------------------------------
    @property
    def center(self) -> float:
        return self.size / 2

    @property
    def radius(self) -> float:
        return self.size / 2

    @property
    def segments(self) -> int:
        return max(1, int(self.symmetry.get("segments") or 1))

    @property
    def segment_angle(self) -> float:
        return 360.0 / self.segments

    # -- lookups -------------------------------------------------------
    def layer(self, lid: str) -> Layer | None:
        return next((l for l in self.layers if l.id == lid), None)

    def layer_index(self, lid: str) -> int:
        for i, l in enumerate(self.layers):
            if l.id == lid:
                return i
        return -1

    def find_item(self, iid: str):
        for lay in self.layers:
            for it in lay.items:
                if it.id == iid:
                    return lay, it
        return None, None

    def unique_layer_name(self, base: str) -> str:
        names = {l.name for l in self.layers}
        n = 1
        while f"{base} {n}" in names:
            n += 1
        return f"{base} {n}"

    # -- (de)serialisation --------------------------------------------
    def state(self) -> dict:
        """Undo snapshot (assets are append-only, so they're excluded)."""
        return {"size": self.size, "background": self.background,
                "layers": [l.to_dict() for l in self.layers],
                "palette": copy.deepcopy(self.palette), "name": self.name,
                "symmetry": copy.deepcopy(self.symmetry),
                "grid": copy.deepcopy(self.grid),
                "guides": copy.deepcopy(self.guides)}

    def restore(self, st: dict):
        self.size = st["size"]
        self.background = st["background"]
        self.layers = [Layer.from_dict(l) for l in st["layers"]]
        self.palette = copy.deepcopy(st["palette"])
        self.name = st.get("name", self.name)
        self.symmetry = {**default_symmetry(),
                         **copy.deepcopy(st.get("symmetry") or {})}
        self.grid = {**default_grid(), **copy.deepcopy(st.get("grid") or {})}
        self.guides = {**default_guides(),
                       **copy.deepcopy(st.get("guides") or {})}

    def used_assets(self) -> set:
        used = {it.asset for l in self.layers for it in l.items if it.asset}
        return used

    def to_dict(self) -> dict:
        d = self.state()
        used = self.used_assets()
        d["assets"] = {k: v for k, v in self.assets.items() if k in used}
        d["format"] = "mwpx"
        d["version"] = 1
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Document":
        doc = cls(layers=[Layer("tmp")])
        doc.restore({"size": d.get("size", DEFAULT_SIZE),
                     "background": d.get("background"),
                     "layers": d.get("layers") or [
                         Layer("Layer 1").to_dict()],
                     "palette": d.get("palette") or default_palette(),
                     "name": d.get("name", "Untitled"),
                     "symmetry": d.get("symmetry"),
                     "grid": d.get("grid"), "guides": d.get("guides")})
        doc.assets = dict(d.get("assets", {}))
        return doc
