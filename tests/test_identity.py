"""Stage 4: identity between versions and carrying approved interpretations over (design H, 3-3b, G-1, G-2, D-1).

Acceptance (BRIEF_v3_step4 §3, design 3-7 and 3-5-1):
  * step2_moved: every id kept, one batch of moves waiting (wall 1 + boundaries 6) -> one batch approval ->
    the effective values are the new positions and the only open issue is 名前がない空間;
  * step2_boundary_only: nothing adopted, the boundaries move, the wall stays (2300); after the batch approval
    one ずれ issue with two options;
  * mesh_json: nodes 6, edges 7, anchors 4;
  * a partition added to the right room only: that room is 判断できない (split), the left room's boundary keeps
    its id and its judgement (F-2);
  * a door that moved with its wall is not a move; its absolute position is computed from the new wall (例9);
  * a judgement whose basis changed gets a recheck mark and the effective value stays adopted (決定 9);
  * the same drawing read twice does not shake the ids (例6);
  * only the plan changed: the clues of the unchanged tables are not "not found" (決定 16);
  * F-9: two versions with a shifted origin are aligned on the grid labels and recorded in intake_log.
"""
from __future__ import annotations

import json

import pytest

from helpers import (FINISH_SCHEDULE, JW_ORIGIN, STEP2, STEP2_BOUNDARY_ONLY, STEP2_MOVED, WALL_TYPES, count,
                     import_sample, make_project, register_fixture, seg, step2_fixture_at, step2_like_dxf)
from btruth.intake import import_file


# ---------------------------------------------------------------- helpers
def version(store, name, seq):
    return store.scalar("select v.id from source_version v join source s on s.id=v.source_id where s.name=? and v.seq=?",
                        name, seq)


def approve_all(store, project, interpretation_id):
    from btruth.review import approve_interpretation
    return approve_interpretation(store, project, interpretation_id, reason="図面と見比べた", reviewed_by="てっちゃん")


def sample_v1_approved(tmp_path):
    project, store = import_sample(tmp_path, STEP2)
    r = register_fixture(store, project, "step2_fixed")
    approve_all(store, project, r.interpretation_id)
    return project, store, r


def next_plan(store, project, path):
    return import_file(store, project, path, source_name="平面図", mode="next", recorded_by="テスト").source_version_id


def identify(store, project, v2):
    from btruth.identity import identify as run
    return run(store, project, version(store, "平面図", 1), v2, recorded_by="テスト")


def verdict(store, run_id, element_id):
    row = store.one("select verdict, reason, facts_json from identity_link where run_id=? and element_id=?", run_id, element_id)
    return row["verdict"] if row else None


def J(x, y):
    return [JW_ORIGIN[0] + x, JW_ORIGIN[1] + y]


def approve_moves(store, project, run_id, **kw):
    from btruth.review import approve_moves as go
    return go(store, project, run_id, reason="図面の変更を確かめた", reviewed_by="てっちゃん", **kw)


