"""Small helpers shared by the stage-2 tests (vessel and entrance).

Everything here builds *fictional* drawings in a temporary folder (BRIEF step2 §3: no real project data).
"""
from __future__ import annotations

from pathlib import Path

import ezdxf

from conftest import ROOT

SAMPLES = ROOT / "samples"
STEP1 = SAMPLES / "step1" / "step1.dxf"
STEP1_JW = SAMPLES / "step1" / "step1_JW.dxf"
STEP2 = SAMPLES / "step2" / "step2.dxf"
STEP2_BOUNDARY_ONLY = SAMPLES / "step2" / "step2_boundary_only.dxf"
STEP2_MOVED = SAMPLES / "step2" / "step2_moved.dxf"


def make_project(tmp_path: Path, name: str = "架空の物件", office: Path | None = None):
    """Create a project folder with the vessel inside it and return (project, store)."""
    from btruth.project import init_project, open_store

    folder = tmp_path / "project"
    project = init_project(folder, name=name, office_dir=office, recorded_by="テスト")
    store = open_store(project)
    return project, store


def write_dxf(path: Path, entities, layers=(), unit_mm: bool = True) -> Path:
    """Write a fictional DXF (R2010 so that ezdxf keeps full precision). `entities` is a list of
    (kind, layer, kwargs). Returns the path."""
    doc = ezdxf.new("R2010")
    if unit_mm:
        doc.header["$INSUNITS"] = 4
    for layer in layers:
        if layer not in doc.layers:
            doc.layers.add(layer)
    msp = doc.modelspace()
    for kind, layer, kw in entities:
        attribs = {"layer": layer}
        if kind == "LINE":
            msp.add_line(kw["start"], kw["end"], dxfattribs=attribs)
        elif kind == "CIRCLE":
            msp.add_circle(kw["center"], kw["radius"], dxfattribs=attribs)
        elif kind == "ARC":
            msp.add_arc(kw["center"], kw["radius"], kw["start"], kw["end"], dxfattribs=attribs)
        elif kind == "TEXT":
            attribs["height"] = kw.get("height", 300)
            if "rotation" in kw:
                attribs["rotation"] = kw["rotation"]
            msp.add_text(kw["text"], dxfattribs=attribs).set_placement(kw["insert"])
        elif kind == "LWPOLYLINE":
            msp.add_lwpolyline(kw["points"], close=kw.get("close", False), dxfattribs=attribs)
        elif kind == "POINT":
            msp.add_point(kw["location"], dxfattribs=attribs)
        elif kind == "INSERT":
            if kw["name"] not in doc.blocks:
                blk = doc.blocks.new(name=kw["name"])
                blk.add_line((0, 0), (100, 0))
            msp.add_blockref(kw["name"], kw["insert"], dxfattribs=attribs)
        else:
            raise ValueError(kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(path)
    return path


def one_room_dxf(path: Path, dx: float = 0.0, dy: float = 0.0, extra=()) -> Path:
    """A fictional one-room plan (6000 x 4000) like samples/step1, shifted by (dx, dy)."""
    def p(x, y):
        return (x + dx, y + dy)

    ents = [
        ("LINE", "GRID", {"start": p(0, -1500), "end": p(0, 5500)}),
        ("LINE", "GRID", {"start": p(6000, -1500), "end": p(6000, 5500)}),
        ("LINE", "GRID", {"start": p(-1500, 0), "end": p(7500, 0)}),
        ("LINE", "GRID", {"start": p(-1500, 4000), "end": p(7500, 4000)}),
        ("TEXT", "GRID", {"text": "X1", "insert": p(0, 5900)}),
        ("TEXT", "GRID", {"text": "X2", "insert": p(6000, 5900)}),
        ("TEXT", "GRID", {"text": "Y1", "insert": p(-1900, 0)}),
        ("TEXT", "GRID", {"text": "Y2", "insert": p(-1900, 4000)}),
        ("LINE", "ROOM_BOUNDARY", {"start": p(0, 0), "end": p(6000, 0)}),
        ("LINE", "ROOM_BOUNDARY", {"start": p(6000, 0), "end": p(6000, 4000)}),
        ("LINE", "ROOM_BOUNDARY", {"start": p(6000, 4000), "end": p(0, 4000)}),
        ("LINE", "ROOM_BOUNDARY", {"start": p(0, 4000), "end": p(0, 0)}),
        ("LINE", "WALL_CENTER", {"start": p(0, 0), "end": p(6000, 0)}),
        ("LINE", "WALL_CENTER", {"start": p(6000, 0), "end": p(6000, 4000)}),
        ("LINE", "WALL_CENTER", {"start": p(6000, 4000), "end": p(0, 4000)}),
        ("LINE", "WALL_CENTER", {"start": p(0, 4000), "end": p(0, 0)}),
        ("TEXT", "ROOM_NAME", {"text": "101 事務室", "insert": p(3000, 2000), "height": 350}),
    ] + list(extra)
    return write_dxf(path, ents, layers=["GRID", "ROOM_BOUNDARY", "ROOM_NAME", "WALL_CENTER"])


def count(store, sql: str, *params) -> int:
    return store.conn.execute(sql, params).fetchone()[0]
