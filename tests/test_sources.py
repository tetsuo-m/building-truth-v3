"""Stage 5: tables, legends and minutes as sources; identity between sources (B-13); meaning changes (案3, Q27).

  * the minutes' sentences can be cited (`btruth clues` shows SENTENCE / CELL children);
  * 未決 (「〜を検討する」「次回確認」) has no rank and never becomes an effective value (C-10);
  * an element can be found by its key (`{"find": {"kind": "建具の型", "符号": "AD-1"}}`);
  * 例2: the column of the architectural plan and the column of the structural drawing become one element;
    the primary (構造図) gives the position; the plan's position is a secondary that differs → 言い分の食い違い;
  * 例4: a legend's 記号の定義 is the evidence of the plan's reading; a pending legend may be cited;
  * a legend whose definition changed: the elements read with that symbol become 意味が変わった;
  * a wall-type row that changed: the judgements on walls of that type get a recheck mark (Q27 の足し, 決定 9);
  * F-6: layer names changed, the fixed interpretation still registers and approves the same way.
"""
from __future__ import annotations

import json

import pytest

from helpers import (OUTSIDE, STOREY, claim, count, element, ev, import_sample, make_project, proposal, register_fixture,
                     relation, seg, write_dxf, step2_like_dxf, step2_fixture_at, WALL_TYPES)
from stage5 import (approve, check, imp, open_kinds, open_of, ref, register, wall_type_project, wall_type_reading,
                    write_text, composition)


# ---------------------------------------------------------------- readers and references
def test_clues_command_lists_the_sentences_of_minutes(tmp_path):
    import subprocess, sys
    from conftest import ROOT
    project, store = wall_type_project(tmp_path)
    store.close()
    r = subprocess.run([sys.executable, "-m", "btruth", "clues", str(project.folder), "議事録3@1"], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)
    sentences = [c for c in d["clues"] if c["kind"] == "SENTENCE"]
    assert [s["text"] for s in sentences if "WT" in s["text"]] == ["WT-1 の間仕切は PB 二重張りとする。", "WT-2 の遮音性能は次回確認。"]
    assert all(s["ref"].startswith("議事録3@1#") for s in sentences)


def test_undecided_minutes_have_no_rank_and_no_effective_value(tmp_path, terminal_ok):
    from btruth.effective import effective_value
    project, store = wall_type_project(tmp_path)
    r = register(store, project, wall_type_reading(store))
    approve(store, project, r.interpretation_id)
    assert effective_value(store, project, r.element_ids["wt2"], "遮音性能").present is False
    c = store.one("select statement_kind from claim where subject_id=? and attribute='遮音性能'", r.element_ids["wt2"])
    assert c["statement_kind"] == "未決"


def test_find_an_element_by_its_key(tmp_path, terminal_ok):
    project, store = wall_type_project(tmp_path)
    r = register(store, project, wall_type_reading(store))
    approve(store, project, r.interpretation_id)
    s = ref(store, "議事録3", 1, "次回確認")
    p = proposal([], claims=[dict(claim("遮音性能", "次回確認", [ev(s)]), subject={"find": {"kind": "壁種", "符号": "WT-2"}},
                                  statement_kind="未決")], sources=["議事録3@1"])
    r2 = register(store, project, p)
    assert r2.rejected == 0
    assert store.scalar("select subject_id from claim where id=?", r2.claim_ids[0]) == r.element_ids["wt2"]


# ---------------------------------------------------------------- 例2: one column from two sources
def column_plan(path, y=0.0, tag="C1", note=True):
    ents = [("LINE", "GRID", {"start": (0, -1500), "end": (0, 5500)}), ("TEXT", "GRID", {"text": "X1", "insert": (0, 5900)}),
            ("LINE", "GRID", {"start": (-1500, 0), "end": (7500, 0)}), ("TEXT", "GRID", {"text": "Y1", "insert": (-1900, 0)}),
            ("INSERT", "COLUMN", {"name": tag, "insert": (0, y)})]
    if note:
        ents.append(("TEXT", "NOTE", {"text": "柱：鉄骨表し", "insert": (300, 300)}))
    return write_dxf(path, ents, layers=["GRID", "COLUMN", "NOTE"])