# ---------------------------------------------------------------- step2_moved (3-5-1)
def test_step2_moved_keeps_every_id_and_waits_for_one_batch(tmp_path, terminal_ok):
    from btruth.effective import effective_value, open_issues, room_area_m2
    project, store, r = sample_v1_approved(tmp_path)
    elements_before = count(store, "select count(*) from element")
    res = identify(store, project, next_plan(store, project, STEP2_MOVED))
    ids = r.element_ids
    # every element keeps its id: nothing new, nothing gone, nothing undecided
    assert count(store, "select count(*) from element") == elements_before
    assert res.counts["追加"] == 0 and res.counts["消えた"] == 0 and res.counts["判断できない"] == 0
    assert verdict(store, res.run_id, ids["wall_A"]) == "移動"
    facts = json.loads(store.scalar("select facts_json from identity_link where run_id=? and element_id=?", res.run_id, ids["wall_A"]))
    assert facts["移動量_mm"] == pytest.approx(500.0)
    moved_boundaries = {k for k in ("room_left_b1", "room_left_b2", "room_left_b3", "room_101_b1", "room_101_b3", "room_101_b4")}
    for k in moved_boundaries:
        assert verdict(store, res.run_id, ids[k]) == "移動", k
    for k in ("room_left", "room_101", "room_left_b4", "room_101_b2", "wall_S", "wall_N", "wall_E", "wall_W", "grid_X1", "wt3",
              "out_S", "out_N"):
        assert verdict(store, res.run_id, ids[k]) == "一致", k
    assert len(res.move_items) == 7                                  # wall 1 + boundaries 6
    pending = [i for i in open_issues(store, project) if i["kind"] == "移動の承認待ち"]
    assert len(pending) == 1 and len(pending[0]["facts"]["item_ids"]) == 7
    # before the approval nothing moves (B-9, F-4)
    assert effective_value(store, project, ids["wall_A"], "芯線").value == [J(2300, 0), J(2300, 4000)]
    assert room_area_m2(store, project, ids["room_left"]) == pytest.approx(9.20, abs=0.005)
    # one batch approval
    rid = approve_moves(store, project, res.run_id)
    rev = store.one("select target_kind, action, choice_json from review where id=?", rid)
    assert rev["target_kind"] == "identity_run" and rev["action"] == "移動をまとめて承認"
    assert len(json.loads(rev["choice_json"])["item_ids"]) == 7
    from btruth.checks import check_after_moves
    check_after_moves(store, project, res.run_id, recorded_by="テスト")
    assert effective_value(store, project, ids["wall_A"], "芯線").value == [J(2800, 0), J(2800, 4000)]
    assert room_area_m2(store, project, ids["room_left"]) == pytest.approx(11.20, abs=0.005)
    assert room_area_m2(store, project, ids["room_101"]) == pytest.approx(12.80, abs=0.005)
    assert [i["kind"] for i in open_issues(store, project)] == ["名前がない空間"]
    assert count(store, "select count(*) from claim where mode='採用'") == 0


def test_mesh_json_has_nodes_6_edges_7_anchors_4(tmp_path, terminal_ok):
    project, store, r = sample_v1_approved(tmp_path)
    res = identify(store, project, next_plan(store, project, STEP2_MOVED))
    mesh = json.loads(store.scalar("select mesh_json from identity_run where id=?", res.run_id))
    assert mesh["nodes_base"] == 6 and mesh["nodes_new"] == 6
    assert mesh["edges_base"] == 7 and mesh["edges_new"] == 7
    assert len(mesh["anchors"]) == 4
    assert len(mesh["moved"]) == 2 and all(m["distance_mm"] == pytest.approx(500.0) for m in mesh["moved"])
    assert sorted(f["verdict"] for f in mesh["faces"]) == ["一致", "一致"]
    run = store.one("select frame_json, counts_json, interpretation_id from identity_run where id=?", res.run_id)
    assert json.loads(run["frame_json"])["aligned"] is True
    counts = json.loads(run["counts_json"])
    assert counts["移動"] == 7 and counts["人に渡した数"] >= 1 and counts["自動で処理した数"] >= 1
    agent = store.one("select a.name, a.kind from interpretation i join agent a on a.id=i.agent_id where i.id=?",
                      run["interpretation_id"])
    assert agent["name"] == "同定" and agent["kind"] == "規則の読み手"


