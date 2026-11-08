"""Creating the vessel: default structure (C-2b), default CSV tables (J), readers (B-2), settings."""
from __future__ import annotations

import csv

from helpers import count, make_project


def kinds_of(store):
    """{element_id: kind} from the 種類 claims (C-1: the kind is a claim, not a column)."""
    rows = store.conn.execute(
        "select subject_id, value_json from claim where subject_kind='element' and attribute='種類'").fetchall()
    import json
    return {r[0]: json.loads(r[1]) for r in rows}


def names_of(store):
    import json
    rows = store.conn.execute(
        "select subject_id, value_json from claim where subject_kind='element' and attribute='名前'").fetchall()
    return {r[0]: json.loads(r[1]) for r in rows}


def test_default_structure_has_one_first_storey(tmp_path):
    _, store = make_project(tmp_path)
    kinds = kinds_of(store)
    names = names_of(store)
    storeys = [e for e, k in kinds.items() if k == "階"]
    assert len(storeys) == 1
    assert names[storeys[0]] == "1階"
    assert sorted(kinds.values()) == sorted(["物件", "敷地", "建物", "階", "外部"])


def test_the_project_is_an_element_too(tmp_path):
    """改訂 6 (2): the project is an element (種類=物件); the project table points at it."""
    _, store = make_project(tmp_path, name="架空の物件")
    kinds, names = kinds_of(store), names_of(store)
    [proj] = [e for e, k in kinds.items() if k == "物件"]
    assert names[proj] == "架空の物件"
    assert store.conn.execute("select element_id from project").fetchone()[0] == proj
    # 集める: 敷地 → 物件 (an element, not the project row)
    site = [e for e, k in kinds.items() if k == "敷地"][0]
    to = store.conn.execute("select to_element_id, role_json from relation where from_element_id=?", (site,)).fetchone()
    assert to[0] == proj and to[1] is None


def test_default_structure_is_an_interpretation_of_the_rule_reader(tmp_path):
    _, store = make_project(tmp_path)
    row = store.conn.execute(
        "select i.summary, a.kind from interpretation i join agent a on a.id = i.agent_id").fetchone()
    assert tuple(row) == ("既定の構成", "規則の読み手")
    # 集める: 階 -> 建物 -> 敷地 -> 物件, 外部 -> 敷地 (E-7 / C-2b)
    rels = store.conn.execute("select kind, from_element_id, to_element_id from relation").fetchall()
    assert all(k == "集める" for k, _, _ in rels)
    assert len(rels) == 4  # 敷地→物件, 建物→敷地, 階→建物, 外部→敷地
    assert count(store, "select count(*) from element") == 5
    # every default claim is a 記述 (statement_kind); no 決定 is invented
    kinds_of_statement = {r[0] for r in store.conn.execute("select distinct statement_kind from claim")}
    assert kinds_of_statement == {"記述"}


def test_project_folder_layout_and_settings(tmp_path):
    project, store = make_project(tmp_path, name="架空の物件")
    for sub in ("rules", "settings", "knowledge", "archive", "out"):
        assert (project.folder / sub).is_dir(), sub
    assert project.db_path.exists()
    # the DB lives where the settings say, never on the command line (G-1 (a))
    assert project.settings["db_path"]
    assert project.db_path == project.folder / project.settings["db_path"]
    assert store.conn.execute("select name from project").fetchone()[0] == "架空の物件"


