"""The effective value (有効値, design D-1 改訂 6, decision Q1 / 9 / 10 / 11):
採用 → approved observation (per source the latest approved) → default structure of the rule reader.
A recheck mark does not remove an adopted value; type vs instance only among adopted values."""
from __future__ import annotations

import json

import pytest

from helpers import (STEP2, claim, count, element, ev, import_sample, proposal, register_fixture, relation, seg, STOREY)


def test_default_structure_counts_without_approval(tmp_path):
    from btruth.effective import effective_value
    project, store = import_sample(tmp_path)
    from btruth.common import dumps
    storey = store.one("select subject_id from claim where attribute='名前' and value_json=?", dumps("1階"))["subject_id"]
    v = effective_value(store, project, storey, "名前")
    assert v.value == "1階" and v.status == "既定の構成"


def test_observation_counts_only_after_approval(tmp_path, terminal_ok):
    from btruth.effective import effective_value
    from btruth.review import approve_items
    project, store = import_sample(tmp_path)
    r = register_fixture(store, project, "step1_fixed")
    room = r.element_ids["room_101"]
    before = effective_value(store, project, room, "室番号")
    assert before.value is None and before.status == "なし"
    item = store.one("select id from interpretation_item where element_id=? and kind='要素を作る'", room)["id"]
    approve_items(store, project, [item], reason="確かめた", reviewed_by="テスト")
    after = effective_value(store, project, room, "室番号")
    assert after.value == "101" and after.status == "承認済みの観測" and after.recheck is False


def test_adopted_value_wins_and_survives_a_recheck_mark(tmp_path, terminal_ok):
    """決定 9: the adopted value stays effective even with a recheck mark; it is shown as 要再確認."""
    from btruth.effective import effective_value
    from btruth.review import approve_interpretation, decide
    project, store = import_sample(tmp_path)
    r = register_fixture(store, project, "step1_fixed")
    approve_interpretation(store, project, r.interpretation_id, reason="テスト", reviewed_by="テスト")
    wall = r.element_ids["wall_S"]
    review_id = decide(store, project, wall, "芯線", seg((0, 0), (6000, 10)), reason="境界線に合わせる",
                       reviewed_by="テスト", unit="mm")
    v = effective_value(store, project, wall, "芯線")
    assert v.status == "採用" and v.value == seg((0, 0), (6000, 10)) and v.review_id == review_id
    # a recheck mark (written by the identity run in stage 4; here directly) does not change the value
    store.insert("recheck_mark", "テスト", review_id=review_id, caused_by_kind="source_version", caused_by_id="x",
                 reason="根拠の手掛かりが変わった", detail_json="{}")
    store.commit()
    v2 = effective_value(store, project, wall, "芯線")
    assert v2.value == seg((0, 0), (6000, 10)) and v2.status == "採用" and v2.recheck is True


