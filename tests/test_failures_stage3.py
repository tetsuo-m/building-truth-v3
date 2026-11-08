"""docs/FAILURES.md: the failures whose check belongs to stage 3 (design 3-9), reproduced on fictional data.

F-1   a line shared by grid axis, wall centre and room boundary became one wall over the whole axis.
      -> the line gives the position; the extent comes from the physical boundaries (C-2e, 例10).
F-3   the AI ran the approval command and wrote the reason itself.
      -> only the terminal command writes review; Store refuses; the hook stops Claude Code (G-1).
F-5   "no wall" was inferred from the shape of an open door drawn across the whole boundary.
      -> a virtual boundary made by an opening stays a proposal; without a door schedule row it is 要確認.
F-13  writing review rows straight into the SQLite file.
      -> hook on *.sqlite / *.db / sqlite3 (tested in test_guard_confirm), Store refusal, triggers.
"""
from __future__ import annotations

import json

import pytest

from helpers import (OUTSIDE, STOREY, claim, count, element, ev, make_project, proposal, rect_room, relation, seg,
                     write_dxf)
from btruth.intake import import_file


def house_dxf(path):
    """例10: a fictional one-storey house. Y2 (y = 3640) runs from x = -910 to 9100 as one line that is grid
    axis, wall centre and room boundary at once. Rooms: 寝室 / 廊下 (x 0..2730), LDK (x 2730..6370, both
    sides of Y2 without a corner on it), 浴室 / 洗面 (x 6370..8190)."""
    L = lambda a, b, layer="ROOM_BOUNDARY": ("LINE", layer, {"start": a, "end": b})
    ents = [
        L((-910, 3640), (9100, 3640), "GRID"),                       # 1  Y2 (shared line)
        ("TEXT", "GRID", {"text": "Y2", "insert": (-1300, 3640)}),   # 2
        L((0, 0), (8190, 0)), L((8190, 0), (8190, 6370)), L((8190, 6370), (0, 6370)), L((0, 6370), (0, 0)),   # 3-6 outer
        L((2730, 0), (2730, 6370)), L((6370, 0), (6370, 6370)),      # 7, 8 partitions (full height)
        L((0, 3700), (2730, 3700), "WALL_FACE"), L((0, 3580), (2730, 3580), "WALL_FACE"),        # 9, 10 faces west wall
        L((6370, 3700), (8190, 3700), "WALL_FACE"), L((6370, 3580), (8190, 3580), "WALL_FACE"),  # 11, 12 faces east wall
        ("TEXT", "ROOM_NAME", {"text": "LDK", "insert": (4500, 3000)}),   # 13
    ]
    return write_dxf(path, ents, layers=["GRID", "ROOM_BOUNDARY", "WALL_FACE", "ROOM_NAME"])


def house_project(tmp_path):
    project, store = make_project(tmp_path)
    import_file(store, project, house_dxf(tmp_path / "house.dxf"), source_name="平面図", kind="設計図",
                drawing_type="建築平面図", recorded_by="テスト")
    return project, store


def house_rooms():
    """The five rooms with their boundaries; the Y2 boundaries of 寝室/廊下/浴室/洗面 get wall partners."""
    els, rels = [], []
    def add(e, r):
        els.extend(e); rels.extend(r)
    y2 = "平面図@1#1"
    add(*rect_room("廊下", 0, 0, 2730, 3640, ["平面図@1#3", "平面図@1#7", y2, "平面図@1#6"], [None, None, "wall_Y2a", None]))
    add(*rect_room("寝室", 0, 3640, 2730, 6370, [y2, "平面図@1#7", "平面図@1#5", "平面図@1#6"], ["wall_Y2a", None, None, None]))
    add(*rect_room("LDK", 2730, 0, 6370, 6370, ["平面図@1#3", "平面図@1#8", "平面図@1#5", "平面図@1#7"], None, "LDK",
                   [ev("平面図@1#13")]))
    add(*rect_room("洗面", 6370, 0, 8190, 3640, ["平面図@1#3", "平面図@1#4", y2, "平面図@1#8"], [None, None, "wall_Y2b", None]))
    add(*rect_room("浴室", 6370, 3640, 8190, 6370, [y2, "平面図@1#4", "平面図@1#5", "平面図@1#8"], ["wall_Y2b", None, None, None]))
    return els, rels


def correct_walls():
    """C-2e: two walls on Y2 — position from the shared line, extent from the physical boundaries."""
    return [element("wall_Y2a", "壁", [claim("芯線", seg((0, 3640), (2730, 3640)), [ev("平面図@1#1")], "mm")],
                    [ev("平面図@1#1", "主の根拠", "位置"), ev("平面図@1#9", "補助", "面の線"), ev("平面図@1#10", "補助", "面の線")]),
            element("wall_Y2b", "壁", [claim("芯線", seg((6370, 3640), (8190, 3640)), [ev("平面図@1#1")], "mm")],
                    [ev("平面図@1#1", "主の根拠", "位置"), ev("平面図@1#11", "補助"), ev("平面図@1#12", "補助")])], \
           [relation("ca", "含む", "wall_Y2a", STOREY), relation("cb", "含む", "wall_Y2b", STOREY)]