# ---------------------------------------------------------------- step2_boundary_only (例1)
def test_step2_boundary_only_keeps_the_wall_and_hands_over_one_offset(tmp_path, terminal_ok):
    from btruth.effective import effective_value, open_issues
    project, store, r = sample_v1_approved(tmp_path)
    ids = r.element_ids
    res = identify(store, project, next_plan(store, project, STEP2_BOUNDARY_ONLY))
    assert verdict(store, res.run_id, ids["wall_A"]) == "一致"         # its centre line is still at 2300
    assert verdict(store, res.run_id, ids["room_left_b2"]) == "移動"
    assert len(res.move_items) == 6                                   # boundaries only
    approve_moves(store, project, res.run_id)
    from btruth.checks import check_after_moves
    check_after_moves(store, project, res.run_id, recorded_by="テスト")
    assert effective_value(store, project, ids["wall_A"], "芯線").value == [J(2300, 0), J(2300, 4000)]
    assert effective_value(store, project, ids["room_left_b2"], "線分").value == [J(2800, 0), J(2800, 4000)]
    assert count(store, "select count(*) from claim where mode='採用'") == 0
    issues = open_issues(store, project)
    kinds = sorted(i["kind"] for i in issues)
    assert kinds == ["名前がない空間", "壁と境界のずれ"]
    [offset] = [i for i in issues if i["kind"] == "壁と境界のずれ"]
    assert ids["wall_A"] in offset["subject_ids"]
    assert {ids["room_left_b2"], ids["room_101_b4"]} <= set(offset["subject_ids"])
    assert offset["facts"]["ずれ_mm"] == pytest.approx(500.0)
    assert [o["label"] for o in offset["options"]] == ["境界線に合わせる", "追従を外す"]
    # running the check again does not add a second issue
    check_after_moves(store, project, res.run_id, recorded_by="テスト")
    assert sum(1 for i in open_issues(store, project) if i["kind"] == "壁と境界のずれ") == 1


# ---------------------------------------------------------------- F-2: a partition added to one room only
def test_partition_added_to_the_right_room_only_keeps_the_left_boundary(tmp_path, terminal_ok):
    from btruth.effective import effective_value, relations_from
    from btruth.review import decide
    project, store = make_project(tmp_path)
    import_file(store, project, step2_like_dxf(tmp_path / "v1.dxf"), source_name="平面図", kind="設計図",
                drawing_type="建築平面図", recorded_by="テスト")
    import_file(store, project, WALL_TYPES, source_name="壁種表", kind="設計図", drawing_type="壁種表", recorded_by="テスト")
    import_file(store, project, FINISH_SCHEDULE, source_name="仕上表", kind="設計図", drawing_type="仕上表", recorded_by="テスト")
    from btruth.propose import register_proposal
    r = register_proposal(store, project, step2_fixture_at(0, 0), recorded_by="テスト")
    approve_all(store, project, r.interpretation_id)
    ids = r.element_ids
    # a judgement on the left room's east boundary (the side the T-node will land on)
    rid = decide(store, project, ids["room_left_b2"], "境界の種類", "物理的", reason="壁がある", reviewed_by="てっちゃん")
    extra = [("LINE", "_0-3_ROOM_BOUNDARY", {"start": (2300, 2000), "end": (6000, 2000)}),
             ("LINE", "_0-5_WALL_CENTER", {"start": (2300, 2000), "end": (6000, 2000)})]
    res = identify(store, project, next_plan(store, project, step2_like_dxf(tmp_path / "v2.dxf", extra=extra)))
    mesh = json.loads(store.scalar("select mesh_json from identity_run where id=?", res.run_id))
    assert mesh["nodes_new"] == 8
    assert len(mesh["edges_split"]) == 2
    assert verdict(store, res.run_id, ids["room_101"]) == "判断できない"
    link = store.one("select reason, candidates_json from identity_link where run_id=? and element_id=?", res.run_id, ids["room_101"])
    assert link["reason"] == "分割" and len(json.loads(link["candidates_json"])) == 2
    for k in ("room_101_b1", "room_101_b2", "room_101_b3", "room_101_b4"):
        assert verdict(store, res.run_id, ids[k]) == "判断できない", k
    # the left room and its four boundaries are 一致; the judgement stays, without a recheck mark
    for k in ("room_left", "room_left_b1", "room_left_b2", "room_left_b3", "room_left_b4"):
        assert verdict(store, res.run_id, ids[k]) == "一致", k
    v = effective_value(store, project, ids["room_left_b2"], "境界の種類")
    assert v.status == "採用" and v.review_id == rid and v.recheck is False
    assert count(store, "select count(*) from recheck_mark where review_id=?", rid) == 0
    # only 向かい合う changes: it ends, waiting for the person to settle the split room
    assert not [x for x in relations_from(store, ids["room_left_b2"], "向かい合う")]
    assert any(i for i in res.issues if store.scalar("select kind from issue where id=?", i) == "部屋の分割・統合")
    assert res.counts["分割"] == 1


