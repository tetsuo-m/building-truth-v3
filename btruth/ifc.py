"""The IFC output (design 3-8; IFC4 ADD2 TC1, schema identifier 'IFC4'), written with the standard library.

Only approved elements are exported, with their effective values (3-8-2, Q18). What is decided here:
  * GlobalId (3-8-4 (a)): an element's UUID in IFC's 22-character form (compress_guid). What has no row of its own
    — a boundary split by its partners, a virtual element, a relation that IFC groups (IfcRelAggregates,
    IfcRelContainedInSpatialStructure, IfcRelDefinesByType, property sets) — gets a name-based UUID (v5) of fixed
    parts: the same parts give the same GlobalId every time;
  * the DB's id: BT_Common.ElementId on every product and type; a mapping CSV next to the IFC leads from every
    GlobalId (or material name) back to the DB's ids — relations and materials carry no properties (決定 17);
  * coordinates: the stored values shifted to the frame of the grid labels (as shown to the person), in mm;
  * heights: the storey's 階高, else default_storey_height_mm with BT_Common.HeightAssumed = true (Q23);
  * open issues: the effective value is exported and BT_Common.HasOpenIssue = true (Q18);
  * the delivery requirements (conditions of category 受け渡しの要件) are checked first; not met → no IFC (IfcStopped)
    until a person allowed it (`allow-ifc`, a review on the stopped generation; L-2).
"""
from __future__ import annotations

import csv
import math
import uuid
from pathlib import Path

from btruth import __version__, geometry
from btruth.common import dumps, loads, new_id, now_iso, sha256_of
from btruth.effective import (_kind_of, approved_elements_by_kind, effective_name, effective_value, open_issues,
                              relations_from, relations_to, room_area_m2, room_ring)
from btruth.project import ProjectFolder
from btruth.store import Store
from btruth.tables import effective_rows, effective_rules

CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$"
NAMESPACE = uuid.UUID("6f1c2b3a-9d4e-5b7f-8a1c-2e3d4f5a6b7c")       # fixed for this DB's derived GlobalIds (3-8-4 (a))


class IfcStopped(Exception):
    def __init__(self, message: str, generation_id: str, failures: list):
        super().__init__(message)
        self.generation_id = generation_id
        self.failures = failures


# ====================================================================== GlobalId
def compress_guid(u: str) -> str:
    n = uuid.UUID(str(u)).int
    out = []
    for _ in range(22):
        out.append(CHARS[n & 63])
        n >>= 6
    return "".join(reversed(out))


def expand_guid(g: str) -> str:
    n = 0
    for ch in g:
        n = n * 64 + CHARS.index(ch)
    return str(uuid.UUID(int=n))


def derived_guid(*parts) -> str:
    return compress_guid(str(uuid.uuid5(NAMESPACE, "|".join(str(p) for p in parts))))


# ====================================================================== STEP writing
class Ref(int):
    pass


class Enum(str):
    pass


class Typed:
    def __init__(self, name: str, value):
        self.name, self.value = name, value


STAR = object()


def _string(s: str) -> str:
    out = []
    for ch in s:
        o = ord(ch)
        if ch == "'":
            out.append("''")
        elif ch == "\\":
            out.append("\\\\")
        elif 32 <= o < 127:
            out.append(ch)
        else:
            units = ch.encode("utf-16-be")
            out.append("\\X2\\" + units.hex().upper() + "\\X0\\")
    return "'" + "".join(out) + "'"


def _real(x: float) -> str:
    x = float(x)
    if x == int(x) and abs(x) < 1e15:
        return f"{int(x)}."
    t = repr(x)
    return t.replace("e", "E") if "." in t else t.replace("e", ".E")


def fmt(a) -> str:
    if a is None:
        return "$"
    if a is STAR:
        return "*"
    if isinstance(a, Ref):
        return f"#{int(a)}"
    if isinstance(a, Enum):
        return f".{a}."
    if isinstance(a, bool):
        return ".T." if a else ".F."
    if isinstance(a, Typed):
        return f"{a.name}({fmt(a.value)})"
    if isinstance(a, int):
        return str(a)
    if isinstance(a, float):
        return _real(a)
    if isinstance(a, str):
        return _string(a)
    if isinstance(a, (list, tuple)):
        return "(" + ",".join(fmt(x) for x in a) + ")"
    raise TypeError(type(a))


