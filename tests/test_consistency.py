"""Stage 5: the consistency check (design I, C-3, C-7, C-10, D-1, J-2, J-3; examples 3, 5, 8, 9, 11).

The check reads only (C-8). It lines up, per element and attribute, the claims of every source, takes the primary
source of rules/authority.csv as the basis, and uses the document ranks of rules/document_rank.csv:
  * a higher-ranked decision that differs → 決定が未反映, with a fix proposed for the lower document (例3, 例9);
  * a human judgement that differs from a higher-ranked decision → 決定が未反映（人の判断と食い違う）(例8);
  * a site drawing that differs → 設計図と施工図の食い違い, shown only, no fix (C-10);
  * 未決 minutes → recorded as 議事録の未決 (記録のみ), no rank;
  * type and instance observations that differ → 言い分の食い違い（型と実物）, the note does not win (例5, 決定 9);
  * the four cases of 例11 and the facing boundaries' kinds (決定 6);
  * documents are compared exactly; drawing measurements use the tolerances (決定 14).
The options carry the subject, the attribute and the value (決定 13), and `choose` applies one (a person, terminal).
"""
from __future__ import annotations

import json

import pytest

from helpers import (OUTSIDE, STOREY, claim, count, element, ev, import_sample, make_project, proposal, register_fixture,
                     relation, seg, step2_fixture_at, step2_like_dxf, WALL_TYPES, FINISH_SCHEDULE)
from stage5 import (approve, check, composition, door_schedule, imp, open_kinds, open_of, ref, register, wall_type_project,
                    wall_type_reading, write_text)


def choose(store, project, issue_id, code, **kw):
    from btruth.review import choose_option
    return choose_option(store, project, issue_id, code, reason=kw.pop("reason", "決めた"), reviewed_by="てっちゃん", **kw)


# ---------------------------------------------------------------- 例3: minutes win, the wall-type table gets a fix; site drawing shown only
def test_example3_minutes_win_and_the_wall_type_table_gets_a_fix(tmp_path, terminal_ok):
    from btruth.effective import effective_value
    project, store = wall_type_project(tmp_path)
    r = register(store, project, wall_type_reading(store))
    approve(store, project, r.interpretation_id)
    check(store, project)
    wt1 = r.element_ids["wt1"]
    [late] = open_of(store, project, "決定が未反映")
    assert late["subject_ids"] == [wt1]
    assert late["facts"]["正とみなす"]["出どころ"] == "議事録3" and late["facts"]["従"]["出どころ"] == "壁種表"
    assert "壁種表" in json.dumps(late["proposal"], ensure_ascii=False)
    assert [o["code"] for o in late["options"]][:1] == ["adopt_higher"]
    [site] = open_of(store, project, "設計図と施工図の食い違い")
    assert site["proposal"] is None and [o["label"] for o in site["options"]] == ["確認した（記録のみ）"]
    # the undecided sentence has no rank; it stays as a record (保留として残る)
    undecided = [i for i in store.all("select * from issue where kind='議事録の未決'")]
    assert len(undecided) == 1 and undecided[0]["severity"] == "記録のみ"
    # nothing adopted, the effective value stays the primary source's (the person decides)
    assert count(store, "select count(*) from claim where mode='採用'") == 0
    assert effective_value(store, project, wt1, "構成").value == composition(1)
    # the person approves the minutes' value through the option
    choose(store, project, late["id"], "adopt_higher")
    v = effective_value(store, project, wt1, "構成")
    assert v.status == "採用" and v.value == composition(2)
    assert "決定が未反映" not in open_kinds(store, project)