# ---------------------------------------------------------------- 例9: a door that moves with its wall
def door_project(tmp_path):
    project, store = make_project(tmp_path)
    import_file(store, project, step2_like_dxf(tmp_path / "v1.dxf", door=True), source_name="平面図", kind="設計図",
                drawing_type="建築平面図", recorded_by="テスト")
    import_file(store, project, WALL_TYPES, source_name="壁種表", kind="設計図", drawing_type="壁種表", recorded_by="テスト")
    import_file(store, project, FINISH_SCHEDULE, source_name="仕上表", kind="設計図", drawing_type="仕上表", recorded_by="テスト")
    from btruth.propose import register_proposal
    r = register_proposal(store, project, step2_fixture_at(0, 0, door=True), recorded_by="テスト")
    approve_all(store, project, r.interpretation_id)
    return project, store, r


def test_a_door_moving_with_its_wall_is_not_a_move(tmp_path, terminal_ok):
    from btruth.propose import opening_segment
    project, store, r = door_project(tmp_path)
    ids = r.element_ids
    res = identify(store, project, next_plan(store, project, step2_like_dxf(tmp_path / "v2.dxf", wc_x=2800, door=True)))
    assert verdict(store, res.run_id, ids["wall_A"]) == "移動"
    assert verdict(store, res.run_id, ids["opening_A"]) == "一致"
    assert verdict(store, res.run_id, ids["door_A"]) == "一致"
    reason = store.scalar("select reason from identity_link where run_id=? and element_id=?", res.run_id, ids["opening_A"])
    assert "壁に従う" in reason
    moved_elements = {store.scalar("select element_id from interpretation_item where id=?", i) for i in res.move_items}
    assert ids["opening_A"] not in moved_elements and ids["door_A"] not in moved_elements
    # the absolute position is computed from the wall's effective centre line (never stored)
    assert opening_segment(store, project, ids["opening_A"]) == ((2300.0, 1100.0), (2300.0, 1900.0))
    approve_moves(store, project, res.run_id)
    assert opening_segment(store, project, ids["opening_A"]) == ((2800.0, 1100.0), (2800.0, 1900.0))


def test_a_door_left_behind_by_its_wall_goes_to_the_person(tmp_path, terminal_ok):
    project, store, r = door_project(tmp_path)
    ids = r.element_ids
    res = identify(store, project, next_plan(store, project,
                                             step2_like_dxf(tmp_path / "v2.dxf", wc_x=2800, door=True, door_dx=-500)))
    assert verdict(store, res.run_id, ids["wall_A"]) == "移動"
    assert verdict(store, res.run_id, ids["opening_A"]) == "判断できない"
    assert any(store.scalar("select kind from issue where id=?", i) == "建具が壁から外れた" for i in res.issues)


def test_a_door_tag_changed_in_place_is_a_change_of_meaning(tmp_path, terminal_ok):
    project, store, r = door_project(tmp_path)
    ids = r.element_ids
    res = identify(store, project, next_plan(store, project, step2_like_dxf(tmp_path / "v2.dxf", door=True, door_tag="AD-2",
                                                                            door_name="DOOR_SL")))
    assert verdict(store, res.run_id, ids["door_A"]) == "意味が変わった"
    assert verdict(store, res.run_id, ids["wall_A"]) == "一致"
    assert res.counts["意味が変わった"] >= 1
    moved_elements = {store.scalar("select element_id from interpretation_item where id=?", i) for i in res.move_items}
    assert ids["door_A"] not in moved_elements


