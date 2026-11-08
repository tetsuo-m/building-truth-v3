"""Identity between two versions of one source, and carrying the interpretation over (design H, 3-3b 案1〜4).

The run never writes `review` (G-1): it writes identity_run / identity_link / impact / recheck_mark /
relation_end / issue, and one interpretation of its own (agent 規則の読み手, name 同定) whose items are the
new positions of the elements that moved (H-2). Those items wait for a person's batch approval (G-1,
決定 Q1・Q15); until then the effective values stay where they were (B-9, F-4).

一段目 (案1)
  1. the frame: both versions are aligned on the crossing of the smallest grid labels present in both
     (compare.find_origin); the alignment is written to identity_run.frame_json and intake_log (F-9);
  2. the node mesh (B-7): end points and crossings of the clues whose layer role is ROOM_BOUNDARY, merged
     within same_position_mm. Edges, faces (rooms' candidates) and corners are computed, never stored; the
     outcome goes to identity_run.mesh_json (B-10). Faces are matched by their anchored corners (a corner is a
     node where the ring turns, together with the directions of its two sides): one new face → 一致, several
     → 分割, a new face that holds anchored corners of several old faces → 統合;
  3. per element, its basis is split by source (決定 16): clues of the source that got a new version are
     looked for in the new version; clues of other sources (the tables) are carried over as found;
  4. rooms and their boundaries follow the faces and corners (決定 Q13): a T-node on the far side is not a
     corner of this room, so this room's boundaries do not split (F-2); walls, grid axes and the outer side's
     boundaries are lines: found → 一致, else one parallel line of the same role within wall_move_max_mm →
     移動; openings and doors follow their wall when their clues are found under the wall's displacement
     (壁基準が同じ → 一致（壁に従う）。決定 11、例9). A text or block at the same place with another content
     is 意味が変わった (案3).
二段目 (案2・4): impact rows (one step along the relations), the clues to hand to the AI (bounding box of
what was not explained, widened by reread_margin_mm) with the context elements around it.

Which basis (Q25, 【仮】): an approved element is followed through the clues of its approved claims and of its
creating item (the basis approved by the person, B-14); an element still proposed is followed through the
clues of its proposal, recorded as such — so a version can be identified before the person approves.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from btruth import __version__, geometry
from btruth.checks import _severity
from btruth.common import dumps, loads
from btruth.compare import _load_clues, _norm, find_origin, geometry_match
from btruth.effective import (STATUS_APPROVED, STATUS_HELD, STATUS_PENDING, _kind_of, claim_status, effective_name,
                              effective_value, element_item, item_status, proposed_kind_of, relations_from, relations_to)
from btruth.project import ProjectFolder
from btruth.store import Store
from btruth.tables import effective_rows, effective_rules, latest_load_id

AGENT_NAME = "同定"
ITEM_KIND = "既存の要素と同じ"
LIVE = (STATUS_APPROVED, STATUS_PENDING, STATUS_HELD)
LINE_KEY = {"壁": ("芯線", "WALL_CENTER"), "通り芯": ("線分", "GRID"), "空間の境界": ("線分", "ROOM_BOUNDARY")}
NEIGHBOUR_KINDS = {"接する", "区切る", "境界の相手", "向かい合う", "くり抜く", "ふさぐ", "載る", "使う", "部品である", "貫通する"}
BASIS_APPROVED = "承認の前提"
BASIS_PROPOSED = "提案の根拠（未承認）"
TYPE_KINDS = {"壁種", "建具の型", "柱の型", "層の組み立て", "材料"}
KEY_ATTRIBUTES = {"柱": ("符号",), "建具": ("符号",), "建具の型": ("符号",), "壁種": ("符号",), "柱の型": ("符号",),
                  "通り芯": ("符号",), "部屋": ("室番号",), "材料": ("名称",)}


def add_mark(store: Store, recorded_by: str, review_id: str, caused_by_kind: str, caused_by_id: str, reason: str,
             detail: dict) -> bool:
    """A recheck mark (G-2), not twice for the same judgement and the same cause."""
    if store.one("select 1 from recheck_mark where review_id=? and caused_by_kind=? and caused_by_id=?", review_id,
                 caused_by_kind, caused_by_id):
        return False
    store.insert("recheck_mark", recorded_by, review_id=review_id, caused_by_kind=caused_by_kind, caused_by_id=caused_by_id,
                 reason=reason, detail_json=dumps(detail))
    return True


class IdentityError(Exception):
    pass


@dataclass
class IdentityResult:
    run_id: str
    interpretation_id: str
    counts: dict
    mesh: dict
    move_items: list = field(default_factory=list)
    issues: list = field(default_factory=list)
    links: dict = field(default_factory=dict)
    scope: dict = field(default_factory=dict)


# ====================================================================== small geometry
def _angle(p, q) -> float:
    return math.degrees(math.atan2(q[1] - p[1], q[0] - p[0])) % 360.0


def _ang_close(a: float, b: float, tol: float) -> bool:
    return abs((a - b + 180.0) % 360.0 - 180.0) <= tol


def _seg_intersection(a, b, tol):
    """The crossing point of two segments (proper or T), or None (parallel segments give None)."""
    (x1, y1), (x2, y2) = a
    (x3, y3), (x4, y4) = b
    d = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(d) < 1e-12:
        return None
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / d
    p = (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
    for s in (a, b):
        L = geometry.length(s)
        u = geometry.along(s, p)
        if u < -tol or u > L + tol or geometry.distance_to_line(s, p) > tol:
            return None
    return p


def _parallel(a, b, tol_deg) -> bool:
    return _ang_close(_angle(*a) % 180.0, _angle(*b) % 180.0, tol_deg) or \
        _ang_close(_angle(*a) % 180.0 + 180.0, _angle(*b) % 180.0, tol_deg)


def _oriented_like(new, base):
    """`new` with its ends swapped if it runs against `base`."""
    (a, b), (c, d) = base, new
    if (b[0] - a[0]) * (d[0] - c[0]) + (b[1] - a[1]) * (d[1] - c[1]) < 0:
        return (d, c)
    return (c, d)


# ====================================================================== the node mesh (B-7)
class Mesh:
    def __init__(self, segments, tol: float, tol_deg: float):
        self.tol, self.tol_deg = tol, tol_deg
        self.nodes: list[tuple[float, float]] = []
        for s in segments:
            self._node(s[0])
            self._node(s[1])
        for i in range(len(segments)):
            for j in range(i + 1, len(segments)):
                p = _seg_intersection(segments[i], segments[j], tol)
                if p is not None:
                    self._node(p)
        edges = set()
        for s in segments:
            L = geometry.length(s)
            on = sorted(((geometry.along(s, n), k) for k, n in enumerate(self.nodes)
                         if geometry.distance_to_line(s, n) <= tol and -tol <= geometry.along(s, n) <= L + tol))
            for (_, a), (_, b) in zip(on, on[1:]):
                if a != b:
                    edges.add((min(a, b), max(a, b)))
        self.edges = sorted(edges)
        self.adj: dict[int, list[int]] = {}
        for a, b in self.edges:
            self.adj.setdefault(a, []).append(b)
            self.adj.setdefault(b, []).append(a)
        self.faces = self._faces()

    def _node(self, p) -> int:
        for k, n in enumerate(self.nodes):
            if math.dist(n, p) <= self.tol:
                return k
        self.nodes.append((float(p[0]), float(p[1])))
        return len(self.nodes) - 1

    def find(self, p) -> int | None:
        for k, n in enumerate(self.nodes):
            if math.dist(n, p) <= self.tol:
                return k
        return None

    def _faces(self) -> list[dict]:
        order = {v: sorted(ns, key=lambda w: _angle(self.nodes[v], self.nodes[w])) for v, ns in self.adj.items()}
        seen, faces = set(), []
        for a, b in self.edges:
            for u, v in ((a, b), (b, a)):
                if (u, v) in seen:
                    continue
                ring, cu, cv = [], u, v
                while (cu, cv) not in seen:
                    seen.add((cu, cv))
                    ring.append(cu)
                    ns = order[cv]
                    k = ns.index(cu)
                    cu, cv = cv, ns[(k - 1) % len(ns)]
                    if len(ring) > 4 * len(self.edges) + 4:
                        break
                pts = [self.nodes[k] for k in ring]
                if geometry.polygon_area(pts) > self.tol:
                    faces.append({"ring": ring, "corners": self._corners(ring)})
        return faces

    def _corners(self, ring: list[int]) -> list[dict]:
        out = []
        n = len(ring)
        for i, k in enumerate(ring):
            prev, nxt = self.nodes[ring[i - 1]], self.nodes[ring[(i + 1) % n]]
            here = self.nodes[k]
            a_in, a_out = _angle(here, prev), _angle(here, nxt)
            if _ang_close(a_in, (a_out + 180.0) % 360.0, self.tol_deg):
                continue                                   # a straight run through a T-node: not a corner
            out.append({"node": k, "to_prev": a_in, "to_next": a_out})
        return out


def _same_sector(c1, c2, tol_deg) -> bool:
    return _ang_close(c1["to_prev"], c2["to_prev"], tol_deg) and _ang_close(c1["to_next"], c2["to_next"], tol_deg)


def match_meshes(base: Mesh, new: Mesh) -> dict:
    tol, tol_deg = base.tol, base.tol_deg
    anchor = {i: new.find(p) for i, p in enumerate(base.nodes)}
    anchor = {i: j for i, j in anchor.items() if j is not None}
    owner_new: dict[int, set] = {}
    face_map = []
    for fi, f in enumerate(base.faces):
        targets = set()
        for c in f["corners"]:
            j = anchor.get(c["node"])
            if j is None:
                continue
            for gi, g in enumerate(new.faces):
                if any(gc["node"] == j and _same_sector(c, gc, tol_deg) for gc in g["corners"]):
                    targets.add(gi)
        face_map.append(targets)
        for gi in targets:
            owner_new.setdefault(gi, set()).add(fi)
    faces, corner_pairs = [], {}
    for fi, targets in enumerate(face_map):
        f = base.faces[fi]
        entry = {"base_face": fi, "base_corners": [base.nodes[c["node"]] for c in f["corners"]]}
        if not targets:
            entry.update(verdict="消えた面", new_faces=[])
        elif len(targets) > 1:
            entry.update(verdict="分割", new_faces=sorted(targets))
        elif len(owner_new[next(iter(targets))]) > 1:
            entry.update(verdict="統合", new_faces=sorted(targets))
        else:
            gi = next(iter(targets))
            g = new.faces[gi]
            entry.update(verdict="一致", new_faces=[gi])
            fc, gc = f["corners"], g["corners"]
            if len(fc) == len(gc):
                k = next(i for i, c in enumerate(fc) if c["node"] in anchor)
                m = next(i for i, c in enumerate(gc) if c["node"] == anchor[fc[k]["node"]])
                pairs = {fc[(k + i) % len(fc)]["node"]: gc[(m + i) % len(gc)]["node"] for i in range(len(fc))}
                corner_pairs[fi] = pairs
                entry["corners"] = f"{len(fc)}→{len(gc)}"
            else:
                entry["corners"] = f"{len(fc)}→{len(gc)}"
                entry["corner_change"] = "角が増えた" if len(gc) > len(fc) else "角が減った"
        faces.append(entry)
    for gi, g in enumerate(new.faces):
        if gi not in owner_new:
            faces.append({"new_face": gi, "verdict": "新しい面", "new_corners": [new.nodes[c["node"]] for c in g["corners"]]})
    moved = {}
    for pairs in corner_pairs.values():
        for i, j in pairs.items():
            if i not in anchor and i not in moved:
                moved[i] = j
    used_new = set(anchor.values()) | set(moved.values())
    edges_split = []
    for a, b in base.edges:
        if a in anchor and b in anchor:
            A, B = new.nodes[anchor[a]], new.nodes[anchor[b]]
            s = (A, B)
            inner = [n for k, n in enumerate(new.nodes) if k not in (anchor[a], anchor[b])
                     and geometry.distance_to_line(s, n) <= tol and tol < geometry.along(s, n) < geometry.length(s) - tol]
            if inner:
                edges_split.append({"edge": [base.nodes[a], base.nodes[b]], "new_nodes": inner})
    return {
        "anchor": anchor, "moved": moved, "face_map": face_map, "corner_pairs": corner_pairs,
        "json": {
            "nodes_base": len(base.nodes), "nodes_new": len(new.nodes),
            "edges_base": len(base.edges), "edges_new": len(new.edges),
            "anchors": [[base.nodes[i], new.nodes[j]] for i, j in sorted(anchor.items())],
            "moved": [{"from": base.nodes[i], "to": new.nodes[j], "distance_mm": math.dist(base.nodes[i], new.nodes[j])}
                      for i, j in sorted(moved.items())],
            "appeared": [new.nodes[k] for k in range(len(new.nodes)) if k not in used_new],
            "vanished": [base.nodes[i] for i in range(len(base.nodes)) if i not in anchor and i not in moved],
            "faces": faces, "edges_split": edges_split,
        },
    }


# ====================================================================== clues of a version, normalised
class _Versions:
    """Clues of any version of the source, normalised to the frame shared with the new version."""

    def __init__(self, store: Store, project: ProjectFolder, new_vid: str, tol: float, tol_deg: float):
        self.store, self.tol, self.tol_deg = store, tol, tol_deg
        self.layer_rows = effective_rows(store, project, "layer_roles")
        self.new_vid = new_vid
        self.new = _load_clues(store, new_vid, self.layer_rows)
        self.new_origin = find_origin(self.new)
        self._cache: dict[str, dict] = {}
        self._new_norm: dict[bool, list] = {}

    def _aligned(self, origin) -> bool:
        return origin is not None and self.new_origin is not None and origin["labels"] == self.new_origin["labels"]

    def version(self, vid: str) -> dict:
        if vid not in self._cache:
            clues = _load_clues(self.store, vid, self.layer_rows)
            origin = find_origin(clues)
            aligned = self._aligned(origin)
            for c in clues:
                c["norm"] = _norm(c, origin if aligned else None)
            self._cache[vid] = {"clues": {c["id"]: c for c in clues}, "origin": origin, "aligned": aligned,
                                "uf": clues[0]["uf"] if clues else 1.0}
        return self._cache[vid]

    def new_clues(self, aligned: bool) -> list:
        if aligned not in self._new_norm:
            out = []
            for c in self.new:
                d = dict(c)
                d["norm"] = _norm(c, self.new_origin if aligned else None)
                out.append(d)
            self._new_norm[aligned] = out
        return self._new_norm[aligned]

    def clue(self, clue_id: str):
        vid = self.store.scalar("select source_version_id from clue where id=?", clue_id)
        v = self.version(vid)
        return v["clues"].get(clue_id), v["aligned"]

    # --- matching
    @staticmethod
    def _content(c):
        if c["kind"] == "INSERT":
            return (c["style"] or {}).get("block_name")
        return c["text"]

    def match(self, c: dict, aligned: bool, shift=(0.0, 0.0)) -> str | None:
        n = _shift_norm(c["norm"], shift)
        for b in self.new_clues(aligned):
            if b["kind"] != c["kind"] or b["roles"] != c["roles"] or self._content(b) != self._content(c):
                continue
            if geometry_match(c["kind"], n, b["norm"], c["text"], b["text"], self.tol, self.tol_deg):
                return b["id"]
        return None

    def changed_in_place(self, c: dict, aligned: bool, shift=(0.0, 0.0)) -> str | None:
        """A text / block at the same place with other content, or a table row with the same key (its first field)
        and other content (案3: 意味の面)."""
        if c["kind"] == "ROW":
            key = _row_key(c["text"])
            for b in self.new_clues(aligned):
                if b["kind"] == "ROW" and _row_key(b["text"]) == key and b["text"] != c["text"]:
                    return b["id"]
            return None
        if c["kind"] not in ("TEXT", "MTEXT", "INSERT"):
            return None
        n = _shift_norm(c["norm"], shift)
        for b in self.new_clues(aligned):
            if b["kind"] == c["kind"] and math.dist(n["insert"][:2], b["norm"]["insert"][:2]) <= self.tol \
                    and self._content(b) != self._content(c):
                return b["id"]
        return None

    def to_new_coords(self, p, aligned: bool):
        uf = self.new[0]["uf"] if self.new else 1.0
        ox, oy = (self.new_origin["x"], self.new_origin["y"]) if aligned and self.new_origin else (0.0, 0.0)
        return [(p[0] + ox) / uf, (p[1] + oy) / uf]

    def to_norm(self, p, vid: str):
        v = self.version(vid)
        o = v["origin"] if v["aligned"] else None
        ox, oy = (o["x"], o["y"]) if o else (0.0, 0.0)
        return (p[0] * v["uf"] - ox, p[1] * v["uf"] - oy)


def _row_key(text: str | None) -> str | None:
    import csv
    if not text:
        return None
    try:
        return next(csv.reader([text]))[0].strip()
    except (StopIteration, csv.Error):
        return None


def _shift_norm(n: dict, shift) -> dict:
    if not shift or (shift[0] == 0 and shift[1] == 0):
        return n
    dx, dy = shift
    out = dict(n)
    for key in ("insert", "center", "point"):
        if key in out:
            out[key] = [out[key][0] + dx, out[key][1] + dy] + list(out[key][2:])
    if "points" in out:
        out["points"] = [[p[0] + dx, p[1] + dy] + list(p[2:]) for p in out["points"]]
    return out


def _line_of(c: dict):
    pts = c["norm"].get("points")
    if c["kind"] == "LINE" and pts:
        return (tuple(pts[0][:2]), tuple(pts[1][:2]))
    return None


def _points_of(c: dict) -> list:
    n = c["norm"]
    if "points" in n:
        return [p[:2] for p in n["points"]]
    for key in ("insert", "center", "point"):
        if key in n:
            return [n[key][:2]]
    return []


# ====================================================================== the run
def identify(store: Store, project: ProjectFolder, base_version_id: str, new_version_id: str,
             recorded_by: str = "同定") -> IdentityResult:
    base = store.one("select id, source_id, seq from source_version where id=?", base_version_id)
    new = store.one("select id, source_id, seq from source_version where id=?", new_version_id)
    if base is None or new is None:
        raise IdentityError("版が見つかりません")
    if base["source_id"] != new["source_id"]:
        raise IdentityError("第4段の同定は、同じ出どころの版の間だけ（出どころの間の同定は第5段。B-13）")
    source_id = base["source_id"]
    rules = effective_rules(store, project)
    tol = float(rules.get("same_position_mm", "0.1"))
    tol_deg = float(rules.get("same_angle_deg", "0.01"))
    gap = float(rules.get("gap_tol_mm", "50"))
    move_max = float(rules.get("wall_move_max_mm", "1000"))
    margin = float(rules.get("reread_margin_mm", "1000"))
    V = _Versions(store, project, new_version_id, tol, tol_deg)
    bv = V.version(base_version_id)
    aligned = bv["aligned"]
    frame = {"aligned": aligned, "labels": bv["origin"]["labels"] if aligned else None,
             "origin_base_mm": [bv["origin"]["x"], bv["origin"]["y"]] if bv["origin"] else None,
             "origin_new_mm": [V.new_origin["x"], V.new_origin["y"]] if V.new_origin else None,
             "delta_mm": [V.new_origin["x"] - bv["origin"]["x"], V.new_origin["y"] - bv["origin"]["y"]] if aligned else [0.0, 0.0],
             "same_position_mm": tol, "same_angle_deg": tol_deg,
             "note": "両方の版にある一番小さい通り芯の符号の交点で揃えた" if aligned
             else "通り芯の符号が両方の版に揃っていないので、揃えずに比べた（v2 Q62・Q66）"}

    # ---------------------------------------------------------------- the mesh
    def rb_segments(clues):
        out = []
        for c in clues:
            if "ROOM_BOUNDARY" not in c["roles"]:
                continue
            pts = c["norm"].get("points") or []
            if c["kind"] == "LINE" and len(pts) == 2:
                out.append((tuple(pts[0][:2]), tuple(pts[1][:2])))
            elif c["kind"] in ("LWPOLYLINE", "POLYLINE") and len(pts) >= 2:
                ps = [tuple(p[:2]) for p in pts] + ([tuple(pts[0][:2])] if c["norm"].get("closed") else [])
                out += list(zip(ps, ps[1:]))
        return out

    base_mesh = Mesh(rb_segments(bv["clues"].values()), tol, tol_deg)
    new_mesh = Mesh(rb_segments(V.new_clues(aligned)), tol, tol_deg)
    mm = match_meshes(base_mesh, new_mesh)

    # every base clue of this source found in the new version (used to tell candidates for addition)
    new_used: set[str] = set()
    for c in bv["clues"].values():
        m = V.match(c, aligned)
        if m:
            new_used.add(m)

    # ---------------------------------------------------------------- the elements to follow
    elements = []
    for item in store.all("select id, element_id from interpretation_item where kind='要素を作る' and element_id is not null "
                          "order by rowid"):
        st = item_status(store, item["id"])
        if st not in LIVE:
            continue
        elements.append((item["element_id"], st))

    def version_of(clue_id):
        return store.one("select v.id, v.source_id, v.seq from clue c join source_version v on v.id=c.source_version_id "
                         "where c.id=?", clue_id)

    def basis_claims(eid: str) -> dict:
        """attribute -> the claim row that carries the element's value now (approved first; Q25)."""
        out = {}
        for c in store.all("select rowid as rn, * from claim where subject_id=? and mode='観測' and attribute<>'種類' order by rowid", eid):
            st = claim_status(store, c)
            if st not in LIVE:
                continue
            prev = out.get(c["attribute"])
            rank = (st == STATUS_APPROVED, _seq_of(store, c["source_version_id"]), c["rn"])
            if prev is None or rank >= prev[0]:
                out[c["attribute"]] = (rank, c)
        return {a: v[1] for a, v in out.items()}

    def claim_clues(claim_id: str) -> list[str]:
        return [r["clue_id"] for r in store.all("select clue_id from claim_evidence where claim_id=?", claim_id)]

    def element_basis(eid: str) -> list[str]:
        item = element_item(store, eid)
        clues = [r["clue_id"] for r in store.all("select clue_id from interpretation_evidence where item_id=? and clue_id is not null",
                                                  item["id"])] if item else []
        for c in basis_claims(eid).values():
            clues += claim_clues(c["id"])
        return list(dict.fromkeys(clues))

    def split_by_source(clue_ids):
        mine, other = [], []
        for cid in clue_ids:
            v = version_of(cid)
            if v and v["source_id"] == source_id and v["seq"] <= new["seq"] and v["id"] != new_version_id:
                mine.append(cid)
            elif v and v["id"] != new_version_id:
                other.append(cid)
        return mine, other

    def find(cid, shift=(0.0, 0.0)):
        c, al = V.clue(cid)
        if c is None:
            return None
        return V.match(c, al, shift)

    links: dict[str, dict] = {}
    kinds = {eid: _kind_of(store, eid) or proposed_kind_of(store, eid) for eid, _ in elements}
    status_of = dict(elements)

    def link(eid, verdict, reason=None, facts=None, basis=None, candidates=None, move=None):
        links[eid] = {"verdict": verdict, "reason": reason, "facts": facts or {}, "basis": basis or {},
                      "candidates": candidates, "move": move}

    def basis_record(eid, mine, other, found, not_found, extra=None):
        d = {"根拠の時点": BASIS_APPROVED if status_of[eid] == STATUS_APPROVED else BASIS_PROPOSED,
             "found": len(found), "not_found": len(not_found), "carried_over": len(other), "total": len(mine) + len(other)}
        if extra:
            d.update(extra)
        return d

    def segment_norm(claim_row):
        s = geometry.segment(loads(claim_row["value_json"]))
        if s is None:
            return None
        vid = claim_row["source_version_id"] or base_version_id
        return (V.to_norm(s[0], vid), V.to_norm(s[1], vid))

    # ---------------------------------------------------------------- elements without a clue of this source: carried over (決定 16)
    for eid, _ in elements:
        mine, other = split_by_source(element_basis(eid))
        if not mine:
            link(eid, "一致", "この出どころの根拠を持たない（持ち越し）", {}, basis_record(eid, mine, other, [], []))

    # ---------------------------------------------------------------- rooms and their boundaries (faces, corners)
    room_face: dict[str, int] = {}
    for eid, _ in elements:
        if kinds[eid] != "部屋":
            continue
        corners = []
        for b in _boundaries(store, eid):
            bc = basis_claims(b).get("線分")
            s = segment_norm(bc) if bc else None
            if s:
                corners.append(base_mesh.find(s[0]))
        corner_set = {c for c in corners if c is not None}
        for fi, f in enumerate(base_mesh.faces):
            if corner_set and {c["node"] for c in f["corners"]} == corner_set:
                room_face[eid] = fi
                break

    face_json = {e.get("base_face"): e for e in mm["json"]["faces"] if "base_face" in e}
    for eid, _ in elements:
        if kinds[eid] != "部屋" or eid in links:
            continue
        mine, other = split_by_source(element_basis(eid))
        found = [c for c in mine if find(c)]
        not_found = [c for c in mine if c not in found]
        fi = room_face.get(eid)
        rec = basis_record(eid, mine, other, found, not_found)
        if fi is None:
            link(eid, "判断できない", "網の目に面がない", {"not_found_clues": not_found}, rec)
            continue
        fv = face_json[fi]["verdict"]
        rec["face"] = face_json[fi]
        if fv == "一致":
            link(eid, "一致", "面が一致", {"not_found_clues": not_found}, rec)
        elif fv in ("分割", "統合"):
            cands = [[V.to_new_coords(new_mesh.nodes[c["node"]], aligned) for c in new_mesh.faces[g]["corners"]]
                     for g in face_json[fi]["new_faces"]]
            link(eid, "判断できない", fv, {"not_found_clues": not_found}, rec, candidates=cands)
        else:
            link(eid, "消えた", fv, {"not_found_clues": not_found}, rec)

    def new_rb_clue(seg_n):
        for b in V.new_clues(aligned):
            line = _line_of(b)
            if line and "ROOM_BOUNDARY" in b["roles"] and all(
                    geometry.distance_to_line(line, p) <= tol and -tol <= geometry.along(line, p) <= geometry.length(line) + tol
                    for p in seg_n):
                return b["id"]
        return None

    room_boundary_ids = set()
    for eid, _ in elements:
        if kinds[eid] != "空間の境界":
            continue
        room = next((r["to_element_id"] for r in relations_from(store, eid, "区切る", include_pending=True)), None)
        if room is None or (kinds.get(room) or _kind_of(store, room)) != "部屋":
            continue
        if eid in links:
            room_boundary_ids.add(eid)
            continue
        room_boundary_ids.add(eid)
        mine, other = split_by_source(element_basis(eid))
        found = [c for c in mine if find(c)]
        not_found = [c for c in mine if c not in found]
        rec = basis_record(eid, mine, other, found, not_found)
        rl = links.get(room)
        if rl is None or rl["verdict"] != "一致":
            link(eid, "判断できない", f"部屋の{(rl or {}).get('reason') or '同定ができない'}", {"room": room}, rec)
            continue
        fi = room_face[room]
        pairs = mm["corner_pairs"].get(fi)
        if pairs is None:
            link(eid, "判断できない", face_json[fi].get("corner_change", "角の対応が取れない"), {"room": room}, rec)
            continue
        bc = basis_claims(eid).get("線分")
        s = segment_norm(bc) if bc else None
        a, b = (base_mesh.find(s[0]), base_mesh.find(s[1])) if s else (None, None)
        if a not in pairs or b not in pairs:
            link(eid, "判断できない", "境界の端が部屋の角にない", {"room": room}, rec)
            continue
        if a in mm["anchor"] and b in mm["anchor"]:
            link(eid, "一致", "両端の角が足場", {"not_found_clues": not_found}, dict(rec, 足場=[base_mesh.nodes[a], base_mesh.nodes[b]]))
            continue
        ns = (new_mesh.nodes[pairs[a]], new_mesh.nodes[pairs[b]])
        evid = new_rb_clue(ns)
        dist = max(math.dist(s[0], ns[0]), math.dist(s[1], ns[1]))
        if evid is None:
            link(eid, "判断できない", "新しい位置の部屋割り線が見つからない", {"room": room}, rec)
            continue
        link(eid, "移動", "部屋が一致し、角が動いた（意味の変更なし）",
             {"移動量_mm": dist, "from": [list(s[0]), list(s[1])], "to": [list(ns[0]), list(ns[1])]}, rec,
             move={"attribute": "線分", "value": [V.to_new_coords(ns[0], aligned), V.to_new_coords(ns[1], aligned)],
                   "unit": bc["unit"] or "mm", "clue": evid, "distance": dist})

    # ---------------------------------------------------------------- lines: walls, grid axes, the outer side's boundaries
    displacement: dict[str, tuple] = {}
    for eid, _ in elements:
        kind = kinds[eid]
        if kind not in LINE_KEY or eid in room_boundary_ids or eid in links:
            continue
        attribute, role = LINE_KEY[kind]
        mine, other = split_by_source(element_basis(eid))
        found = [c for c in mine if find(c)]
        not_found = [c for c in mine if c not in found]
        rec = basis_record(eid, mine, other, found, not_found)
        kc = basis_claims(eid).get(attribute)
        key_clues = [c for c in claim_clues(kc["id"]) if c in mine] if kc else []
        if key_clues and all(c in found for c in key_clues):
            link(eid, "一致", "芯の線が見つかった" if kind == "壁" else "線が見つかった",
                 {"not_found_clues": not_found, "補助の根拠が見つからない": bool(not_found)}, rec)
            displacement[eid] = (0.0, 0.0)
            continue
        s = segment_norm(kc) if kc else None
        if s is None:
            link(eid, "判断できない", "線の言い分がない", {"not_found_clues": not_found}, rec)
            continue
        cands = []
        for c in V.new_clues(aligned):
            line = _line_of(c)
            if not line or role not in c["roles"] or c["id"] in new_used or not _parallel(s, line, tol_deg):
                continue
            off = geometry.distance_to_line(s, line[0])
            if off <= tol or off > move_max:
                continue
            t0, t1 = sorted((geometry.along(s, line[0]), geometry.along(s, line[1])))
            if min(t1, geometry.length(s)) - max(t0, 0.0) <= tol:
                continue
            cands.append((off, c, line))
        if len(cands) > 1:
            same_len = [x for x in cands if abs(geometry.length(x[2]) - geometry.length(s)) <= tol]
            cands = same_len if len(same_len) == 1 else cands
        if not cands:
            link(eid, "消えた", "根拠の線が見つからず、動いた先の線もない", {"not_found_clues": not_found}, rec)
        elif len(cands) > 1:
            link(eid, "判断できない", "動いた先の候補が一つに決まらない", {"not_found_clues": not_found}, rec,
                 candidates=[c["id"] for _, c, _ in cands])
        else:
            off, c, line = cands[0]
            nl = _oriented_like(line, s)
            vec = (nl[0][0] - s[0][0], nl[0][1] - s[0][1])
            # the part across the line (the displacement the wall's openings follow)
            u = (s[1][0] - s[0][0], s[1][1] - s[0][1])
            L = math.hypot(*u) or 1.0
            ux, uy = u[0] / L, u[1] / L
            along_part = vec[0] * ux + vec[1] * uy
            perp = (vec[0] - along_part * ux, vec[1] - along_part * uy)
            displacement[eid] = perp
            link(eid, "移動", "平行に動いた（意味の変更なし）",
                 {"移動量_mm": off, "長さの差_mm": geometry.length(nl) - geometry.length(s), "from": [list(s[0]), list(s[1])],
                  "to": [list(nl[0]), list(nl[1])], "not_found_clues": not_found}, rec,
                 move={"attribute": attribute, "value": [V.to_new_coords(nl[0], aligned), V.to_new_coords(nl[1], aligned)],
                       "unit": kc["unit"] or "mm", "clue": c["id"], "distance": off})
            new_used.add(c["id"])

    # ---------------------------------------------------------------- openings and doors follow their wall (決定 11、例9)
    def wall_of(eid):
        kind = kinds.get(eid)
        if kind == "開口":
            return next((r["to_element_id"] for r in relations_from(store, eid, "くり抜く", include_pending=True)), None)
        if kind == "建具":
            op = next((r["to_element_id"] for r in relations_from(store, eid, "ふさぐ", include_pending=True)), None)
            return wall_of(op) if op else None
        return None

    issues_to_write: list[dict] = []
    for eid, _ in elements:
        if kinds[eid] not in ("開口", "建具") or eid in links:
            continue
        wall = wall_of(eid)
        mine, other = split_by_source(element_basis(eid))
        rec = basis_record(eid, mine, [], [], [])
        d = displacement.get(wall) if wall else None
        if wall is None or d is None:
            found = [c for c in mine if find(c)]
            rec = basis_record(eid, mine, other, found, [c for c in mine if c not in found])
            link(eid, "一致" if len(found) == len(mine) else "判断できない",
                 None if len(found) == len(mine) else "くり抜く壁が同定できない", {}, rec)
            continue
        follow = [c for c in mine if find(c, d)]
        if len(follow) == len(mine):
            rec = basis_record(eid, mine, other, follow, [])
            if d == (0.0, 0.0):
                link(eid, "一致", "壁基準も絶対の位置も同じ", {}, rec)
            else:
                link(eid, "一致", "壁に従う（壁基準の位置が同じ。移動の一覧に入れない）", {"壁の移動_mm": math.hypot(*d)}, rec)
            for c in mine:
                m = find(c, d)
                if m:
                    new_used.add(m)
            continue
        stayed = [c for c in mine if find(c)]
        if stayed and len(stayed) == len(mine):
            wseg = None
            wc = basis_claims(wall).get("芯線")
            if links.get(wall, {}).get("move"):
                f = links[wall]["facts"]["to"]
                wseg = (tuple(f[0]), tuple(f[1]))
            elif wc:
                wseg = segment_norm(wc)
            c0, al = V.clue(stayed[0])
            pt = _points_of(c0)[0] if c0 else None
            thick = effective_value(store, project, wall, "厚さ").value
            try:
                half = float(thick) / 2.0
            except (TypeError, ValueError):
                half = 0.0
            off = geometry.distance_to_line(wseg, pt) if (wseg and pt) else float("inf")
            limit = half + gap
            if off <= limit:
                link(eid, "移動", "壁の中での移動（壁基準の位置が変わった）", {"壁からの距離_mm": off}, rec,
                     move={"attribute": "位置", "value": geometry.along(wseg, pt), "unit": "mm", "clue": find(stayed[0]),
                           "distance": abs(geometry.along(wseg, pt))})
            else:
                link(eid, "判断できない", "建具が壁から外れた", {"壁からの距離_mm": off, "上限_mm": limit, "wall": wall}, rec)
                issues_to_write.append({"kind": "建具が壁から外れた", "subjects": [eid, wall],
                                        "facts": {"壁からの距離_mm": off, "上限_mm": limit,
                                                  "note": "壁が動いたのに、開口・建具の手掛かりが元の位置に残った（v2 Q3・Q6）"}})
            continue
        link(eid, "消えた" if not stayed else "判断できない", "根拠の手掛かりが見つからない", {}, rec)

    # ---------------------------------------------------------------- everything else: by its clues
    for eid, _ in elements:
        if eid in links:
            continue
        mine, other = split_by_source(element_basis(eid))
        found = [c for c in mine if find(c)]
        not_found = [c for c in mine if c not in found]
        rec = basis_record(eid, mine, other, found, not_found)
        if not mine or len(found) == len(mine):
            link(eid, "一致", "根拠の手掛かりがすべて見つかった" if mine else "この出どころの根拠を持たない（持ち越し）",
                 {}, rec)
        elif not found:
            link(eid, "消えた", "根拠の手掛かりが一つも見つからない", {"not_found_clues": not_found}, rec)
        else:
            link(eid, "判断できない", "根拠が変わった（一部が見つからない）", {"not_found_clues": not_found}, rec)

    # ---------------------------------------------------------------- the meaning (案3): same place, other content
    for eid, l in links.items():
        if l["verdict"] == "判断できない" and l["reason"] in ("分割", "統合", "建具が壁から外れた"):
            continue
        mine, _ = split_by_source(element_basis(eid))
        d = displacement.get(wall_of(eid)) or (0.0, 0.0) if kinds.get(eid) in ("開口", "建具") else (0.0, 0.0)
        changed = []
        for cid in mine:
            if find(cid) or find(cid, d):
                continue
            c, al = V.clue(cid)
            if c is None:
                continue
            m = V.changed_in_place(c, al, d) or V.changed_in_place(c, al)
            if m:
                changed.append({"from": cid, "to": m, "was": V._content(c),
                                "now": V._content(next(x for x in V.new_clues(al) if x["id"] == m))})
                new_used.add(m)
        missing = [cid for cid in mine if not (find(cid) or find(cid, d))]
        if changed and len(changed) == len(missing):
            l.update(verdict="意味が変わった", reason="同じ位置の文字・記号の中身が変わった", move=None)
            l["facts"]["変わった手掛かり"] = changed
        elif changed:
            l["facts"]["変わった手掛かり"] = changed

    # ---------------------------------------------------------------- meaning changes spread (案3-1, 案3-2)
    type_changed: list[str] = []
    for eid, l in list(links.items()):
        if l["verdict"] != "意味が変わった":
            continue
        if kinds.get(eid) == "記号の定義":
            for r in store.all("select distinct it.element_id, it.claim_id from interpretation_evidence e join interpretation_item it "
                               "on it.id=e.item_id where e.element_ref_id=?", eid):
                dep = r["element_id"] or (store.scalar("select subject_id from claim where id=?", r["claim_id"]) if r["claim_id"] else None)
                if dep and dep in links and dep != eid:
                    links[dep].update(verdict="意味が変わった", reason="凡例の定義が変わった", move=None)
                    links[dep]["facts"]["凡例の要素"] = eid
        elif kinds.get(eid) in TYPE_KINDS:
            type_changed.append(eid)
    instances: dict[str, str] = {}
    for t in type_changed:
        targets = [t] + [r["to_element_id"] for r in relations_from(store, t, "組み立てを持つ", include_pending=True)]
        for x in targets:
            for r in relations_to(store, x, "型である", include_pending=True) + relations_to(store, x, "使う", include_pending=True):
                instances.setdefault(r["from_element_id"], t)

    # ---------------------------------------------------------------- the scope for the AI (案4) and the candidates for addition
    candidates = [c for c in V.new_clues(aligned) if c["id"] not in new_used and not _explained_by_move(c, links)]
    reinterpret = [eid for eid, l in links.items() if l["verdict"] in ("判断できない", "消えた", "意味が変わった")]
    pts = []
    for c in candidates:
        pts += _points_of(c)
    for eid in reinterpret:
        for cid in split_by_source(element_basis(eid))[0]:
            c, _ = V.clue(cid)
            if c:
                pts += _points_of(c)
    scope = {"clue_ids": [], "context_element_ids": [], "margin_mm": margin, "bbox_mm": None}
    if pts:
        x0, y0 = min(p[0] for p in pts) - margin, min(p[1] for p in pts) - margin
        x1, y1 = max(p[0] for p in pts) + margin, max(p[1] for p in pts) + margin
        scope["bbox_mm"] = [[x0, y0], [x1, y1]]
        inside = lambda p: x0 <= p[0] <= x1 and y0 <= p[1] <= y1
        scope["clue_ids"] = [c["id"] for c in V.new_clues(aligned) if any(inside(p) for p in _points_of(c))]
        for eid, l in links.items():
            if eid in reinterpret:
                continue
            for cid in split_by_source(element_basis(eid))[0]:
                c, _ = V.clue(cid)
                if c and any(inside(p) for p in _points_of(c)):
                    scope["context_element_ids"].append(eid)
                    break

    # ================================================================ writing (rows are appended only)
    agent = store.one("select id from agent where name=? and kind='規則の読み手' and coalesce(version,'')=?", AGENT_NAME, __version__)
    agent_id = agent["id"] if agent else store.insert("agent", recorded_by, name=AGENT_NAME, kind="規則の読み手", model=None,
                                                      version=__version__, instructions_sha256=None)
    names = {r["id"]: f"{r['name']}@{r['seq']}" for r in store.all(
        "select v.id, v.seq, s.name from source_version v join source s on s.id=v.source_id where v.id in (?, ?)",
        base_version_id, new_version_id)}
    interp_id = store.insert("interpretation", recorded_by, source_version_ids_json=dumps([new_version_id]), agent_id=agent_id,
                             scope_json=dumps({"kind": "同定", "base": base_version_id, "new": new_version_id}), premise_json="[]",
                             summary=f"同定 {names.get(base_version_id)} → {names.get(new_version_id)}：移動の新しい位置（意味の変更なし）")
    move_items = []
    for eid, l in links.items():
        mv = l.get("move")
        if l["verdict"] != "移動" or not mv:
            continue
        cid = store.insert("claim", recorded_by, subject_kind="element", subject_id=eid, attribute=mv["attribute"],
                           value_json=dumps(mv["value"]), unit=mv["unit"], mode="観測", statement_kind="記述",
                           source_version_id=new_version_id, interpretation_id=interp_id, review_id=None, agent_id=agent_id,
                           confidence=1.0)
        store.insert("claim_evidence", recorded_by, claim_id=cid, clue_id=mv["clue"], role="主の根拠", reason="同定：移動した先の手掛かり")
        reason = f"移動 {mv['distance']:.1f} mm（意味の変更なし）：{l['reason']}"
        iid = store.insert("interpretation_item", recorded_by, interpretation_id=interp_id, kind=ITEM_KIND, element_id=eid,
                           relation_id=None, claim_id=cid, assumption_id=None, reason=reason, confidence=1.0,
                           rule_check_status="通った", rule_check_reason=None)
        store.insert("interpretation_evidence", recorded_by, item_id=iid, clue_id=mv["clue"], element_ref_id=None, role="主の根拠",
                     reason="同定：移動した先の手掛かり")
        store.insert("rule_check", recorded_by, interpretation_item_id=iid, rule="既存の要素と同じ（同定の移動）", result="通った",
                     detail_json=dumps({"移動量_mm": mv["distance"]}))
        l["item_id"] = iid
        move_items.append(iid)

    counts = {k: 0 for k in ("一致", "移動", "追加", "消えた", "判断できない", "意味が変わった")}
    for l in links.values():
        counts[l["verdict"]] = counts.get(l["verdict"], 0) + 1
    faces = mm["json"]["faces"]
    counts["分割"] = sum(1 for f in faces if f["verdict"] == "分割")
    counts["統合"] = sum(1 for f in faces if f["verdict"] == "統合")
    counts["追加の候補の手掛かり"] = len(candidates)
    counts["自動で処理した数"] = counts["一致"]
    counts["人に渡した数"] = counts["移動"] + counts["消えた"] + counts["判断できない"] + counts["意味が変わった"]
    run_id = store.insert("identity_run", recorded_by, kind="版の間", base_source_version_id=base_version_id,
                          new_source_version_id=new_version_id, frame_json=dumps(frame),
                          rules_table_load_id=latest_load_id(store, "rules", "物件"), mesh_json=dumps(mm["json"]),
                          interpretation_id=interp_id, counts_json=dumps(counts))
    for eid, l in links.items():
        store.insert("identity_link", recorded_by, run_id=run_id, element_id=eid, new_element_id=None,
                     candidates_json=dumps(l["candidates"]) if l["candidates"] is not None else None, verdict=l["verdict"],
                     reason=l["reason"], basis_json=dumps(l["basis"]), facts_json=dumps(l["facts"]), decided_by="自動")

    # recheck marks (G-2, 決定 Q27): judgements on elements that did not stay the same
    marks = 0
    for eid, l in links.items():
        if l["verdict"] == "一致":
            continue
        for c in store.all("select distinct review_id from claim where subject_id=? and mode='採用' and review_id is not null", eid):
            if add_mark(store, recorded_by, c["review_id"], "identity_run", run_id, "根拠の手掛かりが変わった",
                        {"element_id": eid, "verdict": l["verdict"], "reason": l["reason"], "facts": l["facts"]}):
                marks += 1
            l["judged"] = True
    # Q27 の足し: a type whose row changed → the judgements on its instances, even when the instance is 一致
    for inst, t in instances.items():
        for c in store.all("select distinct review_id from claim where subject_id=? and mode='採用' and review_id is not null", inst):
            if add_mark(store, recorded_by, c["review_id"], "source_version", new_version_id, "使っている型の表の行が変わった",
                        {"element_id": inst, "type": t, "identity_run_id": run_id}):
                marks += 1
        store.insert("impact", recorded_by, run_id=run_id, element_id=inst, relation_id=None, reason="表の行が変わった",
                     action="再確認" if store.one("select 1 from claim where subject_id=? and mode='採用'", inst) else "再計算だけ",
                     depth=1)
    # Q27 の足し: a judgement whose premises hold a table row / a sentence of this source that is gone or changed
    for prem in store.all("select distinct p.review_id, p.ref_id from review_premise p join clue c on c.id=p.ref_id "
                          "join source_version v on v.id=c.source_version_id where p.kind='clue' and v.source_id=? "
                          "and c.kind in ('ROW','CELL','SENTENCE','PARAGRAPH')", source_id):
        if not store.one("select 1 from claim where review_id=? and mode='採用'", prem["review_id"]):
            continue
        if find(prem["ref_id"]):
            continue
        if add_mark(store, recorded_by, prem["review_id"], "source_version", new_version_id, "判断の前提の表の行・文が変わった",
                    {"clue_id": prem["ref_id"], "identity_run_id": run_id}):
            marks += 1

    # 向かい合う ends when the room on the other side is split or merged (例1 の参考)
    for eid, l in links.items():
        if eid in room_boundary_ids and l["verdict"] == "判断できない":
            for r in relations_from(store, eid, "向かい合う", include_pending=True) + relations_to(store, eid, "向かい合う", include_pending=True):
                if not store.one("select 1 from relation_end where relation_id=?", r["id"]):
                    store.insert("relation_end", recorded_by, relation_id=r["id"],
                                 reason=f"相手の部屋が{l['reason'].replace('部屋の', '')}（同定 {run_id}）")

    # impact (二段目, 案2): the changed elements, then one step along the relations
    changed = {eid for eid, l in links.items() if l["verdict"] != "一致"}
    for eid in changed:
        l = links[eid]
        action = "再確認" if l.get("judged") or l["verdict"] == "移動" else "再解釈"
        store.insert("impact", recorded_by, run_id=run_id, element_id=eid, relation_id=None,
                     reason="根拠の手掛かりが変わった" if l["verdict"] != "意味が変わった" else "凡例の定義が変わった",
                     action=action, depth=0)
    touched = set()
    for eid in changed:
        for r in relations_from(store, eid, include_pending=True) + relations_to(store, eid, include_pending=True):
            if r["kind"] not in NEIGHBOUR_KINDS:
                continue
            other = r["to_element_id"] if r["from_element_id"] == eid else r["from_element_id"]
            if other in changed or other in touched or other not in links:
                continue
            touched.add(other)
            store.insert("impact", recorded_by, run_id=run_id, element_id=other, relation_id=r["id"],
                         reason="接する要素が変わった", action="再計算だけ", depth=1)
    if candidates:
        store.insert("impact", recorded_by, run_id=run_id, element_id=None, relation_id=None,
                     reason=f"追加の候補の手掛かり {len(candidates)}", action="再解釈", depth=0)

    # issues (I-2): handed to the person
    issues = []

    def issue(kind, subjects, facts, options):
        iid = store.insert("issue", recorded_by, check_run_id=None, identity_run_id=run_id, condition_check_id=None, kind=kind,
                           severity=_severity(rules, kind), subject_ids_json=dumps(subjects), basis_json=dumps({"identity_run": run_id}),
                           facts_json=dumps(facts), proposal_json=None)
        for code, label in options:
            store.insert("issue_option", recorded_by, issue_id=iid, code=code, label=label, effect_json="{}")
        issues.append(iid)

    listable = [l["item_id"] for eid, l in links.items() if l.get("item_id") and not l.get("judged")]
    if listable:
        issue("移動の承認待ち", [store.scalar("select element_id from interpretation_item where id=?", i) for i in listable],
              {"item_ids": listable, "excluded": [l["item_id"] for l in links.values() if l.get("item_id") and l.get("judged")],
               "note": "移動（意味の変更なし）の新しい位置。まとめて承認するまで、有効値は前の承認済みの値のまま（決定 Q1・Q15）"},
              [("batch", "まとめて承認する（btruth approve-moves）"), ("one", "一つずつ見る（btruth approve --item）")])
    for eid, l in links.items():
        if kinds.get(eid) == "部屋" and l["reason"] in ("分割", "統合"):
            subjects = [eid] + [b for b in _boundaries(store, eid)]
            issue("部屋の分割・統合", subjects, {"how": l["reason"], "candidates": l["candidates"],
                                          "note": "ID を引き継がず人に渡す（B-7、H-2）。新しい部屋は AI が読み直して提案する"},
                  [("reread", "新しい部屋として読み直す（AI）"), ("same", "どれかを同じ部屋とする（人）")])
        if l["verdict"] == "消えた" and _severity(rules, f"追加削除.{kinds.get(eid)}") == "要確認":
            issue("消えた要素", [eid], {"kind": kinds.get(eid), "reason": l["reason"]},
                  [("gone", "消えたと認める"), ("reread", "読み直す")])
        if l["verdict"] == "意味が変わった":
            issue("意味が変わった", [eid], l["facts"], [("reread", "読み直す（AI）"), ("keep", "判断を保つ")])
    for x in issues_to_write:
        issue(x["kind"], x["subjects"], x["facts"], [("fix", "図面の修正案（建具を壁に戻す）"), ("move", "壁の中の位置を直す")])

    store.insert("intake_log", recorded_by, source_version_id=new_version_id, kind="座標の枠の揃え方",
                 detail_json=dumps({"base_version": base_version_id, "identity_run_id": run_id, **frame}))
    if candidates:
        store.insert("intake_log", recorded_by, source_version_id=new_version_id, kind="追加の候補",
                     detail_json=dumps({"base_version": base_version_id, "identity_run_id": run_id,
                                        "clue_ids": [c["id"] for c in candidates],
                                        "note": "前の版の要素の根拠にならなかった。AI が読む（案4）"}))
    store.insert("intake_log", recorded_by, source_version_id=new_version_id, kind="AI に渡す範囲",
                 detail_json=dumps({"identity_run_id": run_id, **scope}))
    store.insert("run_summary", recorded_by, kind="同定", counts_json=dumps({"identity_run_id": run_id, **counts,
                                                                          "再確認の印": marks, "要確認": len(issues)}))
    store.commit()
    return IdentityResult(run_id=run_id, interpretation_id=interp_id, counts=counts, mesh=mm["json"], move_items=move_items,
                          issues=issues, links={e: l["verdict"] for e, l in links.items()}, scope=scope)


