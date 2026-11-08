"""Registering a proposal (design E-2, E-3; BRIEF step3 §3-1): ids are given, the rule checks run,
rejected items stay in the vessel, a wall without a boundary partner is not rejected (C-2e)."""
from __future__ import annotations

import json

import pytest

from helpers import (OUTSIDE, STOREY, claim, count, element, ev, fixture, import_sample, one_room_dxf,
                     proposal, rect_room, register_fixture, relation, seg, STEP2)


def test_fixed_step1_proposal_is_registered_with_ids_and_rule_checks(tmp_path):
    project, store = import_sample(tmp_path)
    r = register_fixture(store, project, "step1_fixed")
    assert r.interpretation_id and r.agent_id
    # every element / relation / claim / assumption of the proposal has a row and an item
    assert count(store, "select count(*) from element where created_by_interpretation_id=?", r.interpretation_id) == 18
    assert count(store, "select count(*) from relation where created_by_interpretation_id=?", r.interpretation_id) == 29
    assert count(store, "select count(*) from assumption where created_by_interpretation_id=?", r.interpretation_id) == 1
    items = store.all("select kind, rule_check_status from interpretation_item where interpretation_id=?", r.interpretation_id)
    assert len(items) == 18 + 29 + 1
    assert {i["rule_check_status"] for i in items} == {"通った"}
    assert r.rejected == 0 and r.passed == 48
    # kinds and names are claims, never columns (E-6); every claim is an observation (D-1)
    modes = {m[0] for m in store.all("select distinct mode from claim where interpretation_id=?", r.interpretation_id)}
    assert modes == {"観測"}
    kinds = [json.loads(v[0]) for v in store.all(
        "select value_json from claim where interpretation_id=? and attribute='種類'", r.interpretation_id)]
    assert kinds.count("空間の境界") == 8 and kinds.count("壁") == 4 and kinds.count("部屋") == 1 and kinds.count("通り芯") == 4
    # evidence points at the clues (B-3); every rule check is recorded (E-3)
    assert count(store, "select count(*) from interpretation_evidence e join interpretation_item i on i.id=e.item_id "
                        "where i.interpretation_id=?", r.interpretation_id) > 40
    assert count(store, "select count(*) from rule_check") > 0
    # the agent is recorded (D-6)
    agent = store.one("select name, kind from agent where id=?", r.agent_id)
    assert agent["name"] == "固定の解釈（テスト）"
    # the interpretation names the versions it read (E-2)
    versions = json.loads(store.one("select source_version_ids_json from interpretation where id=?", r.interpretation_id)[0])
    assert len(versions) == 3


def test_fixed_step2_proposal_counts(tmp_path):
    project, store = import_sample(tmp_path, STEP2)
    r = register_fixture(store, project, "step2_fixed")
    assert r.rejected == 0
    kinds = [json.loads(v[0]) for v in store.all(
        "select value_json from claim where interpretation_id=? and attribute='種類'", r.interpretation_id)]
    assert kinds.count("部屋") == 2 and kinds.count("壁") == 5 and kinds.count("空間の境界") == 12


def test_unresolved_reference_is_rejected_but_kept(tmp_path):
    """E-3: 参照した要素・手掛かりが存在する. The rejected proposal stays (v2 Q52), with its reason."""
    project, store = import_sample(tmp_path)
    p = proposal([element("w", "壁", [claim("芯線", seg((0, 0), (6000, 0)), [ev("平面図@1#14")], "mm")],
                          [ev("平面図@1#14")]),
                  element("bad", "壁", [], [ev("平面図@1#999")])],
                 [relation("r", "含む", "w", STOREY), relation("r2", "含む", "bad", STOREY)])
    from btruth.propose import register_proposal
    r = register_proposal(store, project, p, recorded_by="テスト")
    status = {row["reason"]: row["rule_check_status"] for row in store.all(
        "select i.rule_check_status, i.reason from interpretation_item i where i.interpretation_id=? and i.kind='要素を作る'",
        r.interpretation_id)}
    assert r.rejected >= 2        # the element and the relation that points at it
    rejected = store.all("select kind, rule_check_reason from interpretation_item where interpretation_id=? "
                         "and rule_check_status='はじかれた'", r.interpretation_id)
    assert any("999" in (row["rule_check_reason"] or "") or "手掛かり" in (row["rule_check_reason"] or "") for row in rejected)
    # the element row of the rejected proposal exists (E-2: はじかれた提案も残す)
    assert count(store, "select count(*) from element where created_by_interpretation_id=?", r.interpretation_id) == 2
    assert count(store, "select count(*) from rule_check where result='はじかれた'") >= 1