# ---------------------------------------------------------------- 決定 9: a judgement whose basis moved
def test_a_judged_wall_that_moved_gets_a_recheck_mark_and_keeps_its_adopted_value(tmp_path, terminal_ok):
    from btruth.effective import effective_value
    from btruth.review import decide, resolve_recheck
    project, store, r = sample_v1_approved(tmp_path)
    ids = r.element_ids
    adopted = [J(2300, 0), J(2300, 4000)]
    rid = decide(store, project, ids["wall_A"], "芯線", adopted, reason="現地で確認", reviewed_by="てっちゃん", unit="mm")
    res = identify(store, project, next_plan(store, project, STEP2_MOVED))
    assert verdict(store, res.run_id, ids["wall_A"]) == "移動"
    marks = store.all("select id, reason from recheck_mark where review_id=?", rid)
    assert len(marks) == 1
    # the judged wall is not in the batch list (決定 Q15)
    from btruth.review import moves_listing_items
    listed = {store.scalar("select element_id from interpretation_item where id=?", i["id"])
              for i in moves_listing_items(store, project, res.run_id)}
    assert ids["wall_A"] not in listed and len(listed) == 6
    v = effective_value(store, project, ids["wall_A"], "芯線")
    assert v.status == "採用" and v.value == adopted and v.recheck is True
    approve_moves(store, project, res.run_id)
    v = effective_value(store, project, ids["wall_A"], "芯線")
    assert v.status == "採用" and v.value == adopted and v.recheck is True      # still adopted (B-9)
    # the person resolves the mark: 保つ keeps the value and clears the mark
    resolve_recheck(store, project, marks[0]["id"], "保つ", reason="壁はそのまま", reviewed_by="てっちゃん")
    v = effective_value(store, project, ids["wall_A"], "芯線")
    assert v.status == "採用" and v.value == adopted and v.recheck is False


def test_recheck_resolution_can_change_or_withdraw_the_adopted_value(tmp_path, terminal_ok):
    from btruth.effective import effective_value
    from btruth.review import decide, resolve_recheck
    project, store, r = sample_v1_approved(tmp_path)
    ids = r.element_ids
    rid = decide(store, project, ids["wall_A"], "芯線", [J(2300, 0), J(2300, 4000)], reason="x", reviewed_by="てっちゃん", unit="mm")
    res = identify(store, project, next_plan(store, project, STEP2_MOVED))
    [mark] = store.all("select id from recheck_mark where review_id=?", rid)
    new = [J(2800, 0), J(2800, 4000)]
    resolve_recheck(store, project, mark["id"], "変える", reason="図面に合わせる", reviewed_by="てっちゃん", value=new, unit="mm")
    v = effective_value(store, project, ids["wall_A"], "芯線")
    assert v.status == "採用" and v.value == new and v.recheck is False
    # withdraw: the adopted value ends; the approved observation (v1, 2300) counts again
    rid2 = v.review_id
    project2_mark = store.insert("recheck_mark", "テスト", review_id=rid2, caused_by_kind="identity_run", caused_by_id=res.run_id,
                                 reason="テストの印", detail_json=None)
    store.commit()
    resolve_recheck(store, project, project2_mark, "取り消す", reason="判断をやめる", reviewed_by="てっちゃん")
    v = effective_value(store, project, ids["wall_A"], "芯線")
    assert v.status == "承認済みの観測" and v.value == [J(2300, 0), J(2300, 4000)]