def test_default_csv_tables_are_copied_and_loaded(tmp_path):
    project, store = make_project(tmp_path)
    for rel in ("rules/rules.csv", "rules/authority.csv", "rules/document_rank.csv", "rules/element_kinds.csv",
                "rules/attributes.csv", "rules/relation_kinds.csv", "rules/conditions.csv",
                "settings/layer_roles.csv", "knowledge/readings.csv"):
        assert (project.folder / rel).exists(), rel
    kinds = {r[0] for r in store.conn.execute("select kind from table_load")}
    assert kinds == {"rules", "authority", "document_rank", "layer_roles", "knowledge",
                     "relation_kinds", "attributes", "element_kinds", "conditions"}
    # E-2 / E-4: the vessel knows these kinds from the start, with IFC names (E-7)
    ek = {r[0]: r[1] for r in store.conn.execute("select kind, ifc_class from element_kinds_loaded")}
    for k in ("階", "空間の境界", "開口", "材料", "層の組み立て", "部品", "外部", "壁", "部屋"):
        assert k in ek, k
    assert ek["階"] == "IfcBuildingStorey"
    assert ek["空間の境界"] == "IfcRelSpaceBoundary"
    assert ek["開口"] == "IfcOpeningElement"
    rk = {r[0]: (r[1], r[2]) for r in store.conn.execute("select kind, max_per_from, from_kinds from relation_kinds_loaded")}
    assert rk["含む"][0] == "1" and rk["くり抜く"][0] == "1"
    assert "開口" not in rk["含む"][1].split("+")          # 改訂 6 (4): openings are not contained in a storey
    assert ek["物件"] == "IfcProject"
    attrs = {(r[0], r[1]) for r in store.conn.execute("select attribute, applies_to from attributes_loaded")}
    names = {a for a, _ in attrs}
    assert {"種類", "名前", "外部か", "ElementId"} <= names
    # 改訂 6 (1): the three meanings of "kind" have three names
    assert ("境界の種類", "空間の境界") in attrs and ("建具の種類", "建具") in attrs
    assert ("種類", "*") in attrs
    assert not {a for a, t in attrs if a == "種類" and t != "*"}
    authority = {(r[0], r[1]) for r in store.conn.execute("select element_kind, attribute from authority_loaded")}
    assert ("建具", "建具の種類") in authority and ("建具", "種類") not in authority


def test_rules_hold_the_tolerances_in_one_place(tmp_path):
    project, store = make_project(tmp_path)
    rules = {r[0]: (r[1], r[2]) for r in store.conn.execute("select key, value, use from rules_loaded")}
    assert rules["same_position_mm"][0] == "0.1"
    assert rules["same_angle_deg"][0] == "0.01"
    # 改訂 6 (14): every tolerance says where it is used; none is for comparing documents with each other
    assert rules["door_width_tol_mm"][1] == "図面の計測" and rules["gap_tol_mm"][1] == "図面の計測"
    assert all(use for _, use in rules.values()), rules
    assert not [k for k, (_, use) in rules.items() if use == "書類の比較" and k.endswith("_mm")]
    with open(project.folder / "rules" / "rules.csv", encoding="utf-8-sig", newline="") as f:
        keys = [row["key"] for row in csv.DictReader(f)]
    assert keys.count("same_position_mm") == 1


def test_document_rank_defaults_follow_c10(tmp_path):
    _, store = make_project(tmp_path)
    ranks = {r[0]: (r[1], r[2]) for r in store.conn.execute(
        "select source_kind, rank, compare_only from document_rank_loaded")}
    assert ranks["法律"][0] == "1" and ranks["議事録"][0] == "2" and ranks["設計図"][0] == "5"
    assert ranks["事務所の基準"][0] == "6" and ranks["標準仕様書"][0] == "7"
    assert ranks["施工図"] == ("5", "yes")
    assert "法規" not in ranks


def test_readers_are_registered(tmp_path):
    _, store = make_project(tmp_path)
    names = {r[0] for r in store.conn.execute("select name from reader")}
    assert {"dxf", "csv", "text"} <= names


def test_office_folder_is_read_first_and_project_overrides(tmp_path):
    from btruth.tables import effective_rows

    office = tmp_path / "office"
    (office / "rules").mkdir(parents=True)
    (office / "rules" / "rules.csv").write_text(
        "key,value,unit,origin,since,note\nsame_position_mm,0.1,mm,人の決定,2026-11-07,\n"
        "gap_tol_mm,50,mm,人の回答,2026-11-05,\noffice_only,1,,事務所,,\n", encoding="utf-8")
    project, store = make_project(tmp_path, office=office)
    # project copy overrides gap_tol_mm
    (project.folder / "rules" / "rules.csv").write_text(
        "key,value,unit,origin,since,note\ngap_tol_mm,30,mm,人の決定,2026-11-08,この物件だけ\n", encoding="utf-8")
    from btruth.tables import load_tables
    load_tables(store, project, recorded_by="テスト")
    rules = {r["key"]: r["value"] for r in effective_rows(store, project, "rules")}
    assert rules["gap_tol_mm"] == "30"
    assert rules["same_position_mm"] == "0.1"
    assert rules["office_only"] == "1"
    scopes = {(r[0], r[1]) for r in store.conn.execute("select kind, scope from table_load where kind='rules'")}
    assert {("rules", "事務所"), ("rules", "物件")} <= scopes
