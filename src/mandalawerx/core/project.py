""".mwpx project files (versioned JSON with embedded images)."""

from __future__ import annotations

import json
from pathlib import Path

from .model import Document

PROJECT_SUFFIX = ".mwpx"


def save_project(doc: Document, path) -> Path:
    path = Path(path)
    if path.suffix.lower() != PROJECT_SUFFIX:
        path = path.with_suffix(PROJECT_SUFFIX)
    path.write_text(json.dumps(doc.to_dict(), indent=1))
    return path


def load_project(path) -> Document:
    data = json.loads(Path(path).read_text())
    if data.get("format") != "mwpx":
        raise ValueError(f"not a Mandala-Werx project file: {path}")
    if int(data.get("version", 1)) > 1:
        raise ValueError("project was saved by a newer Mandala-Werx")
    return Document.from_dict(data)