def test_f1_shared_line_gives_two_walls_and_no_wall_inside_ldk_or_outside(tmp_path):
    from btruth.propose import register_proposal
    project, store = house_project(tmp_path)
    els, rels = house_rooms()
    wels, wrels = correct_walls()
    r = register_proposal(store, project, proposal(els + wels, rels + wrels), recorded_by="テスト")
    assert r.rejected == 0
    walls = [json.loads(v[0]) for v in store.all(
        "select value_json from claim where interpretation_id=? and attribute='芯線'", r.interpretation_id)]
    assert len(walls) == 2
    issues = {i["kind"] for i in store.all("select kind from issue where check_run_id=?", r.check_run_id)}
    assert "壁が境界の外に出ている" not in issues and "境界の相手がない壁" not in issues


def test_f1_a_wall_over_the_whole_shared_line_becomes_an_issue(tmp_path):
    """v2 made one wall from -910 to 9100 (through the LDK and outside the house). v3 registers the
    proposal (the rules do not reject it) but hands it to the person: 壁が境界の外に出ている."""
    from btruth.propose import register_proposal
    project, store = house_project(tmp_path)
    els, rels = house_rooms()
    for rel in rels:                       # the naive reading makes the full wall the partner of all four
        if rel["kind"] == "境界の相手":
            rel["to"] = "wall_full"
    full = element("wall_full", "壁", [claim("芯線", seg((-910, 3640), (9100, 3640)), [ev("平面図@1#1")], "mm")],
                   [ev("平面図@1#1")])
    r = register_proposal(store, project, proposal(els + [full], rels + [relation("c", "含む", "wall_full", STOREY)]),
                          recorded_by="テスト")
    item = store.one("select rule_check_status from interpretation_item where element_id=?", r.element_ids["wall_full"])
    assert item["rule_check_status"] == "通った"              # not rejected: the rules hold (D-1), the check hands it over
    issue = store.one("select kind, severity, facts_json, subject_ids_json from issue where check_run_id=? and kind='壁が境界の外に出ている'",
                      r.check_run_id)
    assert issue is not None and issue["severity"] == "要確認"
    facts = json.loads(issue["facts_json"])
    assert facts["outside_mm"] > 50                               # beyond gap_tol_mm
    assert r.element_ids["wall_full"] in json.loads(issue["subject_ids_json"])
    # the uncovered middle (the LDK) and the two ends outside are named, in drawing coordinates
    spans = [(round(a[0]), round(b[0])) for a, b in facts["outside_points"]]
    assert (-910, 0) in spans and (8190, 9100) in spans and (2730, 6370) in spans
    assert len(facts["outside_intervals_mm"]) == 3


def test_f1_a_wall_only_outside_the_house_is_handed_over_not_rejected(tmp_path):
    from btruth.propose import register_proposal
    project, store = house_project(tmp_path)
    els, rels = house_rooms()
    wels, wrels = correct_walls()
    fence = element("fence", "壁", [claim("芯線", seg((8190, 3640), (9100, 3640)), [ev("平面図@1#1")], "mm")], [ev("平面図@1#1")])
    r = register_proposal(store, project, proposal(els + wels + [fence], rels + wrels + [relation("cf", "含む", "fence", STOREY)]),
                          recorded_by="テスト")
    assert store.one("select rule_check_status from interpretation_item where element_id=?", r.element_ids["fence"])[0] == "通った"
    issue = store.one("select subject_ids_json from issue where check_run_id=? and kind='境界の相手がない壁'", r.check_run_id)
    assert issue and json.loads(issue["subject_ids_json"]) == [r.element_ids["fence"]]


def test_f1_grid_axis_keeps_the_whole_line_as_its_evidence(tmp_path):
    """The grid axis element is one, with the whole line; the walls use the same clue (one clue, several
    elements of different kinds — B-1, v2 Q61)."""
    from btruth.propose import register_proposal
    project, store = house_project(tmp_path)
    els, rels = house_rooms()
    wels, wrels = correct_walls()
    axis = element("Y2", "通り芯", [claim("符号", "Y2", [ev("平面図@1#2")]),
                                  claim("線分", seg((-910, 3640), (9100, 3640)), [ev("平面図@1#1")], "mm")],
                   [ev("平面図@1#1"), ev("平面図@1#2")])
    r = register_proposal(store, project, proposal(els + wels + [axis], rels + wrels), recorded_by="テスト")
    assert r.rejected == 0
    clue_id = store.one("select id from clue where seq=1 and kind='LINE'")["id"]
    users = count(store, "select count(distinct i.element_id) from interpretation_evidence e join interpretation_item i on i.id=e.item_id "
                         "where e.clue_id=? and i.interpretation_id=?", clue_id, r.interpretation_id)
    assert users >= 3 + 4         # axis, two walls, four boundaries