def test_second_containment_and_second_voiding_are_rejected(tmp_path):
    """決定 10 / 11: 含む is one per element, くり抜く one per opening."""
    project, store = import_sample(tmp_path)
    storey2 = element("storey2", "階", [claim("名前", "2階")])
    p = proposal([element("w", "壁", [claim("芯線", seg((0, 0), (6000, 0)), [ev("平面図@1#14")], "mm")], [ev("平面図@1#14")]),
                  element("w2", "壁", [claim("芯線", seg((0, 4000), (6000, 4000)), [ev("平面図@1#18")], "mm")], [ev("平面図@1#18")]),
                  element("op", "開口", [claim("位置", 1000, [ev("平面図#14".replace("#", "@1#"))], "mm"),
                                       claim("幅", 800, [], "mm")], [ev("平面図@1#14")]),
                  storey2],
                 [relation("c1", "含む", "w", STOREY), relation("c2", "含む", "w", "storey2"),
                  relation("v1", "くり抜く", "op", "w", {"位置": 1000}), relation("v2", "くり抜く", "op", "w2", {"位置": 1000})])
    from btruth.propose import register_proposal
    r = register_proposal(store, project, p, recorded_by="テスト")
    by_ref = {row["reason"]: row for row in store.all(
        "select rule_check_status, rule_check_reason, reason from interpretation_item where interpretation_id=? and kind='つながりを作る'",
        r.interpretation_id)}
    statuses = [(row["rule_check_status"], row["rule_check_reason"]) for row in store.all(
        "select rule_check_status, rule_check_reason from interpretation_item where interpretation_id=? and kind='つながりを作る' order by rowid",
        r.interpretation_id)]
    assert [s for s, _ in statuses] == ["通った", "はじかれた", "通った", "はじかれた"]
    assert "含む" in statuses[1][1] and "くり抜く" in statuses[3][1]
    assert count(store, "select count(*) from relation where created_by_interpretation_id=?", r.interpretation_id) == 4


def test_a_wall_without_a_boundary_partner_is_not_rejected_but_an_issue(tmp_path):
    """C-2e / 決定 2 (2026-11-08): 腰壁・袖壁・塀 may be real walls; hand them to the person."""
    project, store = import_sample(tmp_path)
    p = proposal([element("fence", "壁", [claim("芯線", seg((7000, -3000), (7000, 9000)), [ev("平面図@1#4")], "mm")],
                          [ev("平面図@1#4")])],
                 [relation("c", "含む", "fence", STOREY)])
    from btruth.propose import register_proposal
    r = register_proposal(store, project, p, recorded_by="テスト")
    assert r.rejected == 0
    issues = store.all("select kind, severity, subject_ids_json from issue where check_run_id=?", r.check_run_id)
    kinds = [i["kind"] for i in issues]
    assert "境界の相手がない壁" in kinds
    issue = [i for i in issues if i["kind"] == "境界の相手がない壁"][0]
    assert issue["severity"] == "要確認"
    assert r.element_ids["fence"] in json.loads(issue["subject_ids_json"])


def test_unnamed_room_becomes_an_issue_with_two_options(tmp_path):
    """B-12 / decision Q42: a closed space without a name is an element; the person names it or excludes it."""
    project, store = import_sample(tmp_path, STEP2)
    r = register_fixture(store, project, "step2_fixed")
    issues = store.all("select id, kind, subject_ids_json from issue where check_run_id=? and kind='名前がない空間'", r.check_run_id)
    assert len(issues) == 1
    assert json.loads(issues[0]["subject_ids_json"]) == [r.element_ids["room_left"]]
    options = {o[0] for o in store.all("select label from issue_option where issue_id=?", issues[0]["id"])}
    assert options == {"名前を付ける", "部屋として扱わない"}
    # the right room is named; no issue for it, and nothing was invented for the left room (no 天井高)
    assert count(store, "select count(*) from claim where subject_id=? and attribute='天井高'", r.element_ids["room_left"]) == 0


