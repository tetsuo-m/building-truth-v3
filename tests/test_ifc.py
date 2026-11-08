"""Stage 6: the IDS reader (L-1, L-2) and the IFC output (3-8; IFC4 ADD2 TC1, written with the standard library).

  * GlobalId: the UUID's 128 bits in IFC's 22-character form; the same element always gets the same GlobalId;
  * step2 → IfcBuildingStorey 1, IfcSpace 2, IfcWall 5, IfcRelSpaceBoundary 8 on the rooms' side (the outside's side
    counted apart); every product carries BT_Common.ElementId; the mapping CSV leads from relations and materials to
    the DB's ids; openings are not in IfcRelContainedInSpatialStructure;
  * unapproved readings are not exported; an open issue marks the property set HasOpenIssue; without a storey height
    the default height is used and marked HeightAssumed, listed in the report;
  * IDS of the delivery requirements is checked on effective values before export: not met → no IFC, the issues
    listed; a person's 「それでも出す」(allow-ifc, terminal) lets it out.
"""
from __future__ import annotations

import csv
import re
import uuid
from pathlib import Path

import pytest

from helpers import STEP2, import_sample, register_fixture
from stage5 import approve, check, imp, write_text
from test_consistency import door_project, materials_project


def step2_approved(tmp_path):
    project, store = import_sample(tmp_path, STEP2)
    r = register_fixture(store, project, "step2_fixed")
    approve(store, project, r.interpretation_id)
    return project, store, r


def export(store, project, path, **kw):
    from btruth.ifc import export_ifc
    return export_ifc(store, project, path, recorded_by="テスト", **kw)


def entities(text: str) -> dict[int, tuple[str, str]]:
    out = {}
    for m in re.finditer(r"^#(\d+)=([A-Z0-9]+)\((.*)\);$", text, re.M):
        out[int(m.group(1))] = (m.group(2), m.group(3))
    return out


def count_type(ents, name):
    return sum(1 for t, _ in ents.values() if t == name)


# ---------------------------------------------------------------- GlobalId
def test_globalid_is_the_uuid_in_22_characters_and_round_trips():
    from btruth.ifc import compress_guid, expand_guid
    for _ in range(50):
        u = str(uuid.uuid4())
        g = compress_guid(u)
        assert len(g) == 22 and g[0] in "0123" and expand_guid(g) == u
    assert compress_guid("00000000-0000-0000-0000-000000000000") == "0" * 22


# ---------------------------------------------------------------- step2
def test_step2_ifc_has_the_expected_counts_and_resolves_every_reference(tmp_path, terminal_ok):
    project, store, r = step2_approved(tmp_path)
    res = export(store, project, tmp_path / "step2.ifc")
    text = (tmp_path / "step2.ifc").read_text(encoding="ascii")
    assert "FILE_SCHEMA(('IFC4'));" in text
    ents = entities(text)
    assert count_type(ents, "IFCBUILDINGSTOREY") == 1
    assert count_type(ents, "IFCSPACE") == 2
    assert count_type(ents, "IFCWALL") == 5
    assert count_type(ents, "IFCEXTERNALSPATIALELEMENT") == 1
    rows = list(csv.DictReader(open(res["mapping"], encoding="utf-8-sig")))
    bounds = [x for x in rows if x["ifc_type"] == "IfcRelSpaceBoundary"]
    assert sum(1 for x in bounds if x["relating"] == "部屋") == 8
    assert sum(1 for x in bounds if x["relating"] == "外部") == 4
    for _, args in ents.values():                                    # every #n resolves
        for ref in re.findall(r"#(\d+)", args):
            assert int(ref) in ents
    products = [x for x in rows if x["has_element_id"] == "yes"]
    assert len(products) >= 2 + 5 + 1 + 3                             # spaces, walls, storey, site/building/project …
    for p in products:
        assert f"IFCIDENTIFIER('{p['db_id']}')" in text


def test_globalids_are_the_same_when_exported_twice(tmp_path, terminal_ok):
    project, store, r = step2_approved(tmp_path)
    export(store, project, tmp_path / "a.ifc")
    export(store, project, tmp_path / "b.ifc")
    def ids(p):
        return {(t, re.match(r"'([^']{22})'", a).group(1)) for t, a in entities(p.read_text(encoding="ascii")).values()
                if re.match(r"'([^']{22})'", a)}
    a, b = ids(tmp_path / "a.ifc"), ids(tmp_path / "b.ifc")
    assert a == b and len(a) > 20
    from btruth.ifc import compress_guid
    wall = r.element_ids["wall_A"]
    assert ("IFCWALL", compress_guid(wall)) in a


def test_the_mapping_leads_from_relations_and_split_boundaries_to_the_db(tmp_path, terminal_ok):
    project, store, r = door_project(tmp_path, minutes=False)
    res = export(store, project, tmp_path / "door.ifc")
    rows = list(csv.DictReader(open(res["mapping"], encoding="utf-8-sig")))
    voids = [x for x in rows if x["ifc_type"] == "IfcRelVoidsElement"]
    rel = store.scalar("select id from relation where kind='くり抜く' and from_element_id=?", r.element_ids["opening_A"])
    assert voids and voids[0]["db_id"] == rel
    fills = [x for x in rows if x["ifc_type"] == "IfcRelFillsElement"]
    assert fills and fills[0]["db_id"]
    text = (tmp_path / "door.ifc").read_text(encoding="ascii")
    ents = entities(text)
    opening_ent = [n for n, (t, a) in ents.items() if t == "IFCOPENINGELEMENT"]
    assert len(opening_ent) == 1
    contained = set()
    for t, a in ents.values():
        if t == "IFCRELCONTAINEDINSPATIALSTRUCTURE":
            related = a.split("(", 1)[1].split(")", 1)[0]               # the RelatedElements list
            contained |= {int(x) for x in re.findall(r"#(\d+)", related)}
    assert contained and opening_ent[0] not in contained
    assert count_type(ents, "IFCDOOR") == 1 and count_type(ents, "IFCRELFILLSELEMENT") == 1