class Step:
    def __init__(self):
        self.lines: list[str] = []

    def add(self, typ: str, *args) -> Ref:
        n = len(self.lines) + 1
        self.lines.append(f"#{n}={typ}({','.join(fmt(a) for a in args)});")
        return Ref(n)

    def text(self, name: str) -> str:
        head = ["ISO-10303-21;", "HEADER;", "FILE_DESCRIPTION(('ViewDefinition [ReferenceView_V1.2]'),'2;1');",
                f"FILE_NAME({_string(name)},{_string(now_iso())},(''),(''),{_string('btruth ' + __version__)},'btruth','');",
                "FILE_SCHEMA(('IFC4'));", "ENDSEC;", "DATA;"]
        return "\n".join(head + self.lines + ["ENDSEC;", "END-ISO-10303-21;", ""])


# ====================================================================== the export
def _frame(store: Store) -> dict:
    from btruth.display import frame_of_version
    for c in store.all("select source_version_id from claim where attribute in ('芯線','線分') and source_version_id is not null order by rowid"):
        f = frame_of_version(store, c["source_version_id"])
        if f:
            return f
    return {"x": 0.0, "y": 0.0, "uf": 1.0, "labels": None, "version": None}


def _delivery_check(store: Store, project: ProjectFolder, recorded_by: str, generation_id: str, out: Path):
    from btruth.conditions import check_conditions, latest_conditions
    if not latest_conditions(store, "受け渡しの要件"):
        return []
    results = check_conditions(store, project, recorded_by, category="受け渡しの要件", generation_id=generation_id)
    return [r for r in results if r["result"] != "満たす"]