def test_example2_a_column_of_two_sources_is_one_element(tmp_path, terminal_ok):
    from btruth.effective import approved_elements_by_kind, effective_value
    from btruth.identity import identify_sources
    project, store = make_project(tmp_path)
    imp(store, project, column_plan(tmp_path / "arch.dxf"), "建築平面図", "設計図", "建築平面図", discipline="建築")
    imp(store, project, column_plan(tmp_path / "str.dxf", y=50.0, note=False), "構造図", "設計図", "構造図", discipline="構造")
    imp(store, project, write_text(tmp_path / "cols.csv", "code,section\nC1,H-200x200x8x12\n"), "柱リスト", "設計図", "柱リスト",
        discipline="構造")
    grids = [element("X1", "通り芯", [claim("符号", "X1", [ev("建築平面図@1#2")]), claim("線分", seg((0, -1500), (0, 5500)), [ev("建築平面図@1#1")], "mm")],
                     [ev("建築平面図@1#1"), ev("建築平面図@1#2")]),
             element("Y1", "通り芯", [claim("符号", "Y1", [ev("建築平面図@1#4")]), claim("線分", seg((-1500, 0), (7500, 0)), [ev("建築平面図@1#3")], "mm")],
                     [ev("建築平面図@1#3"), ev("建築平面図@1#4")])]
    col = element("c1", "柱", [claim("符号", "C1", [ev("建築平面図@1#5")]), claim("位置", [0.0, 0.0], [ev("建築平面図@1#5")], "mm"),
                               claim("仕上", "鉄骨表し", [ev("建築平面図@1#6")])], [ev("建築平面図@1#5")])
    a = register(store, project, proposal(grids + [col], [relation("on_x", "載る", "c1", "X1"), relation("on_y", "載る", "c1", "Y1"),
                                                       relation("in", "含む", "c1", STOREY)], sources=["建築平面図@1"]))
    approve(store, project, a.interpretation_id)
    # the structural reading refers to the approved grid axes by their key (it does not re-create them)
    s_col = element("s1", "柱", [claim("符号", "C1", [ev("構造図@1#5")]), claim("位置", [0.0, 50.0], [ev("構造図@1#5")], "mm"),
                                 claim("断面", "H-200x200x8x12", [ev("柱リスト@1#1")])], [ev("構造図@1#5"), ev("柱リスト@1#1")])
    b = register(store, project, proposal([s_col], [relation("on_x", "載る", "s1", {"find": {"kind": "通り芯", "符号": "X1"}}),
                                                    relation("on_y", "載る", "s1", {"find": {"kind": "通り芯", "符号": "Y1"}}),
                                                    relation("in", "含む", "s1", STOREY)], sources=["構造図@1", "柱リスト@1"]))
    res = identify_sources(store, project, b.interpretation_id, recorded_by="テスト")
    link = store.one("select element_id, new_element_id, verdict, basis_json from identity_link where run_id=?", res.run_id)
    assert link["verdict"] == "一致" and link["element_id"] == a.element_ids["c1"] and link["new_element_id"] == b.element_ids["s1"]
    assert "C1" in link["basis_json"] and "X1" in link["basis_json"]
    assert store.scalar("select kind from identity_run where id=?", res.run_id) == "出どころの間"
    from btruth.effective import element_status
    assert element_status(store, b.element_ids["s1"]) == "同じ要素に統合"
    # b's interpretation has nothing left to approve (its column and relations are merged); the identity items are approved
    with pytest.raises(ValueError):
        approve(store, project, b.interpretation_id)
    approve(store, project, res.interpretation_id)
    columns = approved_elements_by_kind(store, project)["柱"]
    assert columns == [a.element_ids["c1"]]
    c1 = a.element_ids["c1"]
    assert effective_value(store, project, c1, "位置").value == [0.0, 50.0]            # 主 = 構造図
    assert effective_value(store, project, c1, "断面").value == "H-200x200x8x12"
    assert effective_value(store, project, c1, "仕上").value == "鉄骨表し"             # the architect's own attribute
    from btruth.consistency import primary_discipline
    assert primary_discipline(store, project, c1) == "構造"
    check(store, project)
    [diff] = open_of(store, project, "言い分の食い違い（主と従）")
    assert diff["subject_ids"] == [c1] and diff["facts"]["属性"] == "位置"
    assert "構造図" in diff["facts"]["基準"] and "建築平面図" in json.dumps(diff, ensure_ascii=False)


def test_example2_two_candidates_are_handed_to_the_person(tmp_path, terminal_ok):
    from btruth.identity import identify_sources
    project, store = make_project(tmp_path)
    imp(store, project, column_plan(tmp_path / "arch.dxf"), "建築平面図", "設計図", "建築平面図")
    imp(store, project, column_plan(tmp_path / "str.dxf", y=50.0, note=False), "構造図", "設計図", "構造図")
    cols = [element(f"c{i}", "柱", [claim("符号", "C1", [ev("建築平面図@1#5")]), claim("位置", [0.0, 1000.0 * i], [], "mm")],
                    [ev("建築平面図@1#5")]) for i in (1, 2)]
    a = register(store, project, proposal(cols, [relation(f"in{i}", "含む", f"c{i}", STOREY) for i in (1, 2)], sources=["建築平面図@1"]))
    approve(store, project, a.interpretation_id)
    b = register(store, project, proposal([element("s1", "柱", [claim("符号", "C1", [ev("構造図@1#5")])], [ev("構造図@1#5")])],
                                          [relation("in", "含む", "s1", STOREY)], sources=["構造図@1"]))
    res = identify_sources(store, project, b.interpretation_id, recorded_by="テスト")
    link = store.one("select verdict, candidates_json from identity_link where run_id=?", res.run_id)
    assert link["verdict"] == "判断できない" and len(json.loads(link["candidates_json"])) == 2
    from btruth.effective import element_status
    assert element_status(store, b.element_ids["s1"]) == "提案中"