# ---------------------------------------------------------------- 決定 10: newest approved observation per source
def test_a_held_move_keeps_the_previous_approved_value(tmp_path, terminal_ok):
    from btruth.effective import effective_value
    from btruth.review import hold_items
    project, store, r = sample_v1_approved(tmp_path)
    ids = r.element_ids
    res = identify(store, project, next_plan(store, project, STEP2_MOVED))
    wall_item = next(i for i in res.move_items
                     if store.scalar("select element_id from interpretation_item where id=?", i) == ids["wall_A"])
    hold_items(store, project, [wall_item], reason="あとで", reviewed_by="てっちゃん")
    assert effective_value(store, project, ids["wall_A"], "芯線").value == [J(2300, 0), J(2300, 4000)]
    from btruth.review import approve_items
    approve_items(store, project, [wall_item], reason="見た", reviewed_by="てっちゃん")
    assert effective_value(store, project, ids["wall_A"], "芯線").value == [J(2800, 0), J(2800, 4000)]


# ---------------------------------------------------------------- 例6: the same drawing twice
def test_the_same_geometry_twice_keeps_every_id(tmp_path, terminal_ok):
    project, store = make_project(tmp_path)
    import_file(store, project, step2_like_dxf(tmp_path / "v1.dxf"), source_name="平面図", kind="設計図",
                drawing_type="建築平面図", recorded_by="テスト")
    import_file(store, project, WALL_TYPES, source_name="壁種表", kind="設計図", drawing_type="壁種表", recorded_by="テスト")
    import_file(store, project, FINISH_SCHEDULE, source_name="仕上表", kind="設計図", drawing_type="仕上表", recorded_by="テスト")
    from btruth.propose import register_proposal
    r = register_proposal(store, project, step2_fixture_at(0, 0), recorded_by="テスト")
    approve_all(store, project, r.interpretation_id)
    before = count(store, "select count(*) from element")
    # byte-different file (an extra empty layer) with the same geometry
    from helpers import write_dxf  # noqa: F401
    v2 = step2_like_dxf(tmp_path / "v1_again.dxf", extra=[])
    import ezdxf
    doc = ezdxf.readfile(v2)
    doc.layers.add("UNUSED")
    doc.saveas(v2)
    res = identify(store, project, next_plan(store, project, v2))
    assert res.counts["一致"] > 0
    assert res.counts["移動"] == 0 and res.counts["判断できない"] == 0 and res.counts["消えた"] == 0
    assert res.move_items == []
    assert count(store, "select count(*) from element") == before
    assert count(store, "select count(*) from recheck_mark") == 0


# ---------------------------------------------------------------- F-9: the origin differs between versions
def test_shifted_origin_is_aligned_on_the_grid_labels_and_recorded(tmp_path, terminal_ok):
    project, store = make_project(tmp_path)
    import_file(store, project, step2_like_dxf(tmp_path / "v1.dxf"), source_name="平面図", kind="設計図",
                drawing_type="建築平面図", recorded_by="テスト")
    import_file(store, project, WALL_TYPES, source_name="壁種表", kind="設計図", drawing_type="壁種表", recorded_by="テスト")
    from btruth.propose import register_proposal
    p = step2_fixture_at(0, 0)
    p["source_versions"] = ["平面図@1", "壁種表@1"]
    for e in p["elements"]:
        e["claims"] = [c for c in e["claims"] if c.get("attribute") != "天井高"]
    r = register_proposal(store, project, p, recorded_by="テスト")
    approve_all(store, project, r.interpretation_id)
    v2 = next_plan(store, project, step2_like_dxf(tmp_path / "v2.dxf", dx=210000000.0, dy=148500000.0))
    res = identify(store, project, v2)
    frame = json.loads(store.scalar("select frame_json from identity_run where id=?", res.run_id))
    assert frame["aligned"] is True and frame["labels"] == ["X1", "Y1"]
    assert frame["delta_mm"] == [210000000.0, 148500000.0]
    assert res.counts["移動"] == 0 and res.counts["判断できない"] == 0 and res.counts["消えた"] == 0
    assert verdict(store, res.run_id, r.element_ids["grid_X1"]) == "一致"
    logs = [json.loads(x["detail_json"]) for x in store.all(
        "select detail_json from intake_log where source_version_id=? and kind='座標の枠の揃え方'", v2)]
    assert any(l.get("identity_run_id") == res.run_id for l in logs)