def _explained_by_move(c, links) -> bool:
    return any((l.get("move") or {}).get("clue") == c["id"] for l in links.values())


def _seq_of(store: Store, version_id: str | None) -> int:
    return store.scalar("select seq from source_version where id=?", version_id) or 0 if version_id else 0


def _boundaries(store: Store, room_id: str) -> list[str]:
    rels = relations_to(store, room_id, "区切る", include_pending=True)
    return [r["from_element_id"] for r in rels]


def latest_run(store: Store) -> str | None:
    return store.scalar("select id from identity_run order by rowid desc limit 1")


def resolve_run(store: Store, prefix: str | None) -> str:
    if not prefix:
        rid = latest_run(store)
        if rid is None:
            raise IdentityError("同定の実行がまだありません")
        return rid
    rows = store.all("select id from identity_run where id like ?", prefix + "%")
    if len(rows) != 1:
        raise IdentityError(f"同定の実行が一つに決まりません: {prefix}（{len(rows)} 件）")
    return rows[0]["id"]


# ====================================================================== identity between sources (B-13, 例2)
def _key_of(store: Store, project: ProjectFolder, eid: str, kind: str) -> dict:
    from btruth.effective import proposed_value
    key = {}
    for a in KEY_ATTRIBUTES.get(kind, ()):
        v = effective_value(store, project, eid, a, through_type=False)
        val = v.value if v.present else proposed_value(store, eid, a)
        if val not in (None, ""):
            key[a] = val
    if kind == "柱":
        grids = set()
        for r in relations_from(store, eid, "載る", include_pending=True):
            g = effective_value(store, project, r["to_element_id"], "符号").value
            from btruth.effective import proposed_value as pv
            grids.add(g if g is not None else pv(store, r["to_element_id"], "符号"))
        if grids:
            key["通り芯"] = sorted(str(g) for g in grids)
    return key