def test_example8_a_judgement_that_differs_from_later_minutes(tmp_path, terminal_ok):
    from btruth.review import decide
    project, store = wall_type_project(tmp_path, with_site=False)
    p = wall_type_reading(store, with_site=False)
    minutes_claims = [c for c in p["claims"] if c["subject"] == "wt1"]
    p["claims"] = [c for c in p["claims"] if c["subject"] != "wt1"]
    r = register(store, project, p)
    approve(store, project, r.interpretation_id)
    wt1 = r.element_ids["wt1"]
    rid = decide(store, project, wt1, "構成", composition(1), reason="コストの都合", reviewed_by="てっちゃん")
    m = register(store, project, proposal([], claims=[dict(c, subject={"id": wt1}) for c in minutes_claims], sources=["議事録3@1"]))
    approve(store, project, m.interpretation_id)
    check(store, project)
    [late] = open_of(store, project, "決定が未反映（人の判断と食い違う）")
    assert late["subject_ids"] == [wt1] and rid in json.dumps(late["basis"])
    assert [o["code"] for o in late["options"]] == ["follow_minutes", "keep_judgement"]
    assert count(store, "select count(*) from claim where mode='採用' and subject_id=?", wt1) == 1      # not overwritten
    choose(store, project, late["id"], "keep_judgement", reason="コストの都合のまま")
    from btruth.effective import effective_value
    assert effective_value(store, project, wt1, "構成").value == composition(1)
    assert "決定が未反映（人の判断と食い違う）" not in open_kinds(store, project)


# ---------------------------------------------------------------- 例9: the door schedule, the minutes and the opening's width
def door_project(tmp_path, schedule_rows="AD-1,片開き扉,800,2000,木製フラッシュ\n", minutes=True, door_tag="AD-1"):
    project, store = make_project(tmp_path)
    imp(store, project, step2_like_dxf(tmp_path / "plan.dxf", door=True, door_tag=door_tag), "平面図", "設計図", "建築平面図")
    imp(store, project, WALL_TYPES, "壁種表", "設計図", "壁種表")
    imp(store, project, door_schedule(tmp_path, schedule_rows), "建具表", "設計図", "建具表")
    if minutes:
        imp(store, project, write_text(tmp_path / "m.md", "# 第4回\n\nAD-1 の幅を 900 とする。\n"), "議事録4", "議事録", date="2026-10-15")
    p = step2_fixture_at(0, 0, door=True)
    p["source_versions"] = ["平面図@1", "壁種表@1", "建具表@1"] + (["議事録4@1"] if minutes else [])
    for e in p["elements"]:
        e["claims"] = [c for c in e["claims"] if c.get("attribute") != "天井高"]
        if e["ref"] == "door_A":
            e["claims"] = [c if c["attribute"] != "符号" else dict(c, value=door_tag) for c in e["claims"]]
    if schedule_rows:
        row = ref(store, "建具表", 1, "AD-1")
        p["elements"].append(element("ad1", "建具の型", [claim("符号", "AD-1", [ev(row)]), claim("幅", 800, [ev(row)], "mm"),
                                                       claim("高さ", 2000, [ev(row)], "mm"), claim("建具の種類", "片開き扉", [ev(row)])], [ev(row)]))
        p["relations"].append(relation("door_type", "型である", "door_A", "ad1", evidence=[ev(row)]))
    if minutes:
        s = ref(store, "議事録4", 1, "900")
        p["claims"].append(dict(claim("幅", 900, [ev(s)], "mm"), subject="ad1", statement_kind="決定", source="議事録4@1"))
    r = register(store, project, p)
    approve(store, project, r.interpretation_id)
    return project, store, r


def test_example9_minutes_900_and_schedule_800_offer_the_target_and_the_width(tmp_path, terminal_ok):
    from btruth.effective import effective_value
    from btruth.propose import opening_segment
    from btruth import geometry
    project, store, r = door_project(tmp_path)
    check(store, project)
    [late] = open_of(store, project, "決定が未反映")
    ad1, door, opening = r.element_ids["ad1"], r.element_ids["door_A"], r.element_ids["opening_A"]
    assert late["subject_ids"][0] == ad1
    labels = [o["label"] for o in late["options"]]
    assert any("型（AD-1 全体）" in l and "呼び幅" in l for l in labels)
    assert any("この建具だけ" in l and "呼び幅" in l for l in labels)
    assert any("開口の幅" in l for l in labels)
    effects = {o["code"]: json.loads(o["effect_json"]) for o in late["options"]}
    assert effects["type_width"]["claims"][0] == {"subject": ad1, "attribute": "幅", "value": 900, "unit": "mm"}
    assert effects["door_width"]["claims"][0]["subject"] == door
    assert effects["opening_width"]["claims"][0]["subject"] == opening
    assert geometry.length(opening_segment(store, project, opening)) == pytest.approx(800.0)
    choose(store, project, late["id"], "opening_width")
    assert effective_value(store, project, opening, "幅").value == 900
    assert geometry.length(opening_segment(store, project, opening)) == pytest.approx(900.0)   # the hole uses the same value
    assert effective_value(store, project, ad1, "幅").value == 800                            # the type is unchanged


