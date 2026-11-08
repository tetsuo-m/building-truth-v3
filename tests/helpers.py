"""Small helpers shared by the tests (vessel, entrance, interpretation and confirmation).

Everything here builds *fictional* drawings in a temporary folder (BRIEF step2 §3: no real project data).
"""
from __future__ import annotations

import json
from pathlib import Path

import ezdxf

from conftest import ROOT

SAMPLES = ROOT / "samples"
STEP1 = SAMPLES / "step1" / "step1.dxf"
STEP1_JW = SAMPLES / "step1" / "step1_JW.dxf"
STEP2 = SAMPLES / "step2" / "step2.dxf"
STEP2_BOUNDARY_ONLY = SAMPLES / "step2" / "step2_boundary_only.dxf"
STEP2_MOVED = SAMPLES / "step2" / "step2_moved.dxf"
WALL_TYPES = SAMPLES / "step1" / "wall_types.csv"
FINISH_SCHEDULE = SAMPLES / "step1" / "finish_schedule.csv"
FIXTURES = ROOT / "tests" / "fixtures"


def make_project(tmp_path: Path, name: str = "架空の物件", office: Path | None = None):
    """Create a project folder with the vessel inside it and return (project, store)."""
    from btruth.project import init_project, open_store

    folder = tmp_path / "project"
    project = init_project(folder, name=name, office_dir=office, recorded_by="テスト")
    store = open_store(project)
    return project, store


def import_sample(tmp_path: Path, dxf: Path = STEP1):
    """A project with the sample plan (平面図), the wall-type table (壁種表) and the finish schedule (仕上表)."""
    from btruth.intake import import_file

    project, store = make_project(tmp_path)
    import_file(store, project, dxf, source_name="平面図", kind="設計図", drawing_type="建築平面図",
                discipline="建築", recorded_by="テスト")
    import_file(store, project, WALL_TYPES, source_name="壁種表", kind="設計図", drawing_type="壁種表",
                recorded_by="テスト")
    import_file(store, project, FINISH_SCHEDULE, source_name="仕上表", kind="設計図", drawing_type="仕上表",
                recorded_by="テスト")
    return project, store


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def register_fixture(store, project, name: str):
    from btruth.propose import register_proposal

    return register_proposal(store, project, fixture(name), recorded_by="テスト")


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


# ---------------------------------------------------------------- small proposal builders (stage 3)
def seg(a, b):
    return [[float(a[0]), float(a[1])], [float(b[0]), float(b[1])]]


def proposal(elements, relations=(), assumptions=(), claims=(), unreadable=(), sources=("平面図@1",),
             summary="テストの提案", agent_name="テストの読み手"):
    return {"agent": {"name": agent_name, "kind": "テスト", "model": None, "version": "0", "instructions_sha256": None},
            "source_versions": list(sources), "summary": summary, "assumptions": list(assumptions),
            "elements": list(elements), "relations": list(relations), "claims": list(claims),
            "unreadable": list(unreadable)}


def element(ref, kind, claims=(), evidence=(), reason="テスト", confidence=0.9):
    return {"ref": ref, "kind": kind, "reason": reason, "confidence": confidence,
            "evidence": list(evidence), "claims": list(claims)}


def claim(attribute, value, evidence=(), unit=None, confidence=0.9):
    d = {"attribute": attribute, "value": value, "confidence": confidence, "evidence": list(evidence)}
    if unit:
        d["unit"] = unit
    return d


def relation(ref, kind, frm, to, role=None, evidence=(), reason="テスト", confidence=0.9):
    d = {"ref": ref, "kind": kind, "from": frm, "to": to, "reason": reason, "confidence": confidence,
         "evidence": list(evidence)}
    if role is not None:
        d["role"] = role
    return d


def ev(ref, role="主の根拠", reason=None):
    d = {"clue": ref, "role": role}
    if reason:
        d["reason"] = reason
    return d


STOREY = {"find": {"kind": "階", "name": "1階"}}
OUTSIDE = {"find": {"kind": "外部"}}


def rect_room(ref: str, x0, y0, x1, y1, rb_refs: list[str], partners: list | None = None, name: str | None = None,
              name_evidence=(), physical: bool = True):
    """A rectangular room (counter-clockwise) with one boundary per side; returns (elements, relations).
    `rb_refs` are the clue refs of the four boundary lines (S, E, N, W); `partners` the wall refs or None."""
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    claims = []
    if name:
        claims.append(claim("室名", name, list(name_evidence)))
    els = [element(ref, "部屋", claims, [ev(r) for r in rb_refs] + list(name_evidence))]
    rels = [relation(f"{ref}_in", "集める", ref, STOREY)]
    for i in range(4):
        a, b = corners[i], corners[(i + 1) % 4]
        bref = f"{ref}_b{i + 1}"
        els.append(element(bref, "空間の境界",
                           [claim("線分", seg(a, b), [ev(rb_refs[i])], "mm"),
                            claim("境界の種類", "物理的" if physical else "仮想", [ev(rb_refs[i])])],
                           [ev(rb_refs[i])]))
        rels.append(relation(f"{bref}_bounds", "区切る", bref, ref, {"順": i + 1}))
        if partners and partners[i]:
            rels.append(relation(f"{bref}_partner", "境界の相手", bref, partners[i]))
    return els, rels


