"""The review commands (design G-1): terminal only, y/N, premises recorded, adopted claims in the same
transaction, the check before approval (decision 12), and the acceptance numbers of samples/*/expected.md."""
from __future__ import annotations

import json
import sqlite3

import pytest

from helpers import (OUTSIDE, STEP2, STOREY, claim, count, element, ev, import_sample, proposal, register_fixture,
                     relation, seg)


def approve_all(store, project, interpretation_id):
    from btruth.review import approve_interpretation
    return approve_interpretation(store, project, interpretation_id, reason="図面と見比べた", reviewed_by="てっちゃん")


# ---------------------------------------------------------------- acceptance: step1 / step2 numbers
def test_step1_expected_values_after_approval(tmp_path, terminal_ok):
    from btruth.effective import (approved_elements_by_kind, open_issues, room_area_m2, room_perimeter_m,
                                  effective_value)
    project, store = import_sample(tmp_path)
    r = register_fixture(store, project, "step1_fixed")
    review_id = approve_all(store, project, r.interpretation_id)
    by_kind = approved_elements_by_kind(store, project)
    assert len(by_kind["部屋"]) == 1 and len(by_kind["壁"]) == 4 and len(by_kind["通り芯"]) == 4
    assert len(by_kind["階"]) == 1
    room = by_kind["部屋"][0]
    from btruth.effective import boundaries_of_room
    assert len(boundaries_of_room(store, project, room)) == 4
    assert room_area_m2(store, project, room) == pytest.approx(24.00, abs=0.005)
    assert room_perimeter_m(store, project, room) == pytest.approx(20.000, abs=0.0005)
    assert effective_value(store, project, room, "天井高").value == 2700
    assert effective_value(store, project, room, "室番号").value == "101"
    from btruth.effective import types_of
    for wall in by_kind["壁"]:
        [wt] = types_of(store, wall)                                   # 型である → 壁種 WT-3 (E-5)
        assert effective_value(store, project, wt, "符号").value == "WT-3"
        assert effective_value(store, project, wall, "厚さ").value == 100 and effective_value(store, project, wall, "厚さ").via_type == wt
    assert open_issues(store, project) == []
    # the review row and its premises (G-1): basis clues, assumption, table loads
    rev = store.one("select target_kind, action, reviewed_by, reason, choice_json, signature from review where id=?", review_id)
    assert rev["target_kind"] == "interpretation" and rev["action"] == "まとめて承認"
    assert rev["reviewed_by"] == "てっちゃん" and rev["reason"] == "図面と見比べた" and rev["signature"] is None
    assert len(json.loads(rev["choice_json"])["item_ids"]) == 48
    kinds = {k[0] for k in store.all("select distinct kind from review_premise where review_id=?", review_id)}
    assert {"clue", "assumption", "table_load"} <= kinds
    assert count(store, "select count(*) from review_premise where review_id=? and kind='clue'", review_id) >= 21


def test_step2_expected_values_after_approval(tmp_path, terminal_ok):
    from btruth.effective import (approved_elements_by_kind, boundaries_of_room, effective_value, open_issues,
                                  room_area_m2, room_perimeter_m)
    project, store = import_sample(tmp_path, STEP2)
    r = register_fixture(store, project, "step2_fixed")
    approve_all(store, project, r.interpretation_id)
    by_kind = approved_elements_by_kind(store, project)
    assert len(by_kind["部屋"]) == 2 and len(by_kind["壁"]) == 5
    rooms = {rid: room_area_m2(store, project, rid) for rid in by_kind["部屋"]}
    left, right = r.element_ids["room_left"], r.element_ids["room_101"]
    assert rooms[left] == pytest.approx(9.20, abs=0.005) and rooms[right] == pytest.approx(14.80, abs=0.005)
    assert sum(rooms.values()) == pytest.approx(24.00, abs=0.005)
    assert room_perimeter_m(store, project, left) == pytest.approx(12.600, abs=0.0005)
    assert room_perimeter_m(store, project, right) == pytest.approx(15.400, abs=0.0005)
    assert len(boundaries_of_room(store, project, left)) == 4 and len(boundaries_of_room(store, project, right)) == 4
    assert sum(len(boundaries_of_room(store, project, rid)) for rid in by_kind["部屋"]) == 8
    assert effective_value(store, project, right, "天井高").value == 2700
    assert effective_value(store, project, left, "天井高").value is None       # never guessed
    issues = open_issues(store, project)
    assert [i["kind"] for i in issues] == ["名前がない空間"]
    # wall extents agree with the union of the partner boundaries' intervals (C-2e)
    from btruth.checks import wall_range_facts
    for wall in by_kind["壁"]:
        facts = wall_range_facts(store, project, wall)
        assert facts["outside_mm"] <= 0.1, facts