# ---------------------------------------------------------------- 決定 16: the tables did not change
def test_unchanged_tables_are_carried_over(tmp_path, terminal_ok):
    project, store, r = sample_v1_approved(tmp_path)
    res = identify(store, project, next_plan(store, project, STEP2_MOVED))
    ids = r.element_ids
    assert verdict(store, res.run_id, ids["wt3"]) == "一致"
    basis = json.loads(store.scalar("select basis_json from identity_link where run_id=? and element_id=?", res.run_id, ids["wt3"]))
    assert basis["carried_over"] >= 1 and basis["not_found"] == 0
    # the room's ceiling height comes from the finish schedule: not missing either
    facts = json.loads(store.scalar("select facts_json from identity_link where run_id=? and element_id=?", res.run_id, ids["room_101"]))
    assert not any("仕上表" in str(x) for x in facts.get("not_found_clues", []))


# ---------------------------------------------------------------- impact (二段目) and the scope for the AI (案4)
def test_impact_rows_and_reread_scope(tmp_path, terminal_ok):
    project, store, r = sample_v1_approved(tmp_path)
    extra = [("LINE", "_0-3_ROOM_BOUNDARY", {"start": (JW_ORIGIN[0] + 2300, JW_ORIGIN[1] + 2000), "end": (JW_ORIGIN[0] + 6000, JW_ORIGIN[1] + 2000)})]
    res = identify(store, project, next_plan(store, project,
                                             step2_like_dxf(tmp_path / "v2.dxf", dx=JW_ORIGIN[0], dy=JW_ORIGIN[1], extra=extra)))
    actions = {row["action"] for row in store.all("select action from impact where run_id=?", res.run_id)}
    assert "再解釈" in actions and "再計算だけ" in actions
    assert res.scope["clue_ids"], "the new partition line is in the scope for the AI"
    assert res.scope["margin_mm"] == 1000.0
    assert res.scope["context_element_ids"]


# ---------------------------------------------------------------- identity of pending elements (Q25)
def test_identity_works_on_a_proposal_not_yet_approved_and_moves_wait_for_it(tmp_path, terminal_ok):
    from btruth.review import ApprovalBlocked
    project, store = import_sample(tmp_path, STEP2)
    r = register_fixture(store, project, "step2_fixed")              # not approved
    res = identify(store, project, next_plan(store, project, STEP2_MOVED))
    assert len(res.move_items) == 7
    basis = json.loads(store.scalar("select basis_json from identity_link where run_id=? and element_id=?", res.run_id,
                                    r.element_ids["wall_A"]))
    assert basis["根拠の時点"] == "提案の根拠（未承認）"
    with pytest.raises(ApprovalBlocked):
        approve_moves(store, project, res.run_id)
    approve_all(store, project, r.interpretation_id)
    approve_moves(store, project, res.run_id)


# ---------------------------------------------------------------- the diff report (text and HTML)
def test_diff_report_counts_and_lists(tmp_path, terminal_ok):
    from btruth.diff import build_diff, render_text, write_diff
    project, store, r = sample_v1_approved(tmp_path)
    res = identify(store, project, next_plan(store, project, STEP2_MOVED))
    d = build_diff(store, project, res.run_id)
    assert d["counts"]["移動"] == 7 and d["counts"]["一致"] > 0
    text = render_text(d)
    for word in ("一致", "移動", "追加", "消えた", "判断できない", "自動で処理した数", "人に渡した数", "500"):
        assert word in text
    out = write_diff(store, project, res.run_id, tmp_path / "diff.html", html=True, recorded_by="テスト")
    body = out.read_text(encoding="utf-8")
    assert "<html" in body and "移動" in body
    assert store.one("select 1 from generation where path=?", str(out))