def export_ifc(store: Store, project: ProjectFolder, out: Path, recorded_by: str = "IFC の出口",
               generation_id: str | None = None) -> dict:
    out = Path(out)
    allowed_by = None
    if generation_id:
        rows = store.all("select id from generation where id like ? and kind='IFC'", generation_id + "%")
        if len(rows) != 1:
            raise ValueError(f"止めた IFC の生成が一つに決まりません: {generation_id}")
        generation_id = rows[0]["id"]
        r = store.one("select id from review where target_kind='generation' and target_id=? and action='それでも出す' order by rowid desc limit 1",
                      generation_id)
        if r is None:
            raise IfcStopped("人の「それでも出す」の判断がない（`btruth allow-ifc`）", generation_id, [])
        allowed_by = r["id"]
    else:
        gid = new_id()
        failures = _delivery_check(store, project, recorded_by, gid, out)
        if failures:
            store.insert("generation", recorded_by, id=gid, kind="IFC", as_of_json=dumps({"at": now_iso(), "止めた": True}),
                         path=str(out), sha256=None, marker_json=dumps({"止めた": "受け渡しの要件を満たさない", "件数": len(failures)}))
            store.commit()
            raise IfcStopped(f"受け渡しの要件を満たさないので IFC を出さない（{len(failures)} 件）", gid, failures)
    rules = effective_rules(store, project)
    default_h = float(rules.get("default_storey_height_mm", "2700"))
    fr = _frame(store)
    by_kind = approved_elements_by_kind(store, project)
    approved = {e for es in by_kind.values() for e in es}
    issue_kinds: dict[str, set] = {}
    for i in open_issues(store, project):
        for s in i["subject_ids"]:
            issue_kinds.setdefault(s, set()).add(i["kind"])
    S = Step()
    mapping: list[dict] = []
    ent: dict[str, Ref] = {}
    placement: dict[str, Ref] = {}
    height_assumed: list[str] = []

    def P(p):
        return ((float(p[0]) * fr["uf"] - fr["x"]), (float(p[1]) * fr["uf"] - fr["y"]))

    def m(ifc_type, gid, db_id, **kw):
        row = {"ifc_type": ifc_type, "global_id": gid, "name": kw.get("name", ""), "db_id": db_id or "", "relating": kw.get("relating", ""),
               "has_element_id": kw.get("has_element_id", "no"), "has_open_issue": "yes" if db_id in issue_kinds else "no",
               "boundary_id": kw.get("boundary_id", ""), "partner_id": kw.get("partner_id", ""), "interval_no": kw.get("interval_no", ""),
               "parent_id": kw.get("parent_id", ""), "note": kw.get("note", "")}
        mapping.append(row)

    # --- shared geometry, context, units
    o3 = S.add("IFCCARTESIANPOINT", (0.0, 0.0, 0.0))
    dz = S.add("IFCDIRECTION", (0.0, 0.0, 1.0))
    dx = S.add("IFCDIRECTION", (1.0, 0.0, 0.0))
    world = S.add("IFCAXIS2PLACEMENT3D", o3, dz, dx)
    ctx = S.add("IFCGEOMETRICREPRESENTATIONCONTEXT", None, "Model", 3, 1.0e-5, world, None)
    body = S.add("IFCGEOMETRICREPRESENTATIONSUBCONTEXT", "Body", "Model", STAR, STAR, STAR, STAR, ctx, None, Enum("MODEL_VIEW"), None)
    units = S.add("IFCUNITASSIGNMENT", [S.add("IFCSIUNIT", STAR, Enum("LENGTHUNIT"), Enum("MILLI"), Enum("METRE")),
                                        S.add("IFCSIUNIT", STAR, Enum("AREAUNIT"), None, Enum("SQUARE_METRE")),
                                        S.add("IFCSIUNIT", STAR, Enum("VOLUMEUNIT"), None, Enum("CUBIC_METRE")),
                                        S.add("IFCSIUNIT", STAR, Enum("PLANEANGLEUNIT"), None, Enum("RADIAN"))])

    def local(rel, at=(0.0, 0.0), direction=(1.0, 0.0), z=0.0):
        pt = S.add("IFCCARTESIANPOINT", (float(at[0]), float(at[1]), float(z)))
        d = S.add("IFCDIRECTION", (float(direction[0]), float(direction[1]), 0.0))
        return S.add("IFCLOCALPLACEMENT", rel, S.add("IFCAXIS2PLACEMENT3D", pt, dz, d))

    def extruded(profile, depth):
        solid = S.add("IFCEXTRUDEDAREASOLID", profile, S.add("IFCAXIS2PLACEMENT3D", o3, dz, dx), dz, float(depth))
        rep = S.add("IFCSHAPEREPRESENTATION", body, "Body", "SweptSolid", [solid])
        return S.add("IFCPRODUCTDEFINITIONSHAPE", None, None, [rep])

    def rect(length, width):
        c = S.add("IFCCARTESIANPOINT", (float(length) / 2.0, 0.0))
        return S.add("IFCRECTANGLEPROFILEDEF", Enum("AREA"), None, S.add("IFCAXIS2PLACEMENT2D", c, None), float(length), float(width))

    def name_of(eid):
        return effective_name(store, project, eid)

    def pvalue(name, value, vtype):
        if vtype == "bool":
            return S.add("IFCPROPERTYSINGLEVALUE", name, None, Typed("IFCBOOLEAN", bool(value)), None)
        if vtype in ("length_mm",):
            try:
                return S.add("IFCPROPERTYSINGLEVALUE", name, None, Typed("IFCLENGTHMEASURE", float(value)), None)
            except (TypeError, ValueError):
                return None
        if vtype == "json":
            return S.add("IFCPROPERTYSINGLEVALUE", name, None, Typed("IFCTEXT", dumps(value)), None)
        if isinstance(value, (dict, list)):
            return None
        return S.add("IFCPROPERTYSINGLEVALUE", name, None, Typed("IFCLABEL", str(value)), None)

    def property_sets(e, kind) -> dict:
        psets: dict[str, list] = {}
        bt = [S.add("IFCPROPERTYSINGLEVALUE", "ElementId", None, Typed("IFCIDENTIFIER", e), None)]
        if e in issue_kinds:
            bt.append(S.add("IFCPROPERTYSINGLEVALUE", "HasOpenIssue", None, Typed("IFCBOOLEAN", True), None))
            bt.append(S.add("IFCPROPERTYSINGLEVALUE", "OpenIssueKinds", None, Typed("IFCTEXT", "、".join(sorted(issue_kinds[e]))), None))
        if e in height_assumed:
            bt.append(S.add("IFCPROPERTYSINGLEVALUE", "HeightAssumed", None, Typed("IFCBOOLEAN", True), None))
        psets["BT_Common"] = bt
        for row in effective_rows(store, project, "attributes"):
            pset, prop = (row.get("ifc_pset") or "").strip(), (row.get("ifc_property") or "").strip()
            if not pset or not prop or pset.startswith("Qto_") or row.get("applies_to") not in (kind, "*") or prop == "ElementId":
                continue
            v = effective_value(store, project, e, row["attribute"])
            if not v.present:
                continue
            pv = pvalue(prop, v.value, (row.get("value_type") or "").strip())
            if pv is not None:
                psets.setdefault(pset, []).append(pv)
        return psets

    # --- the spatial structure (E-7, C-2b)
    def one(kind):
        es = by_kind.get(kind) or []
        return es[0] if es else None

    proj, site, bldg, storey, outside = one("物件"), one("敷地"), one("建物"), one("階"), one("外部")
    ent[proj] = S.add("IFCPROJECT", compress_guid(proj), None, name_of(proj) or "物件", None, None, None, None, [ctx], units)
    m("IfcProject", compress_guid(proj), proj, has_element_id="yes")
    placement[site] = local(None)
    ent[site] = S.add("IFCSITE", compress_guid(site), None, name_of(site), None, None, placement[site], None, None, Enum("ELEMENT"),
                      None, None, None, None, None)
    placement[bldg] = local(placement[site])
    ent[bldg] = S.add("IFCBUILDING", compress_guid(bldg), None, name_of(bldg), None, None, placement[bldg], None, None, Enum("ELEMENT"),
                      None, None, None)
    placement[storey] = local(placement[bldg])
    sh = effective_value(store, project, storey, "階高")
    storey_h = float(sh.value) if sh.present else default_h
    assumed = not sh.present
    ent[storey] = S.add("IFCBUILDINGSTOREY", compress_guid(storey), None, name_of(storey), None, None, placement[storey], None, None,
                        Enum("ELEMENT"), 0.0)
    for e, t in ((site, "IfcSite"), (bldg, "IfcBuilding"), (storey, "IfcBuildingStorey")):
        m(t, compress_guid(e), e, has_element_id="yes")
    if outside:
        ent[outside] = S.add("IFCEXTERNALSPATIALELEMENT", compress_guid(outside), None, name_of(outside) or "外部", None, None,
                             local(placement[site]), None, None, Enum("EXTERNAL"))
        m("IfcExternalSpatialElement", compress_guid(outside), outside, has_element_id="yes")

    # --- rooms (IfcSpace)
    for room in by_kind.get("部屋") or []:
        ring = room_ring(store, project, room)
        ch = effective_value(store, project, room, "天井高")
        h = float(ch.value) if ch.present else storey_h
        if not ch.present and assumed:
            height_assumed.append(room)
        shape = None
        if ring:
            pts = [S.add("IFCCARTESIANPOINT", P(p)) for p in ring]
            poly = S.add("IFCPOLYLINE", pts + [pts[0]])
            shape = extruded(S.add("IFCARBITRARYCLOSEDPROFILEDEF", Enum("AREA"), None, poly), h)
        num = effective_value(store, project, room, "室番号")
        long = effective_value(store, project, room, "室名")
        ent[room] = S.add("IFCSPACE", compress_guid(room), None, str(num.value) if num.present else (name_of(room) or ""), None, None,
                          local(placement[storey]), shape, long.value if long.present else None, Enum("ELEMENT"), Enum("SPACE"), None)
        m("IfcSpace", compress_guid(room), room, has_element_id="yes")

    # --- grid
    axes_u, axes_v = [], []
    for g in by_kind.get("通り芯") or []:
        v = effective_value(store, project, g, "線分")
        seg = geometry.segment(v.value) if v.present else None
        tag = effective_value(store, project, g, "符号").value
        if not seg:
            continue
        a, b = P(seg[0]), P(seg[1])
        axis = S.add("IFCGRIDAXIS", str(tag or ""), S.add("IFCPOLYLINE", [S.add("IFCCARTESIANPOINT", a), S.add("IFCCARTESIANPOINT", b)]), True)
        (axes_u if abs(b[0] - a[0]) < abs(b[1] - a[1]) else axes_v).append(axis)
        m("IfcGridAxis", "", g, name=str(tag or ""), note="軸の符号で引く（GlobalId がない）")
    contained: list[Ref] = []
    if axes_u and axes_v:
        grid = S.add("IFCGRID", derived_guid(proj, "通り芯"), None, "通り芯", None, None, local(placement[storey]), None, axes_u, axes_v,
                     None, Enum("RECTANGULAR"))
        contained.append(grid)
        m("IfcGrid", derived_guid(proj, "通り芯"), proj, note="通り芯の要素をまとめた一つの格子")

    # --- types (their property sets go into HasPropertySets: IFC4 does not let IfcRelDefinesByProperties point at a type)
    attr_rows = effective_rows(store, project, "attributes")
    type_ids = set()
    for kind, typ in (("壁種", "IFCWALLTYPE"), ("建具の型", "IFCDOORTYPE"), ("柱の型", "IFCCOLUMNTYPE")):
        for t in by_kind.get(kind) or []:
            type_ids.add(t)
            tag = effective_value(store, project, t, "符号").value
            g = compress_guid(t)
            psets = [S.add("IFCPROPERTYSET", derived_guid(t, pset), None, pset, None, props)
                     for pset, props in property_sets(t, kind).items()]
            if typ == "IFCWALLTYPE":
                ent[t] = S.add(typ, g, None, str(tag or name_of(t) or ""), None, None, psets, None, str(tag or ""), None, Enum("NOTDEFINED"))
            elif typ == "IFCDOORTYPE":
                ent[t] = S.add(typ, g, None, str(tag or ""), None, None, psets, None, str(tag or ""), None, Enum("DOOR"), Enum("NOTDEFINED"),
                               None, None)
            else:
                ent[t] = S.add(typ, g, None, str(tag or ""), None, None, psets, None, str(tag or ""), None, Enum("COLUMN"))
            m({"IFCWALLTYPE": "IfcWallType", "IFCDOORTYPE": "IfcDoorType", "IFCCOLUMNTYPE": "IfcColumnType"}[typ], g, t, has_element_id="yes")

    # --- walls
    wall_geo: dict[str, tuple] = {}
    for w in by_kind.get("壁") or []:
        v = effective_value(store, project, w, "芯線")
        seg = geometry.segment(v.value) if v.present else None
        th = effective_value(store, project, w, "厚さ")
        t = float(th.value) if th.present else 100.0
        shape, pl = None, local(placement[storey])
        if seg:
            a, b = P(seg[0]), P(seg[1])
            L = math.dist(a, b)
            u = ((b[0] - a[0]) / L, (b[1] - a[1]) / L) if L else (1.0, 0.0)
            pl = local(placement[storey], a, u)
            shape = extruded(rect(L, t), storey_h)
            wall_geo[w] = (a, u, t, pl)
        if assumed:
            height_assumed.append(w)
        tag = effective_value(store, project, w, "壁種").value
        ent[w] = S.add("IFCWALL", compress_guid(w), None, name_of(w) or "壁", None, None, pl, shape, str(tag) if tag else None,
                       Enum("NOTDEFINED"))
        m("IfcWall", compress_guid(w), w, has_element_id="yes")

    # --- columns
    for c in by_kind.get("柱") or []:
        pos = effective_value(store, project, c, "位置")
        at = P(pos.value) if pos.present and isinstance(pos.value, list) else (0.0, 0.0)
        tag = effective_value(store, project, c, "符号", through_type=False).value
        ent[c] = S.add("IFCCOLUMN", compress_guid(c), None, str(tag or "柱"), None, None, local(placement[storey], at), None,
                       str(tag) if tag else None, Enum("COLUMN"))
        m("IfcColumn", compress_guid(c), c, has_element_id="yes")

    # --- openings and doors (C-2d: the absolute position is computed from the wall's centre line)
    from btruth.propose import opening_segment
    for o in by_kind.get("開口") or []:
        seg = opening_segment(store, project, o)
        wall = next((r["to_element_id"] for r in relations_from(store, o, "くり抜く")), None)
        hh = effective_value(store, project, o, "高さ")
        h = float(hh.value) if hh.present else storey_h
        shape, pl = None, local(placement[storey])
        if seg:
            a, b = P(seg[0]), P(seg[1])
            L = math.dist(a, b)
            u = ((b[0] - a[0]) / L, (b[1] - a[1]) / L) if L else (1.0, 0.0)
            t = wall_geo.get(wall, (None, None, 100.0, None))[2]
            pl = local(placement[storey], a, u)
            shape = extruded(rect(L, t + 20.0), h)
        ent[o] = S.add("IFCOPENINGELEMENT", compress_guid(o), None, "開口", None, None, pl, shape, None, Enum("OPENING"))
        placement[o] = pl
        m("IfcOpeningElement", compress_guid(o), o, has_element_id="yes")
    for d in by_kind.get("建具") or []:
        op = next((r["to_element_id"] for r in relations_from(store, d, "ふさぐ")), None)
        w = effective_value(store, project, op, "幅") if op else None
        h = effective_value(store, project, op, "高さ") if op else None
        tag = effective_value(store, project, d, "符号", through_type=False).value
        kind = str(effective_value(store, project, d, "建具の種類").value or "")
        pl = placement.get(op) or local(placement[storey])
        args = (compress_guid(d), None, str(tag or "建具"), None, None, pl, None, str(tag) if tag else None,
                float(h.value) if h and h.present else None, float(w.value) if w and w.present else None)
        if "窓" in kind:
            ent[d] = S.add("IFCWINDOW", *args, Enum("WINDOW"), None, None)
            m("IfcWindow", compress_guid(d), d, has_element_id="yes")
        else:
            ent[d] = S.add("IFCDOOR", *args, Enum("DOOR"), None, None)
            m("IfcDoor", compress_guid(d), d, has_element_id="yes")

    # --- relations: aggregation, containment, voids, fills, types (3-8-4 (e))
    parents: dict[str, list] = {}
    for e in list(ent):
        for r in relations_from(store, e, "集める", approved_only=False):     # the default structure has no item (C-2b)
            if r["to_element_id"] in ent:
                parents.setdefault(r["to_element_id"], []).append((e, r["id"]))
    for parent, kids in parents.items():
        g = derived_guid(parent, "集める")
        S.add("IFCRELAGGREGATES", g, None, None, None, ent[parent], [ent[k] for k, _ in kids])
        m("IfcRelAggregates", g, parent, parent_id=parent, note="relation " + " ".join(r for _, r in kids))
    for e in list(ent):
        if _kind_of(store, e) == "開口":
            continue                                      # openings are not in the spatial structure (改訂 6)
        for r in relations_from(store, e, "含む"):
            if r["to_element_id"] == storey:
                contained.append(ent[e])
    if contained:
        g = derived_guid(storey, "含む")
        S.add("IFCRELCONTAINEDINSPATIALSTRUCTURE", g, None, None, None, contained, ent[storey])
        m("IfcRelContainedInSpatialStructure", g, storey, parent_id=storey)
    for o in by_kind.get("開口") or []:
        for r in relations_from(store, o, "くり抜く"):
            if r["to_element_id"] in ent:
                S.add("IFCRELVOIDSELEMENT", compress_guid(r["id"]), None, None, None, ent[r["to_element_id"]], ent[o])
                m("IfcRelVoidsElement", compress_guid(r["id"]), r["id"], note=f"{r['to_element_id']} ← {o}")
    for d in (by_kind.get("建具") or []):
        for r in relations_from(store, d, "ふさぐ"):
            if r["to_element_id"] in ent:
                S.add("IFCRELFILLSELEMENT", compress_guid(r["id"]), None, None, None, ent[r["to_element_id"]], ent[d])
                m("IfcRelFillsElement", compress_guid(r["id"]), r["id"], note=f"{r['to_element_id']} ← {d}")
    typed: dict[str, list] = {}
    for e in list(ent):
        for r in relations_from(store, e, "型である"):
            if r["to_element_id"] in ent:
                typed.setdefault(r["to_element_id"], []).append((e, r["id"]))
    for t, objs in typed.items():
        g = derived_guid(t, "型である")
        S.add("IFCRELDEFINESBYTYPE", g, None, None, None, [ent[o] for o, _ in objs], ent[t])
        m("IfcRelDefinesByType", g, t, parent_id=t, note="一つの型に一つの関係（IFC の決まり。Q33）。relation " + " ".join(r for _, r in objs))

    # --- materials (C-3; no GlobalId → the mapping by name)
    from btruth.consistency import layers_of
    for t in by_kind.get("壁種") or []:
        asm = next((r["to_element_id"] for r in relations_from(store, t, "組み立てを持つ")), None)
        if not asm:
            continue
        layers = []
        mats: dict[str, Ref] = {}
        for r in relations_from(store, asm, "層である"):
            role = loads(r["role_json"]) or {}
            mid = r["to_element_id"]
            mname = str(effective_value(store, project, mid, "名称").value or mid[:8])
            if mname not in mats:
                mats[mname] = S.add("IFCMATERIAL", mname, None, None)
                m("IfcMaterial", "", mid, name=mname)
            thick = float(role.get("厚さ") or 0) * float(role.get("枚数") or 1)
            layers.append((role.get("順") or 0, S.add("IFCMATERIALLAYER", mats[mname], thick, None, f"{role.get('面') or ''}", None, None, None)))
        layers.sort(key=lambda x: x[0])
        lname = str(effective_name(store, project, asm) or asm)
        ls = S.add("IFCMATERIALLAYERSET", [x[1] for x in layers], lname, None)
        m("IfcMaterialLayerSet", "", asm, name=lname)
        g = derived_guid(t, "材料")
        S.add("IFCRELASSOCIATESMATERIAL", g, None, None, None, [ent[t]], ls)
        m("IfcRelAssociatesMaterial", g, t, parent_id=t)

    # --- space boundaries per interval (3-8-4 (a)(b), C-2c)
    from btruth.consistency import boundary_intervals
    gap = float(rules.get("gap_tol_mm", "50"))
    virtual_done: dict[str, Ref] = {}
    for b in by_kind.get("空間の境界") or []:
        space = next((r["to_element_id"] for r in relations_from(store, b, "区切る")), None)
        if space not in ent:
            continue
        iv = boundary_intervals(store, project, b)
        if iv["segment"] is None:
            continue
        L = geometry.length(iv["segment"])
        pieces = []
        per_partner: dict[str, int] = {}
        for pid, (a, z) in sorted(iv["walls"] + iv["openings"], key=lambda x: x[1][0]):
            per_partner[pid] = per_partner.get(pid, 0) + 1
            pieces.append((pid, per_partner[pid], a, z))
        covered = [(a, z) for _, _, a, z in pieces]
        holes = geometry.gaps((0.0, L), covered, gap)
        facing = [r["to_element_id"] if r["from_element_id"] == b else r["from_element_id"]
                  for r in relations_from(store, b, "向かい合う") + relations_to(store, b, "向かい合う")]
        external = _kind_of(store, space) == "外部" or any(
            _kind_of(store, next((r["to_element_id"] for r in relations_from(store, f, "区切る")), None) or "") == "外部" for f in facing)
        split = len(pieces) + len(holes) > 1
        relating = "外部" if _kind_of(store, space) == "外部" else "部屋"
        for pid, k, a, z in pieces:
            phys = Enum("VIRTUAL") if _kind_of(store, pid) == "開口" else Enum("PHYSICAL")
            g = derived_guid(b, pid, k) if split else compress_guid(b)
            S.add("IFCRELSPACEBOUNDARY", g, None, None, None, ent[space], ent.get(pid), None, phys,
                  Enum("EXTERNAL") if external else Enum("INTERNAL"))
            m("IfcRelSpaceBoundary", g, b, relating=relating, boundary_id=b, partner_id=pid, interval_no=k,
              note=f"区間 {a:g}〜{z:g} mm（境界の始点から）")
        for k, (a, z) in enumerate(holes, start=1):
            pair = sorted([b] + facing[:1])
            key = "|".join(pair) + f"|{k}"
            if key not in virtual_done:
                vg = derived_guid(*pair, "仮想の要素", k)
                virtual_done[key] = S.add("IFCVIRTUALELEMENT", vg, None, "仮想の境界", None, None, None, None, None)
                m("IfcVirtualElement", vg, b, boundary_id=b, interval_no=k, has_element_id="yes")
            g = derived_guid(b, "相手なし", k) if split else compress_guid(b)
            S.add("IFCRELSPACEBOUNDARY", g, None, None, None, ent[space], virtual_done[key], None, Enum("VIRTUAL"),
                  Enum("EXTERNAL") if external else Enum("INTERNAL"))
            m("IfcRelSpaceBoundary", g, b, relating=relating, boundary_id=b, partner_id="相手なし", interval_no=k,
              note=f"相手のない区間 {a:g}〜{z:g} mm")

    # --- properties (attributes.csv's ifc_pset), BT_Common, quantities (computed, B-10)
    targets = list(ent.items())                     # the project too (IfcContext carries property sets in IFC4)
    for e, ref in targets:
        kind = _kind_of(store, e)
        if e in type_ids:
            continue                                # in HasPropertySets
        for pset, props in property_sets(e, kind).items():
            ps = S.add("IFCPROPERTYSET", derived_guid(e, pset), None, pset, None, props)
            S.add("IFCRELDEFINESBYPROPERTIES", derived_guid(e, pset, "関係"), None, None, None, [ref], ps)
        if kind == "部屋":
            qs = []
            area = room_area_m2(store, project, e)
            if area is not None:
                qs.append(S.add("IFCQUANTITYAREA", "NetFloorArea", None, None, float(area), None))
            ch = effective_value(store, project, e, "天井高")
            if ch.present:
                qs.append(S.add("IFCQUANTITYLENGTH", "Height", None, None, float(ch.value), None))
            if qs:
                q = S.add("IFCELEMENTQUANTITY", derived_guid(e, "Qto_SpaceBaseQuantities"), None, "Qto_SpaceBaseQuantities", None, None, qs)
                S.add("IFCRELDEFINESBYPROPERTIES", derived_guid(e, "Qto_SpaceBaseQuantities", "関係"), None, None, None, [ref], q)
        if kind == "壁" and e in wall_geo:
            v = effective_value(store, project, e, "芯線")
            seg = geometry.segment(v.value)
            qs = [S.add("IFCQUANTITYLENGTH", "Length", None, None, float(geometry.length(seg)), None),
                  S.add("IFCQUANTITYLENGTH", "Width", None, None, float(wall_geo[e][2]), None),
                  S.add("IFCQUANTITYLENGTH", "Height", None, None, float(storey_h), None)]
            q = S.add("IFCELEMENTQUANTITY", derived_guid(e, "Qto_WallBaseQuantities"), None, "Qto_WallBaseQuantities", None, None, qs)
            S.add("IFCRELDEFINESBYPROPERTIES", derived_guid(e, "Qto_WallBaseQuantities", "関係"), None, None, None, [ref], q)
    for key, vref in virtual_done.items():
        b = key.split("|")[0]
        ps = S.add("IFCPROPERTYSET", derived_guid(key, "BT_Common"), None, "BT_Common",
                   None, [S.add("IFCPROPERTYSINGLEVALUE", "ElementId", None, Typed("IFCIDENTIFIER", b), None)])
        S.add("IFCRELDEFINESBYPROPERTIES", derived_guid(key, "BT_Common", "関係"), None, None, None, [vref], ps)

    # --- the documents the effective values came from (IfcDocumentReference)
    docs: dict[str, list] = {}
    for e, ref in targets:
        for r in store.all("select distinct source_version_id from claim where subject_id=? and mode='観測' and source_version_id is not null", e):
            docs.setdefault(r["source_version_id"], []).append(ref)
    for vid, refs in docs.items():
        v = store.one("select v.seq, v.file_name, v.archive_path, s.name from source_version v join source s on s.id=v.source_id where v.id=?", vid)
        if not v:
            continue
        dr = S.add("IFCDOCUMENTREFERENCE", v["archive_path"], f"{v['name']}@{v['seq']}", v["file_name"], None, None)
        g = derived_guid(vid, "書類")
        S.add("IFCRELASSOCIATESDOCUMENT", g, None, None, None, list(dict.fromkeys(refs)), dr)
        m("IfcRelAssociatesDocument", g, vid, name=f"{v['name']}@{v['seq']}", note="出どころの版")

    # --- write
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(S.text(out.name), encoding="ascii")
    mpath = out.with_suffix(".map.csv")
    with open(mpath, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(mapping[0].keys()))
        w.writeheader()
        w.writerows(mapping)
    rpath = out.with_suffix(".report.txt")
    lines = [f"IFC {out.name}（IFC4）  {now_iso()}",
             f"座標の原点：{fr.get('version') or '（ファイルの座標）'} の通り芯の符号 {'・'.join(fr.get('labels') or []) or '（なし）'} の交点（mm）",
             f"既定の高さ {default_h:g} mm で押し出した要素（BT_Common.HeightAssumed）: {len(height_assumed)}"]
    lines += [f"  {_kind_of(store, e)} {e}" for e in height_assumed]
    lines.append(f"要確認が開いている要素（BT_Common.HasOpenIssue）: {len([e for e in ent if e in issue_kinds])}")
    lines += [f"  {_kind_of(store, e)} {e}  {'、'.join(sorted(issue_kinds[e]))}" for e in ent if e in issue_kinds]
    if allowed_by:
        lines.append(f"受け渡しの要件を満たさないが、人の判断（review {allowed_by}）で出した")
    rpath.write_text("\n".join(lines) + "\n", encoding="utf-8")
    as_of = {"at": now_iso(), "latest_review_id": store.scalar("select id from review order by rowid desc limit 1"),
             "allowed_by": allowed_by, "stopped_generation": generation_id}
    gid_new = store.insert("generation", recorded_by, kind="IFC", as_of_json=dumps(as_of), path=str(out), sha256=sha256_of(out),
                           marker_json=dumps({"schema": "IFC4", "mapping": str(mpath), "report": str(rpath)}))
    store.insert("generation", recorded_by, kind="IFC の対応表", as_of_json=dumps(as_of), path=str(mpath), sha256=sha256_of(mpath),
                 marker_json=dumps({"for": gid_new}))
    store.commit()
    return {"path": out, "mapping": mpath, "report": rpath, "generation_id": gid_new, "height_assumed": height_assumed,
            "default_height_mm": default_h, "allowed_by": allowed_by, "entities": len(S.lines)}
