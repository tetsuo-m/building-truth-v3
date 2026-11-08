"""Comparing two versions of a drawing drawn with different tools (B-14, 3-3b 案1 steps 1-2, 4):
layers normalised to roles (settings/layer_roles.csv), frames aligned on the smallest grid labels,
positions compared within same_position_mm and angles within same_angle_deg (rules.csv, one place).
"""
from __future__ import annotations

from helpers import STEP1, STEP1_JW, count, make_project, one_room_dxf


def test_layer_roles_normalise_both_naming_styles(tmp_path):
    from btruth.compare import roles_for
    from btruth.tables import effective_rows

    project, store = make_project(tmp_path)
    rows = effective_rows(store, project, "layer_roles")
    assert roles_for("GRID", "LINE", rows) == ("GRID",)
    assert roles_for("_0-2_GRID", "LINE", rows) == ("GRID",)
    assert roles_for("_0-3_ROOM_BOUNDARY", "LINE", rows) == ("ROOM_BOUNDARY",)
    assert roles_for("ROOM_NAME", "TEXT", rows) == ("ROOM_NAME",)
    assert roles_for("ADD_LINE", "LINE", rows) == ("raw:ADD_LINE",)      # unknown layers are kept as they are


def test_step1_and_its_jwcad_export_match_within_tolerance(tmp_path):
    from btruth.compare import compare_versions
    from btruth.intake import import_file

    project, store = make_project(tmp_path)
    a = import_file(store, project, STEP1, source_name="平面図", recorded_by="テスト")
    b = import_file(store, project, STEP1_JW, source_name="平面図", recorded_by="テスト")
    r = compare_versions(store, project, a.source_version_id, b.source_version_id, recorded_by="テスト")
    assert r.frame["aligned"] is True
    assert r.frame["labels"] == ["X1", "Y1"]
    assert r.frame["delta_mm"] == [210000000.0, 148500000.0]
    assert len(r.matched) == 21            # 12 lines + 5 texts + 4 grid-label circles
    assert r.only_a == [] and r.only_b == []
    kinds = {row[0] for row in store.conn.execute(
        "select kind from intake_log where source_version_id=?", (b.source_version_id,))}
    assert {"座標の枠の揃え方", "版の比べ"} <= kinds


def test_clues_only_in_the_new_version_are_recorded_as_candidates(tmp_path):
    from btruth.compare import compare_versions
    from btruth.intake import import_file

    project, store = make_project(tmp_path)
    a = import_file(store, project, one_room_dxf(tmp_path / "a.dxf"), source_name="平面図", recorded_by="テスト")
    b = import_file(store, project, one_room_dxf(tmp_path / "b.dxf", extra=[
        ("CIRCLE", "GRID", {"center": (0, 5900), "radius": 400}),
        ("CIRCLE", "GRID", {"center": (6000, 5900), "radius": 400}),
    ]), source_name="平面図", recorded_by="テスト")
    r = compare_versions(store, project, a.source_version_id, b.source_version_id, recorded_by="テスト")
    assert len(r.matched) == 17 and r.only_a == [] and len(r.only_b) == 2
    assert {store.clue_kind(c) for c in r.only_b} == {"CIRCLE"}
    assert count(store, "select count(*) from intake_log where kind='追加の候補' and source_version_id=?",
                 b.source_version_id) == 1


def test_tolerance_comes_from_rules_and_is_applied(tmp_path):
    from btruth.compare import compare_versions
    from btruth.intake import import_file

    project, store = make_project(tmp_path)
    a = import_file(store, project, one_room_dxf(tmp_path / "a.dxf"), source_name="平面図", recorded_by="テスト")
    # same drawing, one wall-centre line nudged by 0.05 mm (inside the width) and one by 0.5 mm (outside)
    path = one_room_dxf(tmp_path / "b.dxf")
    import ezdxf
    doc = ezdxf.readfile(path)
    walls = [e for e in doc.modelspace() if e.dxftype() == "LINE" and e.dxf.layer == "WALL_CENTER"]
    walls[0].dxf.end = (walls[0].dxf.end.x + 0.05, walls[0].dxf.end.y)
    walls[1].dxf.end = (walls[1].dxf.end.x, walls[1].dxf.end.y + 0.5)
    doc.saveas(path)
    b = import_file(store, project, path, source_name="平面図", recorded_by="テスト")
    r = compare_versions(store, project, a.source_version_id, b.source_version_id, recorded_by="テスト")
    assert len(r.only_a) == 1 and len(r.only_b) == 1
    assert len(r.matched) == 16


def test_frame_is_aligned_even_when_the_whole_drawing_is_shifted(tmp_path):
    from btruth.compare import compare_versions
    from btruth.intake import import_file

    project, store = make_project(tmp_path)
    a = import_file(store, project, one_room_dxf(tmp_path / "a.dxf"), source_name="平面図", recorded_by="テスト")
    b = import_file(store, project, one_room_dxf(tmp_path / "b.dxf", dx=12345.678, dy=-999.5),
                    source_name="平面図", recorded_by="テスト")
    r = compare_versions(store, project, a.source_version_id, b.source_version_id, recorded_by="テスト")
    assert r.frame["aligned"] and r.frame["delta_mm"] == [12345.678, -999.5]
    assert len(r.matched) == 17 and not r.only_a and not r.only_b


def test_without_grid_labels_nothing_is_silently_aligned(tmp_path):
    from btruth.compare import compare_versions
    from btruth.intake import import_file
    from helpers import write_dxf

    project, store = make_project(tmp_path)
    ents = [("LINE", "WALL_CENTER", {"start": (0, 0), "end": (1000, 0)})]
    a = import_file(store, project, write_dxf(tmp_path / "a.dxf", ents, ["WALL_CENTER"]), source_name="s", recorded_by="テスト")
    ents2 = [("LINE", "WALL_CENTER", {"start": (10, 0), "end": (1010, 0)})]
    b = import_file(store, project, write_dxf(tmp_path / "b.dxf", ents2, ["WALL_CENTER"]), source_name="s", recorded_by="テスト")
    r = compare_versions(store, project, a.source_version_id, b.source_version_id, recorded_by="テスト")
    assert r.frame["aligned"] is False
    assert len(r.only_a) == 1 and len(r.only_b) == 1
    assert count(store, "select count(*) from intake_log where kind='座標の枠の揃え方' and source_version_id=?",
                 b.source_version_id) == 1