def test_documents_are_compared_exactly_drawings_with_tolerance(tmp_path, terminal_ok):
    """決定 14: 800 vs 805 between two documents is a difference; 800 vs 840 between the drawing's opening and the
    schedule is within door_width_tol_mm (100)."""
    project, store, r = door_project(tmp_path, minutes=False)
    from btruth.review import decide  # noqa: F401
    check(store, project)
    assert "言い分の食い違い（主と従）" not in open_kinds(store, project)
    imp(store, project, write_text(tmp_path / "m2.md", "AD-1 の幅を 805 とする。\n"), "議事録5", "議事録", date="2026-10-20")
    s = ref(store, "議事録5", 1, "805")
    m = register(store, project, proposal([], claims=[dict(claim("幅", 805, [ev(s)], "mm"), subject={"id": r.element_ids["ad1"]},
                                                             statement_kind="決定")], sources=["議事録5@1"]))
    approve(store, project, m.interpretation_id)
    check(store, project)
    assert len(open_of(store, project, "決定が未反映")) == 1


def test_a_door_tag_missing_from_the_schedule_is_not_counted(tmp_path, terminal_ok):
    from btruth.consistency import counted_doors
    project, store, r = door_project(tmp_path, schedule_rows="AD-1,片開き扉,800,2000,木製フラッシュ\n", minutes=False, door_tag="AD-9")
    check(store, project)
    assert open_of(store, project, "建具表にない符号")
    assert r.element_ids["door_A"] not in counted_doors(store, project)


# ---------------------------------------------------------------- 例5: materials in two tiers
def materials_project(tmp_path, boards=1):
    project, store = make_project(tmp_path)
    note = [("TEXT", "NOTE", {"text": "PB 二重張り", "insert": (2400, 2000)})]
    imp(store, project, step2_like_dxf(tmp_path / "plan.dxf", extra=note), "平面図", "設計図", "建築平面図")
    imp(store, project, write_text(tmp_path / "wt.csv", f"type_code,core,board,boards,sides,total\nWT-1,LGS65,PB12.5,{boards},両面,{65 + 25 * boards}\n"),
        "壁種表", "設計図", "壁種表")
    row = "壁種表@1#1"
    els = [element("wt1", "壁種", [claim("符号", "WT-1", [ev(row)]), claim("構成", composition(boards), [ev(row)]),
                                  claim("厚さ", 65 + 25 * boards, [ev(row)], "mm")], [ev(row)]),
           element("asm", "層の組み立て", [claim("名前", "WT-1 の層", [ev(row)])], [ev(row)]),
           element("lgs", "材料", [claim("名称", "LGS65", [ev(row)])], [ev(row)]),
           element("pb", "材料", [claim("名称", "PB12.5", [ev(row)])], [ev(row)]),
           element("w7", "壁", [claim("芯線", seg((2300, 0), (2300, 4000)), [ev("平面図@1#23")], "mm"),
                                claim("層の例外", {"面": "両", "枚数": 2}, [ev("平面図@1#24")])], [ev("平面図@1#23"), ev("平面図@1#24")])]
    rels = [relation("has", "組み立てを持つ", "wt1", "asm"),
            relation("l1", "層である", "asm", "pb", {"順": 1, "面": "A", "厚さ": 12.5, "枚数": boards}),
            relation("l2", "層である", "asm", "lgs", {"順": 2, "面": "芯", "厚さ": 65}),
            relation("l3", "層である", "asm", "pb", {"順": 3, "面": "B", "厚さ": 12.5, "枚数": boards}),
            relation("t", "型である", "w7", "wt1"), relation("u", "使う", "w7", "asm", {"基準の面": "芯線", "向き": "対称", "ずれ": 0}),
            relation("in", "含む", "w7", STOREY)]
    r = register(store, project, proposal(els, rels, sources=["平面図@1", "壁種表@1"]))
    approve(store, project, r.interpretation_id)
    return project, store, r