def test_unreadable_clues_are_recorded_as_items(tmp_path):
    """E-2: kind=読めない — the agent says which clues it could not explain (B-3)."""
    project, store = import_sample(tmp_path)
    p = proposal([element("x1", "通り芯", [claim("符号", "X1", [ev("平面図@1#3")])], [ev("平面図@1#1"), ev("平面図@1#3")])],
                 unreadable=[{"clue": "平面図@1#2", "reason": "通り芯の符号を囲む丸。要素にしなかった"}])
    from btruth.propose import register_proposal
    r = register_proposal(store, project, p, recorded_by="テスト")
    row = store.one("select id, reason from interpretation_item where interpretation_id=? and kind='読めない'", r.interpretation_id)
    assert row and "丸" in row["reason"]
    assert count(store, "select count(*) from interpretation_evidence where item_id=? and role='読めない'", row["id"]) == 1
    # a clue marked 読めない still counts as not read in the report (B-3)
    from btruth.report import build_report
    ver = build_report(store, project)["versions"]
    plan = [v for v in ver if v["source_name"] == "平面図"][0]
    unread_ids = {c["seq"] for c in plan["clues"] if c["unread"]}
    assert 2 in unread_ids and 1 not in unread_ids and 3 not in unread_ids


def test_unknown_kind_is_not_rejected_but_an_issue(tmp_path):
    """J-5: a name missing from the CSV lists is 要確認「知らない名前」, not a rejection (E-1)."""
    project, store = import_sample(tmp_path)
    p = proposal([element("x", "庇", [claim("名前", "玄関庇", [ev("平面図@1#1")])], [ev("平面図@1#1")])])
    from btruth.propose import register_proposal
    r = register_proposal(store, project, p, recorded_by="テスト")
    assert r.rejected == 0
    assert count(store, "select count(*) from issue where check_run_id=? and kind='知らない名前'", r.check_run_id) == 1


def test_recreating_an_approved_element_with_the_same_evidence_is_rejected(tmp_path, terminal_ok):
    """例6 / B-5: the AI read the same drawing twice; the second element with exactly the same evidence
    is rejected so the id and the decisions attached to the first do not waver."""
    project, store = import_sample(tmp_path)
    r1 = register_fixture(store, project, "step1_fixed")
    from btruth.review import approve_interpretation
    approve_interpretation(store, project, r1.interpretation_id, reason="テスト", reviewed_by="テスト")
    again = proposal([element("wall_S_again", "壁",
                              [claim("芯線", seg((0, 0), (5999.6, 0)), [ev("平面図@1#14")], "mm")],
                              [ev("平面図@1#14", "主の根拠"), ev("平面図@1#13", "補助")])],
                     [relation("c", "含む", "wall_S_again", STOREY)])
    from btruth.propose import register_proposal
    r2 = register_proposal(store, project, again, recorded_by="テスト")
    item = store.one("select rule_check_status, rule_check_reason from interpretation_item where interpretation_id=? and kind='要素を作る'",
                     r2.interpretation_id)
    assert item["rule_check_status"] == "はじかれた" and "作り直" in item["rule_check_reason"]
    # the rejected element row remains, and the approved wall is untouched
    assert count(store, "select count(*) from element where created_by_interpretation_id=?", r2.interpretation_id) == 1
    assert count(store, "select count(*) from element where id=?", r1.element_ids["wall_S"]) == 1


def test_a_proposal_for_the_same_source_twice_before_approval_is_not_a_duplicate(tmp_path):
    """Only *approved* elements protect against re-creation (例6); two pending readings may coexist."""
    project, store = import_sample(tmp_path)
    r1 = register_fixture(store, project, "step1_fixed")
    r2 = register_fixture(store, project, "step1_fixed")
    assert r1.rejected == 0 and r2.rejected == 0


def test_proposal_from_the_command_line(tmp_path):
    import subprocess, sys
    from conftest import ROOT
    from helpers import FIXTURES
    project, store = import_sample(tmp_path)
    store.close()
    r = subprocess.run([sys.executable, "-m", "btruth", "propose", str(project.folder), str(FIXTURES / "step1_fixed.json")],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    assert "登録" in r.stdout and "はじかれた 0" in r.stdout
    r = subprocess.run([sys.executable, "-m", "btruth", "items", str(project.folder)],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    assert "提案中" in r.stdout and "空間の境界" in r.stdout