# ---------------------------------------------------------------- 例4: a legend
def legend_dxf(path, meaning="グラスウール 50 (24K)"):
    return write_dxf(path, [("INSERT", "LEGEND", {"name": "INS_GW", "insert": (0, 0)}),
                            ("TEXT", "LEGEND", {"text": meaning, "insert": (500, 0)})], layers=["LEGEND"])


def legend_plan(path):
    return write_dxf(path, [("LINE", "WALL_CENTER", {"start": (0, 4000), "end": (6000, 4000)}),
                            ("INSERT", "INSUL", {"name": "INS_GW", "insert": (1500, 4000)})], layers=["WALL_CENTER", "INSUL"])


def legend_project(tmp_path, approve_legend=False):
    project, store = make_project(tmp_path)
    imp(store, project, legend_dxf(tmp_path / "legend.dxf"), "凡例", "設計図", "凡例")
    imp(store, project, legend_plan(tmp_path / "plan.dxf"), "平面図", "設計図", "建築平面図")
    lg = register(store, project, proposal([element("gw_def", "記号の定義", [
        claim("記号", {"block": "INS_GW"}, [ev("凡例@1#1")]),
        claim("意味", {"材料": "グラスウール", "厚さ": 50, "密度": "24K"}, [ev("凡例@1#2")])], [ev("凡例@1#1"), ev("凡例@1#2")])],
        sources=["凡例@1"]))
    if approve_legend:
        approve(store, project, lg.interpretation_id)
    gw_def = lg.element_ids["gw_def"]
    plan = register(store, project, proposal(
        [element("gw", "材料", [claim("名称", "グラスウール 50", [ev("平面図@1#2")])], [ev("平面図@1#2"), {"element": {"id": gw_def}, "role": "凡例"}]),
         element("wN", "壁", [claim("芯線", seg((0, 4000), (6000, 4000)), [ev("平面図@1#1")], "mm"),
                              claim("断熱材", "グラスウール 50", [ev("平面図@1#2")])],
                 [ev("平面図@1#1"), ev("平面図@1#2"), {"element": {"id": gw_def}, "role": "凡例"}])],
        [relation("in", "含む", "wN", STOREY)], sources=["平面図@1"]))
    return project, store, lg, plan


def test_example4_the_legend_is_the_evidence_and_no_individual_material_is_made(tmp_path, terminal_ok):
    project, store, lg, plan = legend_project(tmp_path)          # the legend is still pending: it may be cited (K)
    assert plan.rejected == 0
    gw_def = lg.element_ids["gw_def"]
    assert count(store, "select count(*) from interpretation_evidence where element_ref_id=? and role='凡例'", gw_def) == 2
    assert count(store, "select count(*) from claim where attribute='種類' and value_json='\"部品\"'") == 0


def test_a_changed_legend_turns_the_elements_read_with_it_into_meaning_changes(tmp_path, terminal_ok):
    from btruth.identity import identify
    project, store, lg, plan = legend_project(tmp_path, approve_legend=True)
    approve(store, project, plan.interpretation_id)
    v2 = imp(store, project, legend_dxf(tmp_path / "legend2.dxf", meaning="ロックウール 50"), "凡例", "設計図", mode="next")
    v1 = store.scalar("select v.id from source_version v join source s on s.id=v.source_id where s.name='凡例' and v.seq=1")
    res = identify(store, project, v1, v2, recorded_by="テスト")
    verdicts = {r["element_id"]: (r["verdict"], r["reason"]) for r in store.all("select * from identity_link where run_id=?", res.run_id)}
    assert verdicts[lg.element_ids["gw_def"]][0] == "意味が変わった"
    assert verdicts[plan.element_ids["wN"]] == ("意味が変わった", "凡例の定義が変わった")
    assert verdicts[plan.element_ids["gw"]][0] == "意味が変わった"