def test_naming_the_room_closes_the_issue(tmp_path, terminal_ok):
    from btruth.effective import effective_value, open_issues
    from btruth.review import name_element
    project, store = import_sample(tmp_path, STEP2)
    r = register_fixture(store, project, "step2_fixed")
    approve_all(store, project, r.interpretation_id)
    left = r.element_ids["room_left"]
    [issue] = open_issues(store, project)
    name_element(store, project, left, "倉庫", reason="設計者に確認", reviewed_by="てっちゃん", issue_id=issue["id"])
    assert effective_value(store, project, left, "名前").value == "倉庫"
    assert effective_value(store, project, left, "名前").status == "採用"
    assert open_issues(store, project) == []


def test_exclude_room_writes_an_adopted_claim(tmp_path, terminal_ok):
    from btruth.effective import effective_value, open_issues
    from btruth.review import exclude_room
    project, store = import_sample(tmp_path, STEP2)
    r = register_fixture(store, project, "step2_fixed")
    approve_all(store, project, r.interpretation_id)
    left = r.element_ids["room_left"]
    [issue] = open_issues(store, project)
    exclude_room(store, project, left, reason="PS。部屋ではない", reviewed_by="てっちゃん", issue_id=issue["id"])
    v = effective_value(store, project, left, "部屋として扱う")
    assert v.value is False and v.status == "採用"
    assert open_issues(store, project) == []
    # the element and its id stay (E-6, B-12)
    assert count(store, "select count(*) from element where id=?", left) == 1


# ---------------------------------------------------------------- the check before approval (決定 12)
def door_proposal():
    wall = element("w", "壁", [claim("芯線", seg((0, 0), (6000, 0)), [ev("平面図@1#14")], "mm")], [ev("平面図@1#14")])
    opening = element("op", "開口", [claim("位置", 1000, [], "mm"), claim("幅", 800, [], "mm")], [ev("平面図@1#13")])
    door = element("door", "建具", [claim("符号", "AD-1", [ev("平面図@1#21")]), claim("建具の種類", "扉")], [ev("平面図@1#21")])
    return proposal([wall, opening, door],
                    [relation("c", "含む", "w", STOREY), relation("v", "くり抜く", "op", "w", {"位置": 1000}),
                     relation("f", "ふさぐ", "door", "op"), relation("dc", "含む", "door", STOREY)])


def item_of(store, element_id):
    return store.one("select id from interpretation_item where element_id=? and kind='要素を作る'", element_id)["id"]


def test_approving_a_door_whose_opening_was_rejected_is_stopped(tmp_path, terminal_ok):
    from btruth.propose import register_proposal
    from btruth.review import ApprovalBlocked, approve_items, reject_items
    project, store = import_sample(tmp_path)
    r = register_proposal(store, project, door_proposal(), recorded_by="テスト")
    approve_items(store, project, [item_of(store, r.element_ids["w"])], reason="壁は確か", reviewed_by="てっちゃん")
    reject_items(store, project, [item_of(store, r.element_ids["op"])], reason="開口は誤読", reviewed_by="てっちゃん")
    before = count(store, "select count(*) from review")
    with pytest.raises(ApprovalBlocked) as exc:
        approve_items(store, project, [item_of(store, r.element_ids["door"])], reason="扉は確か", reviewed_by="てっちゃん")
    assert "開口" in str(exc.value) or "ふさぐ" in str(exc.value)
    assert count(store, "select count(*) from review") == before          # nothing was written


def test_approving_door_and_opening_together_passes(tmp_path, terminal_ok):
    from btruth.propose import register_proposal
    from btruth.review import approve_items
    from btruth.effective import item_status
    project, store = import_sample(tmp_path)
    r = register_proposal(store, project, door_proposal(), recorded_by="テスト")
    items = [item_of(store, r.element_ids[k]) for k in ("w", "op", "door")]
    approve_items(store, project, items, reason="一緒に", reviewed_by="てっちゃん")
    assert all(item_status(store, i) == "承認済み" for i in items)


def test_relation_item_needs_both_ends_approved(tmp_path, terminal_ok):
    from btruth.propose import register_proposal
    from btruth.review import ApprovalBlocked, approve_items
    project, store = import_sample(tmp_path)
    r = register_proposal(store, project, door_proposal(), recorded_by="テスト")
    rel_item = store.one("select id from interpretation_item where relation_id=?", r.relation_ids["f"])["id"]
    with pytest.raises(ApprovalBlocked):
        approve_items(store, project, [rel_item], reason="x", reviewed_by="てっちゃん")


# ---------------------------------------------------------------- other actions
def test_reject_requires_a_reason_and_hold_writes_only_a_review(tmp_path, terminal_ok):
    from btruth.effective import item_status
    from btruth.review import hold_items, reject_items
    project, store = import_sample(tmp_path)
    r = register_fixture(store, project, "step1_fixed")
    item = item_of(store, r.element_ids["grid_X1"])          # a grid axis points at nothing (決定 12 does not interfere)
    with pytest.raises(ValueError):
        reject_items(store, project, [item], reason="", reviewed_by="てっちゃん")
    hold_items(store, project, [item], reason="あとで見る", reviewed_by="てっちゃん")
    assert item_status(store, item) == "保留"
    assert count(store, "select count(*) from claim where mode='採用'") == 0
    reject_items(store, project, [item], reason="誤読", reviewed_by="てっちゃん")
    assert item_status(store, item) == "却下"
    # the latest review decides; a later approval re-opens it (rows are never rewritten, B-6)
    from btruth.review import approve_items
    approve_items(store, project, [item], reason="見直した", reviewed_by="てっちゃん")
    assert item_status(store, item) == "承認済み"
    assert count(store, "select count(*) from review where target_id=?", item) == 3