# ---------------------------------------------------------------- stage 4: fictional versions of the step2 plan
JW_ORIGIN = (210000000.0, 148500000.0)        # samples/step2/*.dxf keep Jw_cad's coordinates


def step2_like_dxf(path: Path, wc_x: float = 2300, rb_x: float | None = None, extra=(), door: bool = False,
                   door_dx: float = 0.0, dx: float = 0.0, dy: float = 0.0, door_name: str = "DOOR_S",
                   door_tag: str = "AD-1") -> Path:
    """A fictional plan with the same first 23 entities (and order) as samples/step2/step2.dxf, at origin (dx, dy).
    `wc_x` is the partition's wall centre, `rb_x` its room boundary (default: the same). With `door`, an INSERT
    (seq 24) and its tag text (seq 25) sit on the partition at y 1100 (wall-based position 1100 from (x, 0));
    `door_dx` shifts them in x independently of the wall."""
    rb_x = wc_x if rb_x is None else rb_x

    def p(x, y):
        return (x + dx, y + dy)

    ents = []
    for label, a, b, c in (("X1", (0, -1500), (0, 5500), (0, 5900)), ("X2", (6000, -1500), (6000, 5500), (6000, 5900)),
                           ("Y1", (-1500, 0), (7500, 0), (-1900, 0)), ("Y2", (-1500, 4000), (7500, 4000), (-1900, 4000))):
        ents += [("LINE", "_0-2_GRID", {"start": p(*a), "end": p(*b)}),
                 ("CIRCLE", "_0-2_GRID", {"center": p(*c), "radius": 300}),
                 ("TEXT", "_0-2_GRID", {"text": label, "insert": p(*c)})]
    for a, b in (((0, 0), (6000, 0)), ((6000, 0), (6000, 4000)), ((6000, 4000), (0, 4000)), ((0, 4000), (0, 0))):
        ents += [("LINE", "_0-3_ROOM_BOUNDARY", {"start": p(*a), "end": p(*b)}),
                 ("LINE", "_0-5_WALL_CENTER", {"start": p(*a), "end": p(*b)})]
    ents.append(("TEXT", "_0-4_ROOM_NAME", {"text": "101 事務室", "insert": p(3000, 2000), "height": 350}))
    ents.append(("LINE", "_0-3_ROOM_BOUNDARY", {"start": p(rb_x, 4000), "end": p(rb_x, 0)}))
    ents.append(("LINE", "_0-5_WALL_CENTER", {"start": p(wc_x, 4000), "end": p(wc_x, 0)}))
    if door:
        ents.append(("INSERT", "_0-6_DOOR", {"name": door_name, "insert": p(wc_x + door_dx, 1100)}))
        ents.append(("TEXT", "_0-6_DOOR", {"text": door_tag, "insert": p(wc_x + door_dx + 150, 1500)}))
    ents += list(extra)
    return write_dxf(path, ents, layers=["_0-2_GRID", "_0-3_ROOM_BOUNDARY", "_0-4_ROOM_NAME", "_0-5_WALL_CENTER", "_0-6_DOOR"])


def _shift_values(obj, dx: float, dy: float):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k == "claims":
                out[k] = [dict(c, value=_shift_points(c["value"], dx, dy)) if c.get("attribute") in ("線分", "芯線") else c
                          for c in v]
            else:
                out[k] = _shift_values(v, dx, dy)
        return out
    if isinstance(obj, list):
        return [_shift_values(x, dx, dy) for x in obj]
    return obj


def _shift_points(value, dx, dy):
    return [[p[0] + dx, p[1] + dy] + list(p[2:]) for p in value]


def step2_fixture_at(dx: float = 0.0, dy: float = 0.0, door: bool = False) -> dict:
    """The fixed interpretation of step2, moved from Jw_cad's origin to (dx, dy); with `door`, an opening that
    voids the partition (wall-based 1100, width 800) and a door AD-1 that fills it (clues 24, 25)."""
    d = _shift_values(fixture("step2_fixed"), dx - JW_ORIGIN[0], dy - JW_ORIGIN[1])
    if door:
        d["elements"] += [
            element("opening_A", "開口", [claim("位置", 1100, [ev("平面図@1#24")], "mm"), claim("幅", 800, [ev("平面図@1#24")], "mm")],
                    [ev("平面図@1#24")]),
            element("door_A", "建具", [claim("符号", "AD-1", [ev("平面図@1#25")]), claim("建具の種類", "扉", [ev("平面図@1#24")])],
                    [ev("平面図@1#24"), ev("平面図@1#25")]),
        ]
        d["relations"] += [relation("opening_A_voids", "くり抜く", "opening_A", "wall_A", {"位置": 1100}),
                           relation("door_A_fills", "ふさぐ", "door_A", "opening_A"),
                           relation("door_A_in", "含む", "door_A", STOREY)]
    return d
