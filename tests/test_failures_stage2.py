"""docs/FAILURES.md: the failures whose check belongs to stage 2 (design 3-9), reproduced on fictional data.

F-7  the vessel was fixed to a handful of table kinds; legends, minutes and other disciplines had no place.
     -> kinds are CSV rows (A-2, C-1, J-5); a new kind needs no code change.
F-8  (ground only) versions are things in the vessel; comparing is done on the vessel (B-5), see test_compare.
"""
from __future__ import annotations

from helpers import count, make_project


def test_f7_a_new_source_kind_needs_no_code_change(tmp_path):
    from btruth.intake import import_file

    project, store = make_project(tmp_path)
    minutes = tmp_path / "m.txt"
    minutes.write_text("WT-1 は二重張りとする。\n", encoding="utf-8")
    legend = tmp_path / "legend.csv"
    legend.write_text("symbol,meaning\nINS_GW,グラスウール 50\n", encoding="utf-8")
    spec = tmp_path / "spec.txt"
    spec.write_text("本工事の特記仕様。\n", encoding="utf-8")
    import_file(store, project, minutes, source_name="議事録3", kind="議事録", recorded_by="テスト")
    import_file(store, project, legend, source_name="凡例", kind="設計図", drawing_type="凡例", recorded_by="テスト")
    import_file(store, project, spec, source_name="特記", kind="特記仕様書", recorded_by="テスト")
    other = tmp_path / "other.txt"
    other.write_text("x\n", encoding="utf-8")
    import_file(store, project, other, source_name="何か", kind="その他", recorded_by="テスト")
    kinds = {r[0] for r in store.conn.execute("select kind from source")}
    assert kinds == {"議事録", "設計図", "特記仕様書", "その他"}
    # a discipline the vessel has never seen is just another attribute value (C-1, E-1)
    elec = tmp_path / "elec.csv"
    elec.write_text("a,b\n1,2\n", encoding="utf-8")
    r = import_file(store, project, elec, source_name="電気配線図", kind="設計図", drawing_type="電気配線図",
                    discipline="電気", recorded_by="テスト")
    assert store.conn.execute("select value from source_attribute where source_id=? and attribute='分野'",
                              (r.source_id,)).fetchone()[0] == "電気"


def test_f7_a_new_element_kind_is_a_csv_row(tmp_path):
    from btruth.tables import effective_rows, load_tables

    project, store = make_project(tmp_path)
    p = project.folder / "rules" / "element_kinds.csv"
    p.write_text(p.read_text(encoding="utf-8-sig") + "貫通部,IfcBuildingElementProxy,,no,設備が壁を貫く所（E-3）\n",
                 encoding="utf-8")
    load_tables(store, project, recorded_by="テスト")
    kinds = {r["kind"]: r for r in effective_rows(store, project, "element_kinds")}
    assert kinds["貫通部"]["ifc_class"] == "IfcBuildingElementProxy"
    assert kinds["壁"]["ifc_class"] == "IfcWall"
    # the copy of the old table stays (B-6, B-10): two loads of element_kinds for the project scope
    assert count(store, "select count(*) from table_load where kind='element_kinds' and scope='物件'") == 2


def test_f7_reader_added_clue_kinds_are_stored_as_they_are(tmp_path):
    """B-1: a reader may add kinds; the clue table does not enumerate them."""
    _, store = make_project(tmp_path)
    v = store.insert("source_version", source_id="s", seq=1, file_name="x", sha256="0" * 64, format="jww",
                     reader_name="jww", reader_version="0", unit_factor=1.0, recorded_by="テスト")
    store.insert("clue", source_version_id=v, seq=1, kind="JWW_SUPPLEMENTARY_LINE", layer_raw="0",
                 geometry_json="{}", format_extra_json='{"aux": true}', recorded_by="テスト")
    assert count(store, "select count(*) from clue where kind='JWW_SUPPLEMENTARY_LINE'") == 1