def test_example5_two_tiers_no_board_elements_and_the_note_does_not_win(tmp_path, terminal_ok):
    from btruth.consistency import layers_of
    from btruth.review import decide
    project, store, r = materials_project(tmp_path)
    w7 = r.element_ids["w7"]
    # one wall adds two relations (型である, 使う), no element per board
    assert count(store, "select count(*) from relation where from_element_id=? and kind in ('型である','使う')", w7) == 2
    assert count(store, "select count(*) from claim where attribute='種類' and value_json in ('\"部品\"')") == 0
    layers = layers_of(store, project, w7)
    assert [(l["面"], l["材料"], l["枚数"]) for l in layers] == [("A", "PB12.5", 1), ("芯", "LGS65", None), ("B", "PB12.5", 1)]
    check(store, project)
    [diff] = open_of(store, project, "言い分の食い違い（型と実物）")
    assert set(diff["subject_ids"]) == {w7, r.element_ids["wt1"]}
    assert [o["code"] for o in diff["options"]] == ["this_wall", "follow_type", "change_type"]
    # the person decides "this wall only, side B triple": the adopted exception wins over the type (E-5)
    decide(store, project, w7, "層の例外", {"面": "B", "材料": "PB12.5", "枚数": 3}, reason="B 面だけ三重", reviewed_by="てっちゃん")
    layers = layers_of(store, project, w7)
    assert [(l["面"], l["枚数"]) for l in layers] == [("A", 1), ("芯", None), ("B", 3)]


def test_type_and_instance_observations_of_the_same_attribute(tmp_path, terminal_ok):
    from btruth.effective import effective_value
    project, store, r = materials_project(tmp_path)
    w7 = r.element_ids["w7"]
    m = register(store, project, proposal([], claims=[dict(claim("厚さ", 150, [ev("平面図@1#24")], "mm"), subject={"id": w7})],
                                          sources=["平面図@1"]))
    approve(store, project, m.interpretation_id)
    assert effective_value(store, project, w7, "厚さ").status == "決まらない"
    check(store, project)
    kinds = open_kinds(store, project)
    assert kinds.count("言い分の食い違い（型と実物）") == 2      # the 厚さ and the 層の例外


# ---------------------------------------------------------------- 例11: the four cases of the partner's intervals
def room_p(north_walls, north_partners, extra_elements=(), extra_relations=(), north_kind="物理的"):
    """Room P (0,0)-(3640,5460) with walls S, E, W and the given north walls."""
    corners = [(0, 0), (3640, 0), (3640, 5460), (0, 5460)]
    els = [element("P", "部屋", [claim("名前", "P")])]
    rels = [relation("P_in", "集める", "P", STOREY)]
    walls = {"S": seg((0, 0), (3640, 0)), "E": seg((3640, 0), (3640, 5460)), "W": seg((0, 5460), (0, 0))}
    for k, s in walls.items():
        els.append(element(f"w{k}", "壁", [claim("芯線", s, [], "mm")]))
        rels.append(relation(f"w{k}_in", "含む", f"w{k}", STOREY))
    for ref_, s in north_walls.items():
        els.append(element(ref_, "壁", [claim("芯線", s, [], "mm")]))
        rels.append(relation(f"{ref_}_in", "含む", ref_, STOREY))
    partners = [["wS"], ["wE"], north_partners, ["wW"]]
    for i in range(4):
        a, b = corners[i], corners[(i + 1) % 4]
        kind = north_kind if i == 2 else "物理的"
        els.append(element(f"P{i}", "空間の境界", [claim("線分", seg(a, b), [], "mm"), claim("境界の種類", kind)]))
        rels.append(relation(f"P{i}_b", "区切る", f"P{i}", "P", {"順": i + 1}))
        for p in partners[i]:
            rels.append(relation(f"P{i}_{p}", "境界の相手", f"P{i}", p))
    return proposal(els + list(extra_elements), rels + list(extra_relations), sources=["平面図@1"])


