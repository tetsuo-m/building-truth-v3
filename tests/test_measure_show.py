"""Measuring the AI's reading against the fixed interpretation (3-5-1 (2), D-9) and the understanding
screen (B-4): the numbers land in run_summary; the screen links every element to its evidence clues."""

from __future__ import annotations

import json

from helpers import (STOREY, claim, count, element, ev, import_sample, proposal, register_fixture, relation, seg)


def test_measure_writes_run_summary_with_matches_and_handovers(tmp_path):
    from btruth.measure import measure
    from btruth.propose import register_proposal
    project, store = import_sample(tmp_path)
    fixed = register_fixture(store, project, "step1_fixed")
    # an "AI" reading that found the grid, the room and three of the four walls, plus one wrong wall
    ai_elements = [
        element("X1", "通り芯", [claim("符号", "X1", [ev("平面図@1#3")]), claim("線分", seg((0, -1500), (0, 5500)), [ev("平面図@1#1")], "mm")],
                [ev("平面図@1#1"), ev("平面図@1#3")]),
        element("wall_S", "壁", [claim("芯線", seg((0, 0), (6000, 0)), [ev("平面図@1#14")], "mm")], [ev("平面図@1#14")]),
        element("wall_E", "壁", [claim("芯線", seg((6000, 0), (6000, 4000)), [ev("平面図@1#16")], "mm")], [ev("平面図@1#16")]),
        element("wall_N", "壁", [claim("芯線", seg((6000, 4000), (0, 4000)), [ev("平面図@1#18")], "mm")], [ev("平面図@1#18")]),
        element("wall_wrong", "壁", [claim("芯線", seg((0, -1500), (0, 5500)), [ev("平面図@1#1")], "mm")], [ev("平面図@1#1")]),
    ]
    ai_rels = [relation(f"c{i}", "含む", e["ref"], STOREY) for i, e in enumerate(ai_elements) if e["kind"] == "壁"]
    ai = register_proposal(store, project, proposal(ai_elements, ai_rels, agent_name="Claude Code"), recorded_by="テスト")
    result = measure(store, project, ai.interpretation_id, fixed.interpretation_id, recorded_by="テスト")
    assert result["elements"]["fixed"] == 18 and result["elements"]["ai"] == 5
    assert result["elements"]["matched"] == 4                     # X1 + three walls
    assert result["elements"]["extra"] == 1 and result["elements"]["missing"] == 14
    assert result["by_kind"]["壁"] == {"fixed": 4, "ai": 4, "matched": 3}
    assert result["handed_to_person"]["issues"] >= 1              # the wrong wall has no boundary partner
    assert result["handed_to_person"]["rejected_items"] == 0
    row = store.one("select kind, counts_json from run_summary where kind='AI の解釈の正しさの測定'")
    assert row is not None and json.loads(row["counts_json"])["elements"]["matched"] == 4
    assert "pass" not in json.dumps(result)                        # no pass / fail line is drawn (D-9)


def test_show_marks_elements_with_their_evidence_and_lists_rejected(tmp_path):
    from btruth.propose import register_proposal
    from btruth.show import build_show, render_show, write_show
    project, store = import_sample(tmp_path)
    r = register_fixture(store, project, "step1_fixed")
    bad = register_proposal(store, project, proposal([element("bad", "壁", [], [ev("平面図@1#999")])]), recorded_by="テスト")
    data = build_show(store, project)
    walls = [e for e in data["elements"] if e["kind"] == "壁" and e["status"] == "提案中"]
    assert len(walls) == 4 and all(len(w["evidence"]) >= 1 for w in walls)
    assert any(e["status"] == "はじかれた" for e in data["elements"])
    html = render_show(data)
    assert "data-evidence" in html and "<svg" in html
    assert "はじかれた" in html and "読み残し" in html
    out = write_show(store, project, project.folder / "out" / "show.html", recorded_by="テスト")
    assert out.exists()
    assert store.one("select kind from generation where path=?", str(out))["kind"] == "理解の確認の画面"