# ---------------------------------------------------------------- F-5
def test_f5_a_door_across_the_whole_boundary_is_not_concluded_as_no_wall(tmp_path):
    """C-5 / 決定 Q16 / 例9: the AI proposes 壁 (全長が開口) + 開口 + 建具 and a virtual boundary made by the
    opening. Without a door-schedule row for the tag, registration raises 建具表にない符号 and nothing is
    confirmed; the boundary's 境界の種類 stays a proposal (no effective value)."""
    from btruth.effective import effective_value
    from btruth.propose import register_proposal
    project, store = make_project(tmp_path)
    dxf = write_dxf(tmp_path / "wc.dxf", [
        ("LINE", "ROOM_BOUNDARY", {"start": (0, 0), "end": (910, 0)}),            # 1 the 910 boundary line
        ("INSERT", "DOOR", {"name": "DOOR_S", "insert": (0, 0)}),                 # 2 door block, open across the width
        ("TEXT", "DOOR", {"text": "WD-3", "insert": (450, 200)}),                  # 3 tag
        ("LINE", "ROOM_BOUNDARY", {"start": (910, 0), "end": (910, 1500)}),       # 4
        ("LINE", "ROOM_BOUNDARY", {"start": (910, 1500), "end": (0, 1500)}),      # 5
        ("LINE", "ROOM_BOUNDARY", {"start": (0, 1500), "end": (0, 0)}),           # 6
    ], layers=["ROOM_BOUNDARY", "DOOR"])
    import_file(store, project, dxf, source_name="平面図", kind="設計図", drawing_type="建築平面図", recorded_by="テスト")
    els, rels = rect_room("便所", 0, 0, 910, 1500, ["平面図@1#1", "平面図@1#4", "平面図@1#5", "平面図@1#6"])
    # the AI's reading of the south side: wall (all opening) + opening + door; the boundary is virtual (by the opening)
    for e in els:
        if e["ref"] == "便所_b1":
            e["claims"] = [claim("線分", seg((0, 0), (910, 0)), [ev("平面図@1#1")], "mm"),
                           claim("境界の種類", "仮想", [ev("平面図@1#2")], confidence=0.6),
                           claim("仮想の理由", "開口が作る", [ev("平面図@1#2")], confidence=0.6)]
    wall = element("w9", "壁", [claim("芯線", seg((0, 0), (910, 0)), [ev("平面図@1#1")], "mm")], [ev("平面図@1#1"), ev("平面図@1#2")])
    opening = element("op9", "開口", [claim("位置", 0, [ev("平面図@1#2")], "mm"), claim("幅", 910, [ev("平面図@1#2")], "mm")],
                      [ev("平面図@1#2")])
    door = element("d9", "建具", [claim("符号", "WD-3", [ev("平面図@1#3")]), claim("建具の種類", "扉", [ev("平面図@1#2")], confidence=0.6)],
                   [ev("平面図@1#2"), ev("平面図@1#3")])
    rels += [relation("cw", "含む", "w9", STOREY), relation("cd", "含む", "d9", STOREY),
             relation("v", "くり抜く", "op9", "w9", {"位置": 0}), relation("f", "ふさぐ", "d9", "op9"),
             relation("p", "境界の相手", "便所_b1", "op9")]
    r = register_proposal(store, project, proposal(els + [wall, opening, door], rels), recorded_by="テスト")
    assert r.rejected == 0
    issues = {i["kind"] for i in store.all("select kind from issue where check_run_id=?", r.check_run_id)}
    assert "建具表にない符号" in issues
    # nothing is confirmed by registration: the boundary kind has no effective value (C-5: 確定は人)
    assert effective_value(store, project, r.element_ids["便所_b1"], "境界の種類").status == "なし"
    assert count(store, "select count(*) from claim where mode='採用'") == 0


# ---------------------------------------------------------------- F-3 / F-13 (in-process part)
def test_f3_no_code_path_writes_review_without_the_terminal_command(tmp_path, no_terminal):
    """The only writer of review / review_premise is btruth.review, and it refuses outside a terminal."""
    import inspect
    import btruth.review as review
    from btruth import intake, propose, store as store_mod, checks, effective, measure, show, report, compare
    for mod in (intake, propose, store_mod, checks, effective, measure, show, report, compare):
        src = inspect.getsource(mod)
        assert "insert into review" not in src.lower(), mod.__name__
    assert "insert into review" in inspect.getsource(review).lower()
    project, store = make_project(tmp_path)
    with pytest.raises(review.NotATerminal):
        review.require_terminal(project.db_path)


def test_f13_triggers_stop_rewriting_review_rows(tmp_path, terminal_ok):
    import sqlite3
    from helpers import import_sample, register_fixture
    from btruth.review import approve_interpretation
    project, store = import_sample(tmp_path)
    r = register_fixture(store, project, "step1_fixed")
    rid = approve_interpretation(store, project, r.interpretation_id, reason="x", reviewed_by="x")
    for sql in ("update review set reason='y' where id=?", "delete from review where id=?",
                "update review_premise set ref_id='z' where review_id=?", "delete from review_premise where review_id=?"):
        with pytest.raises(sqlite3.IntegrityError):
            store.conn.execute(sql, (rid,))