def outside_north(ref_, x0, x1, partner):
    return ([element(ref_, "空間の境界", [claim("線分", seg((x0, 5460), (x1, 5460)), [], "mm"), claim("境界の種類", "物理的")])],
            [relation(f"{ref_}_b", "区切る", ref_, OUTSIDE), relation(f"{ref_}_p", "境界の相手", ref_, partner)])


def eleven(tmp_path, p, schedule=None):
    project, store = import_sample(tmp_path)
    if schedule is not None:
        imp(store, project, door_schedule(tmp_path, schedule), "建具表", "設計図", "建具表")
    r = register(store, project, p)
    approve(store, project, r.interpretation_id)
    check(store, project)
    return project, store, r


WALL_KINDS = ("壁が境界の外に出ている", "壁が途中で終わる", "境界の相手がない壁")


def test_example11_case1_a_wall_longer_than_the_boundary(tmp_path, terminal_ok):
    from btruth.consistency import boundary_intervals
    oe, orl = outside_north("oN", 7280, -100, "wN")
    p = room_p({"wN": seg((-100, 5460), (7280, 5460))}, ["wN"], oe, orl)
    project, store, r = eleven(tmp_path, p)
    assert not [k for k in open_kinds(store, project) if k in WALL_KINDS]
    iv = boundary_intervals(store, project, r.element_ids["P2"])
    assert iv["walls"] == [[r.element_ids["wN"], [0.0, 3640.0]]]


def test_example11_case2_two_walls_on_one_boundary(tmp_path, terminal_ok):
    from btruth.consistency import boundary_intervals
    p = room_p({"wN1": seg((3640, 5460), (1640, 5460)), "wN2": seg((1640, 5460), (0, 5460))}, ["wN1", "wN2"])
    project, store, r = eleven(tmp_path, p)
    assert not [k for k in open_kinds(store, project) if k in WALL_KINDS]
    iv = boundary_intervals(store, project, r.element_ids["P2"])
    assert sorted(x[1] for x in iv["walls"]) == [[0.0, 2000.0], [2000.0, 3640.0]]


def door_on_north(opening_at, width, tag):
    els = [element("op", "開口", [claim("位置", opening_at, [], "mm"), claim("幅", width, [], "mm")]),
           element("door", "建具", [claim("符号", tag), claim("建具の種類", "扉")])]
    rels = [relation("op_v", "くり抜く", "op", "wN", {"位置": opening_at}), relation("door_f", "ふさぐ", "door", "op"),
            relation("door_in", "含む", "door", STOREY), relation("P2_op", "境界の相手", "P2", "op")]
    return els, rels


def test_example11_case3_wall_ends_and_a_door_from_the_schedule(tmp_path, terminal_ok):
    """The wall is extended to the door's interval; walls [0,2000], opening [2000,3640] (from the boundary's start)."""
    from btruth.consistency import boundary_intervals
    els, rels = door_on_north(0.0, 1640, "WD-5")          # the wall N runs (3640,5460) → (0,5460): wall-based 0..1640
    p = room_p({"wN": seg((3640, 5460), (0, 5460))}, ["wN"], els, rels,
               north_kind=[{"区間": [0, 1640], "両端": [[3640, 5460], [2000, 5460]], "値": "仮想", "理由": "開口が作る"},
                           {"区間": [1640, 3640], "両端": [[2000, 5460], [0, 5460]], "値": "物理的"}])
    project, store, r = eleven(tmp_path, p, schedule="WD-5,片開き扉,1600,2000,鋼製\n")
    assert not [k for k in open_kinds(store, project) if k in WALL_KINDS + ("建具表にない符号",)]
    iv = boundary_intervals(store, project, r.element_ids["P2"])
    assert iv["walls"] == [[r.element_ids["wN"], [1640.0, 3640.0]]]
    assert iv["openings"] == [[r.element_ids["op"], [0.0, 1640.0]]]
    assert count(store, "select count(*) from claim where mode='採用'") == 0         # F-5: nothing confirmed by the shape


def test_example11_case3_without_the_schedule_row_and_f5(tmp_path, terminal_ok):
    els, rels = door_on_north(0.0, 1640, "WD-5")
    p = room_p({"wN": seg((3640, 5460), (0, 5460))}, ["wN"], els, rels)
    project, store, r = eleven(tmp_path, p, schedule="AD-1,片開き扉,800,2000,木製\n")
    assert "建具表にない符号" in open_kinds(store, project)
    assert count(store, "select count(*) from claim where mode='採用'") == 0