# ---------------------------------------------------------------- a wall-type row that changed (Q27 の足し)
def test_a_changed_wall_type_row_marks_the_judgements_on_its_walls(tmp_path, terminal_ok):
    from btruth.effective import effective_value
    from btruth.identity import identify
    from btruth.review import decide
    project, store = make_project(tmp_path)
    imp(store, project, step2_like_dxf(tmp_path / "plan.dxf"), "平面図", "設計図", "建築平面図")
    imp(store, project, write_text(tmp_path / "wt.csv", "type_code,core,board,boards\nWT-1,LGS65,PB12.5,1\n"), "壁種表", "設計図", "壁種表")
    wt = element("wt1", "壁種", [claim("符号", "WT-1", [ev("壁種表@1#1")]), claim("構成", composition(1), [ev("壁種表@1#1")])], [ev("壁種表@1#1")])
    wall = element("w", "壁", [claim("芯線", seg((2300, 0), (2300, 4000)), [ev("平面図@1#23")], "mm")], [ev("平面図@1#23")])
    r = register(store, project, proposal([wt, wall], [relation("t", "型である", "w", "wt1", evidence=[ev("壁種表@1#1")]),
                                                       relation("in", "含む", "w", STOREY)], sources=["平面図@1", "壁種表@1"]))
    approve(store, project, r.interpretation_id)
    exc = {"面": "B", "材料": "PB12.5", "枚数": 2}
    rid = decide(store, project, r.element_ids["w"], "層の例外", exc, reason="この壁だけ二重", reviewed_by="てっちゃん")
    v2 = imp(store, project, write_text(tmp_path / "wt2.csv", "type_code,core,board,boards\nWT-1,LGS90,PB12.5,1\n"), "壁種表", "設計図", mode="next")
    v1 = store.scalar("select v.id from source_version v join source s on s.id=v.source_id where s.name='壁種表' and v.seq=1")
    res = identify(store, project, v1, v2, recorded_by="テスト")
    assert store.scalar("select verdict from identity_link where run_id=? and element_id=?", res.run_id, r.element_ids["wt1"]) == "意味が変わった"
    marks = store.all("select caused_by_kind, caused_by_id from recheck_mark where review_id=?", rid)
    assert [m["caused_by_kind"] for m in marks] == ["source_version"] and marks[0]["caused_by_id"] == v2
    v = effective_value(store, project, r.element_ids["w"], "層の例外")
    assert v.status == "採用" and v.value == exc and v.recheck is True


def test_a_changed_rules_table_marks_judgements_that_used_it(tmp_path, terminal_ok):
    """Q27 の足し: a judgement whose premises include a table copy is marked when that table changes."""
    from btruth.review import decide
    project, store = import_sample(tmp_path)
    r = register_fixture(store, project, "step1_fixed")
    approve(store, project, r.interpretation_id)
    rid = decide(store, project, r.element_ids["wall_S"], "耐火", "1時間", reason="特記", reviewed_by="てっちゃん")
    rules = project.folder / "rules" / "rules.csv"
    rules.write_text(rules.read_text(encoding="utf-8-sig").replace("gap_tol_mm,50,", "gap_tol_mm,40,"), encoding="utf-8")
    check(store, project)                               # the check loads the tables and looks at the premises
    marks = store.all("select caused_by_kind from recheck_mark where review_id=?", rid)
    assert [m["caused_by_kind"] for m in marks] == ["table_load"]
    check(store, project)                               # not marked twice for the same change
    assert count(store, "select count(*) from recheck_mark where review_id=?", rid) == 1


# ---------------------------------------------------------------- F-6: layer names are hints, not rules
def test_f6_renamed_layers_do_not_change_the_fixed_reading(tmp_path, terminal_ok):
    from btruth.effective import approved_elements_by_kind, room_area_m2
    from btruth.propose import register_proposal
    import ezdxf
    path = step2_like_dxf(tmp_path / "plan.dxf")
    doc = ezdxf.readfile(path)
    for e in doc.modelspace():
        e.dxf.layer = {"_0-2_GRID": "通り芯", "_0-3_ROOM_BOUNDARY": "部屋", "_0-5_WALL_CENTER": "壁芯", "_0-4_ROOM_NAME": "室名"}.get(e.dxf.layer, e.dxf.layer)
    doc.saveas(path)
    project, store = make_project(tmp_path)
    imp(store, project, path, "平面図", "設計図", "建築平面図")
    imp(store, project, WALL_TYPES, "壁種表", "設計図", "壁種表")
    p = step2_fixture_at(0, 0)
    p["source_versions"] = ["平面図@1", "壁種表@1"]
    for e in p["elements"]:
        e["claims"] = [c for c in e["claims"] if c.get("attribute") != "天井高"]
    r = register_proposal(store, project, p, recorded_by="テスト")
    assert r.rejected == 0
    approve(store, project, r.interpretation_id)
    by_kind = approved_elements_by_kind(store, project)
    assert len(by_kind["部屋"]) == 2 and len(by_kind["壁"]) == 5
    assert sum(room_area_m2(store, project, x) for x in by_kind["部屋"]) == pytest.approx(24.0, abs=0.005)