def test_materials_are_in_the_mapping_by_name(tmp_path, terminal_ok):
    project, store, r = materials_project(tmp_path)
    res = export(store, project, tmp_path / "m.ifc")
    rows = list(csv.DictReader(open(res["mapping"], encoding="utf-8-sig")))
    mats = {x["name"]: x["db_id"] for x in rows if x["ifc_type"] == "IfcMaterial"}
    assert mats.get("PB12.5") == r.element_ids["pb"] and mats.get("LGS65") == r.element_ids["lgs"]
    text = (tmp_path / "m.ifc").read_text(encoding="ascii")
    assert "IFCMATERIALLAYERSET(" in text and "IFCRELASSOCIATESMATERIAL(" in text


# ---------------------------------------------------------------- what is exported and how it is marked
def test_unapproved_readings_are_not_exported_and_open_issues_are_marked(tmp_path, terminal_ok):
    from btruth.propose import register_proposal
    from helpers import element, claim, proposal, seg, STOREY, relation
    project, store, r = step2_approved(tmp_path)
    register_proposal(store, project, proposal([element("extra", "壁", [claim("芯線", seg((0, 0), (100, 0)), [], "mm")])],
                                               [relation("in", "含む", "extra", STOREY)]), recorded_by="テスト")
    check(store, project)
    res = export(store, project, tmp_path / "s.ifc")
    ents = entities((tmp_path / "s.ifc").read_text(encoding="ascii"))
    assert count_type(ents, "IFCWALL") == 5                         # the pending wall is not there
    rows = list(csv.DictReader(open(res["mapping"], encoding="utf-8-sig")))
    left = next(x for x in rows if x["db_id"] == r.element_ids["room_left"])
    assert left["has_open_issue"] == "yes"


def test_heights_missing_are_assumed_marked_and_listed(tmp_path, terminal_ok):
    project, store, r = step2_approved(tmp_path)
    res = export(store, project, tmp_path / "h.ifc")
    text = (tmp_path / "h.ifc").read_text(encoding="ascii")
    assert "IFCPROPERTYSINGLEVALUE('HeightAssumed',$,IFCBOOLEAN(.T.),$)" in text
    assert r.element_ids["wall_A"] in res["height_assumed"] and res["default_height_mm"] == 2700.0


# ---------------------------------------------------------------- IDS of the delivery requirements
IDS = """<?xml version="1.0" encoding="UTF-8"?>
<ids xmlns="http://standards.buildingsmart.org/IDS" xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <info><title>受け渡しの要件（架空）</title><purpose>受け渡しの要件</purpose></info>
  <specifications>
    <specification name="壁には耐火の性質がある" ifcVersion="IFC4">
      <applicability minOccurs="0" maxOccurs="unbounded"><entity><name><simpleValue>IFCWALL</simpleValue></name></entity></applicability>
      <requirements>
        <property cardinality="required"><propertySet><simpleValue>Pset_WallCommon</simpleValue></propertySet>
          <baseName><simpleValue>FireRating</simpleValue></baseName></property>
      </requirements>
    </specification>
  </specifications>
</ids>
"""


def test_ids_is_read_into_conditions(tmp_path, terminal_ok):
    project, store, r = step2_approved(tmp_path)
    v = imp(store, project, write_text(tmp_path / "req.ids", IDS), "受け渡しの要件", "条件")
    [c] = store.all("select * from condition where source_version_id=?", v)
    import json
    d = json.loads(c["ids_json"])
    assert c["form"] == "ids" and c["category"] == "受け渡しの要件"
    assert d["applicability"]["entity"] == ["IFCWALL"]
    assert d["requirements"] == [{"facet": "property", "propertySet": "Pset_WallCommon", "baseName": "FireRating",
                                  "cardinality": "required", "value": None}]
    assert store.scalar("select kind from clue where id=?", c["clue_id"]) == "SPECIFICATION"


def test_unmet_delivery_requirements_stop_the_ifc_until_a_person_allows(tmp_path, terminal_ok):
    from btruth.ifc import IfcStopped
    from btruth.review import allow_ifc
    project, store, r = step2_approved(tmp_path)
    imp(store, project, write_text(tmp_path / "req.ids", IDS), "受け渡しの要件", "条件")
    with pytest.raises(IfcStopped) as exc:
        export(store, project, tmp_path / "x.ifc")
    assert not (tmp_path / "x.ifc").exists()
    gid = exc.value.generation_id
    checks = store.all("select result from condition_check where generation_id=?", gid)
    assert len(checks) == 5 and all(c["result"] == "満たさない" for c in checks)
    assert store.scalar("select count(*) from issue where kind='条件を満たさない'") == 5
    allow_ifc(store, project, gid, reason="耐火は特記で別に渡す", reviewed_by="てっちゃん")
    res = export(store, project, tmp_path / "x.ifc", generation_id=gid)
    assert (tmp_path / "x.ifc").exists() and res["allowed_by"]
    # with the property, the requirement is met and nothing stops
    from btruth.review import decide
    for k in ("wall_S", "wall_E", "wall_N", "wall_W", "wall_A"):
        decide(store, project, r.element_ids[k], "耐火", "1時間", reason="特記", reviewed_by="てっちゃん")
    export(store, project, tmp_path / "y.ifc")
    assert (tmp_path / "y.ifc").exists()