def test_example11_case4_one_wall_touches_twice(tmp_path, terminal_ok):
    from btruth.consistency import boundary_intervals
    els, rels = door_on_north(1340.0, 800, "AD-1")         # wall-based from (3640,5460): x 2300 → 1500
    p = room_p({"wN": seg((3640, 5460), (0, 5460))}, ["wN"], els, rels)
    project, store, r = eleven(tmp_path, p, schedule="AD-1,片開き扉,800,2000,木製\n")
    assert not [k for k in open_kinds(store, project) if k in WALL_KINDS]
    iv = boundary_intervals(store, project, r.element_ids["P2"])     # distances from the boundary's start (x 3640)
    assert sorted(x[1] for x in iv["walls"]) == [[0.0, 1340.0], [2140.0, 3640.0]]
    assert iv["openings"] == [[r.element_ids["op"], [1340.0, 2140.0]]]


def test_facing_boundaries_whose_kinds_differ(tmp_path, terminal_ok):
    """決定 6: P's north is virtual over [0,1640] (from P's start), R's south is physical all along."""
    els, rels = door_on_north(0.0, 1640, "WD-5")
    r_south = element("R0", "空間の境界", [claim("線分", seg((0, 5460), (3640, 5460)), [], "mm"), claim("境界の種類", "物理的")])
    room_r = element("R", "部屋", [claim("名前", "R")])
    extra_e = els + [room_r, r_south]
    extra_r = rels + [relation("R_in", "集める", "R", STOREY), relation("R0_b", "区切る", "R0", "R", {"順": 1}),
                      relation("R0_p", "境界の相手", "R0", "wN"), relation("face", "向かい合う", "P2", "R0")]
    p = room_p({"wN": seg((3640, 5460), (0, 5460))}, ["wN"], extra_e, extra_r,
               north_kind=[{"区間": [0, 1640], "両端": [[3640, 5460], [2000, 5460]], "値": "仮想", "理由": "開口が作る"},
                           {"区間": [1640, 3640], "両端": [[2000, 5460], [0, 5460]], "値": "物理的"}])
    project, store, r = eleven(tmp_path, p, schedule="WD-5,片開き扉,1600,2000,鋼製\n")
    [face] = open_of(store, project, "向かい合う境界の種類の食い違い")
    assert set(face["subject_ids"]) == {r.element_ids["P2"], r.element_ids["R0"]}
    assert face["facts"]["区間"] == [[2000.0, 5460.0], [3640.0, 5460.0]]


# ---------------------------------------------------------------- the open issues: latest per scope, held ones carried over (決定 15)
def test_a_new_check_replaces_issues_in_its_scope_and_keeps_held_and_outside_ones(tmp_path, terminal_ok):
    from btruth.effective import open_issues
    from btruth.review import hold_issue
    project, store, r = materials_project(tmp_path)
    check(store, project)
    check(store, project)
    assert open_kinds(store, project).count("言い分の食い違い（型と実物）") == 1        # replaced, not doubled
    [diff] = open_of(store, project, "言い分の食い違い（型と実物）")
    hold_issue(store, project, diff["id"], reason="あとで", reviewed_by="てっちゃん")
    check(store, project)
    held = [i for i in open_issues(store, project) if i["kind"] == "言い分の食い違い（型と実物）"]
    assert [i["id"] for i in held] == [diff["id"]] and held[0]["held"]
    # a check of another scope leaves this issue alone
    check(store, project, scope=[r.element_ids["lgs"]])
    assert diff["id"] in {i["id"] for i in open_issues(store, project)}


def test_stage4_moves_still_give_exactly_the_expected_issues(tmp_path, terminal_ok):
    """The full check must not add spurious issues to the step2 samples (3-5-1)."""
    from helpers import STEP2
    project, store = import_sample(tmp_path, STEP2)
    r = register_fixture(store, project, "step2_fixed")
    approve(store, project, r.interpretation_id)
    check(store, project)
    assert open_kinds(store, project) == ["名前がない空間"]