def test_latest_approved_observation_per_source_is_used(tmp_path, terminal_ok):
    """改訂 6 (10): the same subject / attribute / source with approved observations in two versions →
    the latest version's approved one; a rejected newer one leaves the older value in force."""
    from btruth.effective import effective_value
    from btruth.intake import import_file
    from btruth.propose import register_proposal
    from btruth.review import approve_items, reject_items
    project, store = import_sample(tmp_path)
    r = register_fixture(store, project, "step1_fixed")
    room = r.element_ids["room_101"]
    from btruth.review import approve_interpretation
    approve_interpretation(store, project, r.interpretation_id, reason="テスト", reviewed_by="テスト")
    # version 2 of the plan (same drawing with the partition) → a second reading of the same room
    import_file(store, project, STEP2, source_name="平面図", mode="next", recorded_by="テスト")
    p2 = proposal([], claims=[{"subject": {"id": room}, "attribute": "室名", "value": "事務室２", "confidence": 0.8,
                               "evidence": [ev("平面図@2#21")]}], sources=["平面図@2"])
    r2 = register_proposal(store, project, p2, recorded_by="テスト")
    item2 = store.one("select id from interpretation_item where interpretation_id=? and kind='言い分'", r2.interpretation_id)["id"]
    assert effective_value(store, project, room, "室名").value == "事務室"        # not approved yet
    reject_items(store, project, [item2], reason="誤読", reviewed_by="テスト")
    assert effective_value(store, project, room, "室名").value == "事務室"        # rejected: the older one stays
    p3 = proposal([], claims=[{"subject": {"id": room}, "attribute": "室名", "value": "事務室３", "confidence": 0.8,
                               "evidence": [ev("平面図@2#21")]}], sources=["平面図@2"])
    r3 = register_proposal(store, project, p3, recorded_by="テスト")
    item3 = store.one("select id from interpretation_item where interpretation_id=? and kind='言い分'", r3.interpretation_id)["id"]
    approve_items(store, project, [item3], reason="確かめた", reviewed_by="テスト")
    v = effective_value(store, project, room, "室名")
    assert v.value == "事務室３" and v.status == "承認済みの観測"


def test_type_and_instance_only_adopted_values_take_precedence(tmp_path, terminal_ok):
    """決定 9: instance adopted → type adopted → observations; conflicting observations are 決まらない."""
    from btruth.effective import effective_value
    from btruth.propose import register_proposal
    from btruth.review import approve_interpretation, decide
    project, store = import_sample(tmp_path)
    r = register_fixture(store, project, "step1_fixed")
    approve_interpretation(store, project, r.interpretation_id, reason="テスト", reviewed_by="テスト")
    wall, wt3 = r.element_ids["wall_S"], r.element_ids["wt3"]
    # the wall has no own 厚さ; the type's approved observation (100) is read through 型である
    v = effective_value(store, project, wall, "厚さ")
    assert v.value == 100 and v.status == "承認済みの観測" and v.via_type == wt3
    # an observation on the instance that disagrees with the type → 決まらない (no silent winner)
    p = proposal([], claims=[{"subject": {"id": wall}, "attribute": "厚さ", "value": 115, "unit": "mm", "confidence": 0.7,
                              "evidence": [ev("平面図@1#14")]}])
    r2 = register_proposal(store, project, p, recorded_by="テスト")
    approve_interpretation(store, project, r2.interpretation_id, reason="テスト", reviewed_by="テスト")
    v2 = effective_value(store, project, wall, "厚さ")
    assert v2.status == "決まらない" and v2.value is None
    # the person's decision on the instance wins over everything
    decide(store, project, wall, "厚さ", 120, reason="この壁だけ", reviewed_by="テスト", unit="mm")
    assert effective_value(store, project, wall, "厚さ").value == 120
    # a decision on the type is used by instances without their own decision
    decide(store, project, wt3, "厚さ", 125, reason="WT-3 を直す", reviewed_by="テスト", unit="mm")
    assert effective_value(store, project, r.element_ids["wall_N"], "厚さ").value == 125
    assert effective_value(store, project, wall, "厚さ").value == 120


def test_room_area_and_perimeter_are_computed_not_stored(tmp_path, terminal_ok):
    """B-10: 面積 is computed from the effective 線分 of the room's boundaries at output time."""
    from btruth.effective import room_area_m2, room_perimeter_m
    from btruth.review import approve_interpretation
    project, store = import_sample(tmp_path)
    r = register_fixture(store, project, "step1_fixed")
    room = r.element_ids["room_101"]
    assert room_area_m2(store, project, room) is None          # nothing approved yet
    approve_interpretation(store, project, r.interpretation_id, reason="テスト", reviewed_by="テスト")
    assert room_area_m2(store, project, room) == pytest.approx(24.00, abs=0.005)
    assert room_perimeter_m(store, project, room) == pytest.approx(20.000, abs=0.0005)
    assert count(store, "select count(*) from claim where attribute='面積'") == 0
