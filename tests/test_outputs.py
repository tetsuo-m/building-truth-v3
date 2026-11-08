"""Stage 6: the outputs (H-1, H-2, H-3, M-1, M-2; example 7).

  * tables computed from effective values (area, finishes, quantities); quantities deduct openings larger than
    opening_min_deduct_m2 (v2 Q17–Q20, Q31); a room without ceiling height is listed under 数えられなかったもの
    with the reason (v2 Q20); nothing stored, the time of the values recorded in `generation`;
  * a generated drawing on BT_GEN_ layers; imported again it is not observation; a person's addition on their own
    layer is (例7);
  * writing back an approved drawing fix: the original is never overwritten; its sha256 must be the imported one,
    else nothing is written; the new drawing is 未確認 until a person checked it in CAD.
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import pytest

from helpers import STEP2, count, import_sample, register_fixture
from stage5 import approve, check, imp, open_of, register
from helpers import claim, ev, proposal
from test_consistency import door_project


def choose(store, project, issue_id, code, reason="決めた"):
    from btruth.review import choose_option
    return choose_option(store, project, issue_id, code, reason=reason, reviewed_by="てっちゃん")


def step2_approved(tmp_path):
    project, store = import_sample(tmp_path, STEP2)
    r = register_fixture(store, project, "step2_fixed")
    approve(store, project, r.interpretation_id)
    return project, store, r


# ---------------------------------------------------------------- tables
def test_area_table_from_effective_values(tmp_path, terminal_ok):
    from btruth.outputs import area_table
    project, store, r = step2_approved(tmp_path)
    t = area_table(store, project)
    rows = {row["要素"]: row for row in t["rows"]}
    assert rows[r.element_ids["room_left"]]["面積_m2"] == pytest.approx(9.20, abs=0.005)
    assert rows[r.element_ids["room_101"]]["面積_m2"] == pytest.approx(14.80, abs=0.005)
    assert rows[r.element_ids["room_101"]]["室名"] == "事務室"
    assert t["合計_m2"] == pytest.approx(24.00, abs=0.005)


def test_quantity_table_follows_the_v2_rules(tmp_path, terminal_ok):
    from btruth.outputs import quantity_table
    project, store, r = step2_approved(tmp_path)
    t = quantity_table(store, project)
    row = next(x for x in t["rows"] if x["要素"] == r.element_ids["room_101"])
    # H = 2700 + 100; wall area = 15.400 m × 2.800 m; boards = ceil(area / (0.91 × 1.82) × 1.10) (v2 Q17–Q19)
    assert row["張り上げ高さ_mm"] == 2800
    assert row["壁の面積_m2"] == pytest.approx(43.12, abs=0.005)
    assert row["差し引いた開口_m2"] == 0
    assert row["ボードの枚数"] == math.ceil(43.12 / (0.91 * 1.82) * 1.10)
    left = next(x for x in t["数えられなかったもの"] if x["要素"] == r.element_ids["room_left"])
    assert "天井高" in left["理由"]


def test_quantities_deduct_openings_larger_than_the_limit(tmp_path, terminal_ok):
    from btruth.outputs import quantity_table
    project, store, r = door_project(tmp_path, minutes=False)
    m = register(store, project, proposal([], claims=[dict(claim("天井高", 2700, [], "mm"), subject={"id": r.element_ids[k]})
                                                      for k in ("room_left", "room_101")], sources=["平面図@1"]))
    approve(store, project, m.interpretation_id)
    t = quantity_table(store, project)
    right = next(x for x in t["rows"] if x["要素"] == r.element_ids["room_101"])
    # the door AD-1 (800 × 2000 from the schedule) = 1.6 m² > 0.5 m²: deducted on both sides of the partition
    assert right["差し引いた開口_m2"] == pytest.approx(1.6)
    assert right["壁の面積_m2"] == pytest.approx(15.4 * 2.8 - 1.6, abs=0.005)
    from btruth.outputs import deducted
    assert deducted(0.4, {"opening_min_deduct_m2": "0.5"}) is False and deducted(1.6, {"opening_min_deduct_m2": "0.5"}) is True


def test_tables_are_written_as_csv_and_html_and_recorded(tmp_path, terminal_ok):
    from btruth.outputs import write_tables
    project, store, r = step2_approved(tmp_path)
    paths = write_tables(store, project, tmp_path / "tables", recorded_by="テスト")
    names = sorted(p.name for p in paths)
    assert names == ["area.csv", "area.html", "finishes.csv", "finishes.html", "quantities.csv", "quantities.html"]
    rows = list(csv.DictReader(open(tmp_path / "tables" / "area.csv", encoding="utf-8-sig")))
    assert len(rows) == 2
    gens = store.all("select kind, as_of_json, path, sha256 from generation where kind='表'")
    assert len(gens) == 6 and all(json.loads(g["as_of_json"]).get("latest_review_id") for g in gens)


# ---------------------------------------------------------------- the generated drawing (H-2, M-1, 例7)
def test_a_generated_drawing_is_not_read_as_observation_and_a_persons_addition_is(tmp_path, terminal_ok):
    import ezdxf
    from btruth.outputs import write_drawing
    project, store, r = step2_approved(tmp_path)
    out = write_drawing(store, project, tmp_path / "gen.dxf", recorded_by="テスト")
    doc = ezdxf.readfile(out)
    layers = {e.dxf.layer for e in doc.modelspace()}
    assert layers and all(l.startswith("BT_GEN_") for l in layers)
    assert sum(1 for e in doc.modelspace() if e.dxf.layer == "BT_GEN_WALL_FACE") == 10      # 5 walls × 2 faces
    # imported as it is: every clue is generated (sha256)
    v = imp(store, project, out, "生成図", "設計図", "建築平面図")
    assert count(store, "select count(*) from clue where source_version_id=? and generated_from is null and parent_clue_id is null", v) == 0
    # a person adds a line on their own layer: that line is observation, the BT_GEN_ lines are not
    doc.modelspace().add_line((0, 0), (1000, 1000), dxfattribs={"layer": "人の描き足し"})
    doc.saveas(tmp_path / "gen_edited.dxf")
    v2 = imp(store, project, tmp_path / "gen_edited.dxf", "生成図", "設計図", mode="next")
    observed = store.all("select layer_raw from clue where source_version_id=? and generated_from is null and parent_clue_id is null", v2)
    assert [o["layer_raw"] for o in observed] == ["人の描き足し"]


# ---------------------------------------------------------------- writing back an approved drawing fix (H-3, M-2)
def fixed_opening(tmp_path):
    project, store, r = door_project(tmp_path)
    check(store, project)
    [late] = open_of(store, project, "決定が未反映")
    choose(store, project, late["id"], "type_width")
    check(store, project)
    opening = r.element_ids["opening_A"]
    [fix] = [i for i in open_of(store, project, "言い分の食い違い（主と従）") if opening in i["subject_ids"]]
    rid = choose(store, project, fix["id"], "fix_secondary", reason="図面を直す")
    return project, store, r, rid


def test_writeback_scales_the_door_in_a_new_file_and_keeps_the_original(tmp_path, terminal_ok):
    import ezdxf
    from btruth.common import sha256_of
    from btruth.outputs import write_back, writeback_status
    project, store, r, rid = fixed_opening(tmp_path)
    original = tmp_path / "plan.dxf"
    before = sha256_of(original)
    wb = write_back(store, project, "平面図", original, tmp_path / "plan_wb.dxf", recorded_by="テスト")
    assert sha256_of(original) == before                                       # never overwritten
    row = store.one("select * from writeback where id=?", wb)
    assert row["base_sha256_verified"] == 1 and rid in json.loads(row["review_ids_json"])
    assert writeback_status(store, wb) == "未確認"
    doc = ezdxf.readfile(tmp_path / "plan_wb.dxf")
    [door] = [e for e in doc.modelspace() if e.dxftype() == "INSERT"]
    assert door.dxf.xscale == pytest.approx(900 / 800) and door.dxf.yscale == pytest.approx(900 / 800)
    # imported unchanged, it is the person's drawing (observed), linked to the writeback
    v = imp(store, project, tmp_path / "plan_wb.dxf", "平面図", "設計図", mode="next")
    assert store.scalar("select writeback_id from source_version where id=?", v) == wb
    assert count(store, "select count(*) from clue where source_version_id=? and generated_from is not null", v) == 0


def test_writeback_refuses_when_the_original_changed(tmp_path, terminal_ok):
    from btruth.outputs import WritebackRefused, write_back
    project, store, r, rid = fixed_opening(tmp_path)
    original = tmp_path / "plan.dxf"
    original.write_bytes(original.read_bytes() + b"\n999\nchanged\n")
    with pytest.raises(WritebackRefused):
        write_back(store, project, "平面図", original, tmp_path / "plan_wb.dxf", recorded_by="テスト")
    assert not (tmp_path / "plan_wb.dxf").exists()
    row = store.one("select * from writeback order by rowid desc limit 1")
    assert row["base_sha256_verified"] == 0 and row["new_path"] is None and row["status"] == "書かなかった"


def test_confirming_the_drawing_in_cad_is_a_persons_review(tmp_path, terminal_ok):
    from btruth.outputs import write_back, writeback_status
    from btruth.review import confirm_drawing
    project, store, r, rid = fixed_opening(tmp_path)
    wb = write_back(store, project, "平面図", tmp_path / "plan.dxf", tmp_path / "plan_wb.dxf", recorded_by="テスト")
    confirm_drawing(store, project, wb, reason="Jw_cad で開いて確かめた", reviewed_by="てっちゃん")
    assert writeback_status(store, wb) == "人が CAD で確認済み"


def test_confirm_drawing_refuses_outside_a_terminal(tmp_path, terminal_ok, monkeypatch):
    from btruth.outputs import write_back
    from btruth.review import NotATerminal, confirm_drawing
    project, store, r, rid = fixed_opening(tmp_path)
    wb = write_back(store, project, "平面図", tmp_path / "plan.dxf", tmp_path / "plan_wb.dxf", recorded_by="テスト")
    monkeypatch.delenv("BTRUTH_TEST_TERMINAL")
    with pytest.raises(NotATerminal):
        confirm_drawing(store, project, wb, reason="x", reviewed_by="x")
