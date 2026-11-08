"""Comparing the clues of two versions drawn with different tools (B-14; design 3-3b 案1, steps 1, 2, 4).

This is the ground for stage 4's identity run, not the identity run itself: it does not touch
elements. It
  1. aligns the coordinate frames on the crossing of the smallest grid labels present in both
     versions (v2 Q62 / Q65-3 / Q66) and writes the alignment to intake_log (never silently);
  2. normalises layer names to roles with settings/layer_roles.csv (C-2: layer habits differ);
  3. matches clues of the same kind and roles whose geometry agrees within same_position_mm and
     same_angle_deg (rules.csv — the only place the widths live), text compared exactly;
  4. reports matched pairs, clues only in A, clues only in B (candidates for addition).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from btruth.common import dumps, loads
from btruth.project import ProjectFolder
from btruth.store import Store
from btruth.tables import effective_rows, effective_rules

GRID_LABEL = re.compile(r"^([XY])(\d+)$")


def roles_for(layer_raw: str | None, entity_kind: str, layer_roles_rows: list[dict]) -> tuple[str, ...]:
    """Roles of a layer: every row whose pattern is part of the layer name (case-insensitive) and whose
    entity kind matches contributes its roles (joined with +). Unknown layers stay as raw:<name>."""
    found: set[str] = set()
    name = (layer_raw or "").lower()
    for row in layer_roles_rows:
        pat = (row.get("layer_pattern") or "").strip().lower()
        ek = (row.get("entity_kind") or "*").strip() or "*"
        if pat and pat in name and ek in ("*", entity_kind):
            found |= {r.strip() for r in (row.get("roles") or "").split("+") if r.strip()}
    return tuple(sorted(found)) if found else (f"raw:{layer_raw}",)


@dataclass
class CompareResult:
    version_a: str
    version_b: str
    frame: dict
    matched: list[tuple[str, str]] = field(default_factory=list)
    only_a: list[str] = field(default_factory=list)
    only_b: list[str] = field(default_factory=list)

    @property
    def counts(self) -> dict:
        return {"matched": len(self.matched), "only_a": len(self.only_a), "only_b": len(self.only_b)}


# ---------------------------------------------------------------------- loading and normalising
def _load_clues(store: Store, version_id: str, layer_rows: list[dict]) -> list[dict]:
    uf = store.scalar("select unit_factor from source_version where id=?", version_id) or 1.0
    out = []
    for r in store.all("select id, kind, layer_raw, geometry_json, text_raw, style_json from clue "
                       "where source_version_id=? and parent_clue_id is null and generated_from is null "
                       "and kind <> 'BLOCK_DEF' order by seq",
                       version_id):
        out.append({"id": r["id"], "kind": r["kind"], "layer": r["layer_raw"], "geometry": loads(r["geometry_json"]) or {},
                    "text": r["text_raw"], "style": loads(r["style_json"]) or {},
                    "roles": roles_for(r["layer_raw"], r["kind"], layer_rows), "uf": float(uf)})
    return out


def find_origin(clues: list[dict]) -> dict | None:
    """The crossing of the smallest X and Y grid labels: x of the X label, y of the Y label (in mm)."""
    best: dict[str, tuple[int, float, str]] = {}
    for c in clues:
        if c["kind"] not in ("TEXT", "MTEXT") or "GRID" not in c["roles"]:
            continue
        m = GRID_LABEL.match((c["text"] or "").strip())
        if not m:
            continue
        axis, number = m.group(1), int(m.group(2))
        insert = c["geometry"].get("insert") or [0, 0, 0]
        value = (insert[0] if axis == "X" else insert[1]) * c["uf"]
        if axis not in best or number < best[axis][0]:
            best[axis] = (number, value, c["text"].strip())
    if "X" not in best or "Y" not in best:
        return None
    return {"x": best["X"][1], "y": best["Y"][1], "labels": [best["X"][2], best["Y"][2]]}


def _shift(points, uf: float, origin) -> list[list[float]]:
    ox, oy = (origin["x"], origin["y"]) if origin else (0.0, 0.0)
    return [[p[0] * uf - ox, p[1] * uf - oy] + ([p[2] * uf] if len(p) > 2 else []) for p in points]


def _norm(c: dict, origin) -> dict:
    """Geometry in mm, relative to the frame origin."""
    g, uf, k = c["geometry"], c["uf"], c["kind"]
    n: dict = {}
    if k == "LINE":
        n["points"] = _shift([g["start"], g["end"]], uf, origin)
    elif k == "CIRCLE":
        n["center"] = _shift([g["center"]], uf, origin)[0]
        n["radius"] = g["radius"] * uf
    elif k == "ARC":
        n["center"] = _shift([g["center"]], uf, origin)[0]
        n["radius"] = g["radius"] * uf
        n["angles"] = [g["start_angle"], g["end_angle"]]
    elif k in ("TEXT", "MTEXT"):
        n["insert"] = _shift([g["insert"]], uf, origin)[0]
        n["rotation"] = g.get("rotation", 0.0)
        n["height"] = (c["style"].get("height") or 0.0) * uf
    elif k == "INSERT":
        n["insert"] = _shift([g["insert"]], uf, origin)[0]
        n["rotation"] = g.get("rotation", 0.0)
        n["scale"] = [g.get("xscale", 1.0), g.get("yscale", 1.0), g.get("zscale", 1.0)]
    elif k in ("LWPOLYLINE", "POLYLINE"):
        pts = g.get("points") or []
        n["points"] = _shift([p[:2] for p in pts], uf, origin)
        n["closed"] = bool(g.get("closed"))
    elif k == "POINT":
        n["point"] = _shift([g["location"]], uf, origin)[0]
    else:
        n["raw"] = g
    return n


def _dist(p, q) -> float:
    return math.dist(p[:2], q[:2])


def _angle_close(a: float, b: float, tol: float) -> bool:
    d = abs((a - b + 180.0) % 360.0 - 180.0)
    return d <= tol


def _points_close(ps, qs, tol: float, allow_reverse: bool = True) -> bool:
    if len(ps) != len(qs):
        return False
    if all(_dist(p, q) <= tol for p, q in zip(ps, qs)):
        return True
    return allow_reverse and all(_dist(p, q) <= tol for p, q in zip(ps, reversed(qs)))


def _deep_close(a, b, tol: float) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return abs(a - b) <= tol
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_deep_close(x, y, tol) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_deep_close(a[k], b[k], tol) for k in a)
    return a == b


def geometry_match(kind: str, a: dict, b: dict, text_a, text_b, tol_pos: float, tol_ang: float) -> bool:
    if kind == "LINE":
        return _points_close(a["points"], b["points"], tol_pos)
    if kind == "CIRCLE":
        return _dist(a["center"], b["center"]) <= tol_pos and abs(a["radius"] - b["radius"]) <= tol_pos
    if kind == "ARC":
        return (_dist(a["center"], b["center"]) <= tol_pos and abs(a["radius"] - b["radius"]) <= tol_pos
                and all(_angle_close(x, y, tol_ang) for x, y in zip(a["angles"], b["angles"])))
    if kind in ("TEXT", "MTEXT"):
        return (text_a == text_b and _dist(a["insert"], b["insert"]) <= tol_pos
                and _angle_close(a["rotation"], b["rotation"], tol_ang) and abs(a["height"] - b["height"]) <= tol_pos)
    if kind == "INSERT":
        return (text_a == text_b and _dist(a["insert"], b["insert"]) <= tol_pos
                and _angle_close(a["rotation"], b["rotation"], tol_ang)
                and all(abs(x - y) <= 1e-9 for x, y in zip(a["scale"], b["scale"])))
    if kind in ("LWPOLYLINE", "POLYLINE"):
        return a["closed"] == b["closed"] and _points_close(a["points"], b["points"], tol_pos)
    if kind == "POINT":
        return _dist(a["point"], b["point"]) <= tol_pos
    return text_a == text_b and _deep_close(a.get("raw"), b.get("raw"), tol_pos)


def _distance_hint(kind: str, a: dict, b: dict) -> float:
    for key in ("points", "insert", "center", "point"):
        if key in a and key in b:
            pa, pb = a[key], b[key]
            if key == "points":
                return _dist(pa[0], pb[0]) if pa and pb else 0.0
            return _dist(pa, pb)
    return 0.0


# ---------------------------------------------------------------------- the comparison
def compare_versions(store: Store, project: ProjectFolder, version_a: str, version_b: str,
                     recorded_by: str = "版の比べ") -> CompareResult:
    rules = effective_rules(store, project)
    tol_pos = float(rules.get("same_position_mm", "0.1"))
    tol_ang = float(rules.get("same_angle_deg", "0.01"))
    layer_rows = effective_rows(store, project, "layer_roles")
    A = _load_clues(store, version_a, layer_rows)
    B = _load_clues(store, version_b, layer_rows)

    oa, ob = find_origin(A), find_origin(B)
    aligned = oa is not None and ob is not None and oa["labels"] == ob["labels"]
    frame = {"aligned": aligned,
             "labels": oa["labels"] if aligned else None,
             "origin_a_mm": [oa["x"], oa["y"]] if oa else None,
             "origin_b_mm": [ob["x"], ob["y"]] if ob else None,
             "delta_mm": [ob["x"] - oa["x"], ob["y"] - oa["y"]] if aligned else [0.0, 0.0],
             "same_position_mm": tol_pos, "same_angle_deg": tol_ang,
             "note": "両方の版にある一番小さい通り芯の符号の交点で揃えた" if aligned
             else "通り芯の符号が両方の版に揃っていないので、揃えずに比べた（v2 Q62・Q66）"}
    org_a, org_b = (oa, ob) if aligned else (None, None)
    for c in A:
        c["norm"] = _norm(c, org_a)
    for c in B:
        c["norm"] = _norm(c, org_b)

    pool: dict[tuple, list[dict]] = {}
    for c in B:
        pool.setdefault((c["kind"], c["roles"]), []).append(c)
    used: set[str] = set()
    result = CompareResult(version_a=version_a, version_b=version_b, frame=frame)
    for a in A:
        best, best_d = None, None
        for b in pool.get((a["kind"], a["roles"]), []):
            if b["id"] in used:
                continue
            if geometry_match(a["kind"], a["norm"], b["norm"], a["text"], b["text"], tol_pos, tol_ang):
                d = _distance_hint(a["kind"], a["norm"], b["norm"])
                if best is None or d < best_d:
                    best, best_d = b, d
        if best is None:
            result.only_a.append(a["id"])
        else:
            used.add(best["id"])
            result.matched.append((a["id"], best["id"]))
    result.only_b = [c["id"] for c in B if c["id"] not in used]

    # A-4 / B-6: the alignment and the outcome are written down on the newer version
    store.insert("intake_log", recorded_by, source_version_id=version_b, kind="座標の枠の揃え方",
                 detail_json=dumps({"base_version": version_a, **frame}))
    store.insert("intake_log", recorded_by, source_version_id=version_b, kind="版の比べ",
                 detail_json=dumps({"base_version": version_a, **result.counts,
                                    "matched": result.matched, "only_a": result.only_a, "only_b": result.only_b}))
    if result.only_b:
        store.insert("intake_log", recorded_by, source_version_id=version_b, kind="追加の候補",
                     detail_json=dumps({"base_version": version_a, "clue_ids": result.only_b,
                                        "note": "前の版の手掛かりと対応しなかった。解釈（第3段）で AI が読む"}))
    store.commit()
    return result