def test_decision_writes_review_and_adopted_claim_in_one_transaction(tmp_path, terminal_ok):
    from btruth.review import decide
    project, store = import_sample(tmp_path)
    r = register_fixture(store, project, "step1_fixed")
    approve_all(store, project, r.interpretation_id)
    wall = r.element_ids["wall_S"]
    rid = decide(store, project, wall, "芯線", seg((0, 0), (6000, 10)), reason="境界線に合わせる", reviewed_by="てっちゃん",
                 unit="mm")
    c = store.one("select mode, review_id, source_version_id, value_json from claim where subject_id=? and attribute='芯線' and mode='採用'", wall)
    assert c["review_id"] == rid and c["source_version_id"] is None
    rev = store.one("select action, choice_json, target_kind, target_id from review where id=?", rid)
    assert rev["action"] == "判断" and rev["target_kind"] == "element" and rev["target_id"] == wall
    assert json.loads(rev["choice_json"])["attribute"] == "芯線"
    assert count(store, "select count(*) from review_premise where review_id=?", rid) >= 1


def test_the_listing_is_shown_before_the_question(tmp_path, terminal_ok):
    """G-1: まとめての承認は一覧を出してから y/N. A confirm callback that answers no writes nothing."""
    from btruth.review import approve_interpretation
    project, store = import_sample(tmp_path)
    r = register_fixture(store, project, "step1_fixed")
    seen = {}

    def confirm(listing: str) -> bool:
        seen["listing"] = listing
        return False

    result = approve_interpretation(store, project, r.interpretation_id, reason="x", reviewed_by="てっちゃん", confirm=confirm)
    assert result is None
    assert "空間の境界" in seen["listing"] and "壁" in seen["listing"] and "平面図@1" in seen["listing"]
    assert count(store, "select count(*) from review") == 0


def test_approve_interpretation_can_leave_items_out(tmp_path, terminal_ok):
    from btruth.effective import item_status
    from btruth.review import approve_interpretation
    project, store = import_sample(tmp_path)
    r = register_fixture(store, project, "step1_fixed")
    left_out = item_of(store, r.element_ids["grid_X1"])
    approve_interpretation(store, project, r.interpretation_id, reason="x", reviewed_by="てっちゃん", exclude=[left_out])
    assert item_status(store, left_out) == "提案中"
    assert item_status(store, item_of(store, r.element_ids["grid_X2"])) == "承認済み"


# ---------------------------------------------------------------- the guards (G-1 (b), (d); F-13)
def test_review_refuses_outside_a_terminal(tmp_path, no_terminal):
    """G-1 (b): called from anything that is not a terminal (and no test override), nothing is written."""
    from btruth.review import NotATerminal, approve_interpretation
    project, store = import_sample(tmp_path)
    r = register_fixture(store, project, "step1_fixed")        # intake and registration work (B-2, D-4)
    with pytest.raises(NotATerminal):
        approve_interpretation(store, project, r.interpretation_id, reason="x", reviewed_by="x")
    assert count(store, "select count(*) from review") == 0
    assert count(store, "select count(*) from review_premise") == 0


def test_store_insert_refuses_review_tables(tmp_path):
    project, store = import_sample(tmp_path)
    with pytest.raises(PermissionError):
        store.insert("review", "x", target_kind="x", target_id="x", action="承認", reviewed_by="x")
    with pytest.raises(PermissionError):
        store.insert("review_premise", "x", review_id="x", kind="clue", ref_id="x")


def test_terminal_override_does_not_work_outside_the_temporary_folder(terminal_ok):
    """BRIEF step3 §3-4: the test override must not become a way into a real project database."""
    from conftest import ROOT
    from btruth.review import is_terminal_for
    assert is_terminal_for(ROOT / "out" / "some-project" / "db" / "truth.sqlite") is False
    import tempfile
    from pathlib import Path
    assert is_terminal_for(Path(tempfile.gettempdir()) / "pytest-x" / "project" / "db" / "truth.sqlite") is True


def test_review_rows_cannot_be_updated_or_deleted_after_a_real_approval(tmp_path, terminal_ok):
    project, store = import_sample(tmp_path)
    r = register_fixture(store, project, "step1_fixed")
    rid = approve_all(store, project, r.interpretation_id)
    with pytest.raises(sqlite3.IntegrityError):
        store.conn.execute("update review set action='却下' where id=?", (rid,))
    with pytest.raises(sqlite3.IntegrityError):
        store.conn.execute("delete from review where id=?", (rid,))
    with pytest.raises(sqlite3.IntegrityError):
        store.conn.execute("delete from review_premise where review_id=?", (rid,))