def identify_sources(store: Store, project: ProjectFolder, interpretation_id: str, recorded_by: str = "同定") -> IdentityResult:
    """The elements proposed by one interpretation (a new source) are matched with the elements already there,
    on their keys (符号・室番号・名称) and, for columns, the grid axes they stand on (足場). Same → the new
    source's claims are added to the existing element as items (kind 既存の要素と同じ) waiting for approval, and
    the proposed element counts as merged (computed status; no row is rewritten). Several candidates →
    判断できない, handed to the person. No key or no candidate → 追加 (the proposed element stays)."""
    from btruth.effective import is_approved_element
    interp = store.one("select * from interpretation where id=?", interpretation_id)
    if interp is None:
        raise IdentityError("解釈が見つかりません")
    rules = effective_rules(store, project)
    news = [r["element_id"] for r in store.all("select element_id from interpretation_item where interpretation_id=? and kind='要素を作る' "
                                               "and rule_check_status='通った' order by rowid", interpretation_id)]
    existing = [r["element_id"] for r in store.all("select it.id, it.element_id from interpretation_item it where it.kind='要素を作る' "
                                                   "and it.interpretation_id<>? order by it.rowid", interpretation_id)
                if item_status(store, r["id"]) in LIVE]
    agent = store.one("select id from agent where name=? and kind='規則の読み手' and coalesce(version,'')=?", AGENT_NAME, __version__)
    agent_id = agent["id"] if agent else store.insert("agent", recorded_by, name=AGENT_NAME, kind="規則の読み手", model=None,
                                                      version=__version__, instructions_sha256=None)
    versions = loads(interp["source_version_ids_json"]) or []
    id_interp = store.insert("interpretation", recorded_by, source_version_ids_json=dumps(versions), agent_id=agent_id,
                             scope_json=dumps({"kind": "出どころの間の同定", "interpretation": interpretation_id}), premise_json="[]",
                             summary=f"出どころの間の同定：{interp['summary'] or interpretation_id} の要素を、既にある要素と照らした")
    links, items, issues = [], [], []
    counts = {"一致": 0, "追加": 0, "判断できない": 0}
    for n in news:
        kind = _kind_of(store, n) or proposed_kind_of(store, n)
        key = _key_of(store, project, n, kind)
        if not key or not any(a in key for a in KEY_ATTRIBUTES.get(kind, ())):
            links.append((None, n, "追加", "鍵がない（新しい要素として残す）", {}, None))
            counts["追加"] += 1
            continue
        cands = []
        for e in existing:
            ek = _kind_of(store, e) or proposed_kind_of(store, e)
            if ek != kind:
                continue
            other = _key_of(store, project, e, ek)
            if all(other.get(a) == v for a, v in key.items() if a in other or a != "通り芯") and \
                    all(key.get(a) == v for a, v in other.items() if a in key):
                cands.append(e)
        approved = [c for c in cands if is_approved_element(store, c)]
        cands = approved or cands
        if len(cands) == 1:
            e = cands[0]
            links.append((e, n, "一致", "鍵と足場が同じ", {"足場": key}, None))
            counts["一致"] += 1
            for c in store.all("select * from claim where subject_id=? and mode='観測' and attribute<>'種類' and interpretation_id=? "
                               "order by rowid", n, interpretation_id):
                cid = store.insert("claim", recorded_by, subject_kind="element", subject_id=e, attribute=c["attribute"],
                                   value_json=c["value_json"], unit=c["unit"], mode="観測", statement_kind=c["statement_kind"],
                                   source_version_id=c["source_version_id"], interpretation_id=id_interp, review_id=None,
                                   agent_id=c["agent_id"], confidence=c["confidence"])
                evid = store.all("select clue_id, role, reason from claim_evidence where claim_id=?", c["id"])
                for ev_ in evid:
                    store.insert("claim_evidence", recorded_by, claim_id=cid, clue_id=ev_["clue_id"], role=ev_["role"], reason=ev_["reason"])
                iid = store.insert("interpretation_item", recorded_by, interpretation_id=id_interp, kind=ITEM_KIND, element_id=e,
                                   relation_id=None, claim_id=cid, assumption_id=None,
                                   reason=f"出どころの間の同定：{c['attribute']} を同じ要素に足す（鍵 {dumps(key)}）", confidence=1.0,
                                   rule_check_status="通った", rule_check_reason=None)
                for ev_ in evid:
                    store.insert("interpretation_evidence", recorded_by, item_id=iid, clue_id=ev_["clue_id"], element_ref_id=None,
                                 role=ev_["role"], reason="出どころの間の同定")
                items.append(iid)
        elif len(cands) > 1:
            links.append((None, n, "判断できない", "鍵が重なる", {"足場": key}, cands))
            counts["判断できない"] += 1
        else:
            links.append((None, n, "追加", "同じ鍵の要素がない", {"足場": key}, None))
            counts["追加"] += 1
    counts["自動で処理した数"] = counts["一致"] + counts["追加"]
    counts["人に渡した数"] = counts["判断できない"]
    run_id = store.insert("identity_run", recorded_by, kind="出どころの間", base_source_version_id=None,
                          new_source_version_id=versions[0] if versions else None, frame_json=dumps({"note": "鍵と足場で照らした"}),
                          rules_table_load_id=latest_load_id(store, "rules", "物件"), mesh_json=dumps({}), interpretation_id=id_interp,
                          counts_json=dumps(counts))
    for e, n, verdict, reason, basis, cands in links:
        store.insert("identity_link", recorded_by, run_id=run_id, element_id=e, new_element_id=n,
                     candidates_json=dumps(cands) if cands else None, verdict=verdict, reason=reason, basis_json=dumps(basis),
                     facts_json="{}", decided_by="自動")
        if verdict == "判断できない":
            iid = store.insert("issue", recorded_by, check_run_id=None, identity_run_id=run_id, condition_check_id=None,
                               kind="同じ要素か判断できない", severity=_severity(rules, "同じ要素か判断できない"),
                               subject_ids_json=dumps([n] + cands), basis_json=dumps(basis), facts_json=dumps({"candidates": cands}),
                               proposal_json=None)
            for code, label in (("new", "別の要素とする（新しい要素を承認）"), ("same", "どれかと同じとする（人）")):
                store.insert("issue_option", recorded_by, issue_id=iid, code=code, label=label, effect_json="{}")
            issues.append(iid)
    store.insert("run_summary", recorded_by, kind="出どころの間の同定", counts_json=dumps({"identity_run_id": run_id, **counts}))
    store.commit()
    return IdentityResult(run_id=run_id, interpretation_id=id_interp, counts=counts, mesh={}, move_items=items, issues=issues,
                          links={n: v for _, n, v, *_ in links})
