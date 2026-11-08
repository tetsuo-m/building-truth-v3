"""Stage 6 §1: the human decisions and the fixes found in the person's trial of stage 5 (out\\try5b), and the three
things left from stage 5.

  * a type value changed by a judgement → a drawing fix for the openings that use the type, whatever the tolerance;
  * the confirmation question throws away what was typed before it (pasted lines must not answer y/N);
  * `issues` speaks plain sentences: what differs, what can be chosen, the command to type (with the issue's id);
    JSON only with --detail. `items` shows the item id first (the one `approve --item` takes);
  * 例4: the wall type's layers hold the insulation the drawing shows (or an issue);
  * 例2: a column's offset from its grid crossing within column_offset_max_mm is normal (D-8), beyond is an issue;
  * B-13: rooms of two sources are matched by their room number.
"""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from conftest import ROOT, subprocess_env
from helpers import STOREY, claim, element, ev, make_project, proposal, relation, seg, step2_like_dxf
from stage5 import approve, check, imp, open_kinds, open_of, register, wall_type_project, wall_type_reading, write_text
from test_consistency import door_project, materials_project


def choose(store, project, issue_id, code, reason="決めた"):
    from btruth.review import choose_option
    return choose_option(store, project, issue_id, code, reason=reason, reviewed_by="てっちゃん")


def run(*args, stdin=None, terminal=False):
    return subprocess.run([sys.executable, "-m", "btruth", *map(str, args)], cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", input=stdin, env=subprocess_env(terminal))


# ---------------------------------------------------------------- a type value changed by a judgement → drawing fix
def test_a_judged_type_width_gives_a_drawing_fix_whatever_the_tolerance(tmp_path, terminal_ok):
    project, store, r = door_project(tmp_path)
    check(store, project)
    [late] = open_of(store, project, "決定が未反映")
    choose(store, project, late["id"], "type_width")          # 800 → 900: within door_width_tol_mm (100)
    check(store, project)
    opening = r.element_ids["opening_A"]
    fixes = [i for i in open_of(store, project, "言い分の食い違い（主と従）") if opening in i["subject_ids"]]
    assert len(fixes) == 1
    fix = fixes[0]["proposal"]
    assert fix["kind"] == "図面の修正案"
    df = fix["drawing_fix"]
    assert df["element"] == opening and df["attribute"] == "幅" and df["value"] == 900 and df["was"] == 800
    assert df["clue_ids"] and df["source_version_id"]
    assert "判断" in fixes[0]["facts"]["理由"]
    # the tolerance in rules.csv is unchanged
    assert "door_width_tol_mm,100," in (project.folder / "rules" / "rules.csv").read_text(encoding="utf-8-sig")


# ---------------------------------------------------------------- the question throws away type-ahead
def test_the_confirmation_flushes_pending_input_before_asking(monkeypatch):
    from btruth import review
    calls = []
    monkeypatch.setattr(review, "flush_pending_input", lambda: calls.append("flush"))
    monkeypatch.setattr("builtins.input", lambda prompt="": calls.append("input") or "y")
    assert review.prompt_confirm("一覧") is True
    assert calls == ["flush", "input"]


def test_flushing_does_nothing_when_stdin_is_not_a_terminal(monkeypatch):
    import io
    from btruth import review
    monkeypatch.setattr(sys, "stdin", io.StringIO("y\nnext line\n"))
    review.flush_pending_input()                       # a pipe (the tests) keeps its content
    assert sys.stdin.read() == "y\nnext line\n"


# ---------------------------------------------------------------- readable issues and items
def test_issues_are_plain_sentences_with_the_command_to_type(tmp_path):
    project, store = wall_type_project(tmp_path)
    p = wall_type_reading(store)
    store.close()
    path = tmp_path / "p.json"
    path.write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
    interp = [l for l in run("propose", project.folder, path).stdout.splitlines() if "解釈の ID" in l][0].split()[-1]
    assert run("approve", project.folder, "--interpretation", interp, "--reason", "ok", stdin="y\n", terminal=True).returncode == 0
    out = run("issues", project.folder).stdout
    block = out.split("■ 決定が未反映")[1].split("■ ")[0]
    assert "要確認の ID：" in block and "選べること" in block and "打つ例：" in block
    assert "議事録3" in block and "壁種表" in block and "格 2" in block and "格 5" in block
    assert "btruth choose" in block and "--option adopt_higher" in block
    assert "{\"" not in out                              # no JSON by default
    detail = run("issues", project.folder, "--detail").stdout
    assert "{\"" in detail or "{'" in detail or "\"属性\"" in detail


def test_items_show_the_item_id_to_type(tmp_path):
    project, store = wall_type_project(tmp_path)
    p = wall_type_reading(store)
    store.close()
    path = tmp_path / "p.json"
    path.write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
    run("propose", project.folder, path)
    out = run("items", project.folder).stdout
    line = next(l for l in out.splitlines() if "壁種" in l and "item " in l)
    item = line.split("item ")[1].split()[0]
    from btruth.project import ProjectFolder, open_store
    with open_store(ProjectFolder.load(project.folder)) as s:
        assert s.scalar("select count(*) from interpretation_item where id like ?", item + "%") == 1
    assert "要素 " in line                                # the element as reference


# ---------------------------------------------------------------- 例4: the wall type's layers and the insulation
def test_insulation_on_the_drawing_must_be_a_layer_of_the_wall_type(tmp_path, terminal_ok):
    project, store, r = materials_project(tmp_path)
    w7 = r.element_ids["w7"]
    m = register(store, project, proposal([], claims=[dict(claim("断熱材", "グラスウール 50", [ev("平面図@1#24")]), subject={"id": w7})],
                                          sources=["平面図@1"]))
    approve(store, project, m.interpretation_id)
    check(store, project)
    [diff] = [i for i in open_of(store, project, "言い分の食い違い（主と従）") if i["facts"].get("属性") == "断熱材"]
    assert w7 in diff["subject_ids"] and "壁種表" in diff["facts"]["基準"]


# ---------------------------------------------------------------- 例2: the column's offset from its grid crossing
def column_project(tmp_path, y):
    from test_sources import column_plan
    project, store = make_project(tmp_path)
    imp(store, project, column_plan(tmp_path / "arch.dxf", y=y), "建築平面図", "設計図", "建築平面図", discipline="建築")
    grids = [element("X1", "通り芯", [claim("符号", "X1"), claim("線分", seg((0, -1500), (0, 5500)), [], "mm")]),
             element("Y1", "通り芯", [claim("符号", "Y1"), claim("線分", seg((-1500, 0), (7500, 0)), [], "mm")])]
    col = element("c1", "柱", [claim("符号", "C1"), claim("位置", [0.0, float(y)], [], "mm")])
    r = register(store, project, proposal(grids + [col], [relation("x", "載る", "c1", "X1"), relation("y", "載る", "c1", "Y1"),
                                                          relation("in", "含む", "c1", STOREY)], sources=["建築平面図@1"]))
    approve(store, project, r.interpretation_id)
    check(store, project)
    return project, store, r


def test_a_column_offset_within_the_limit_is_normal(tmp_path, terminal_ok):
    project, store, r = column_project(tmp_path, 50)
    assert "柱の偏心が上限を超える" not in open_kinds(store, project)


def test_a_column_offset_beyond_the_limit_is_an_issue(tmp_path, terminal_ok):
    project, store, r = column_project(tmp_path, 600)
    [i] = open_of(store, project, "柱の偏心が上限を超える")
    assert i["facts"]["偏心_mm"] == pytest.approx(600.0) and i["facts"]["上限_mm"] == 500.0


# ---------------------------------------------------------------- B-13: rooms matched by their room number
def test_rooms_of_two_sources_are_matched_by_room_number(tmp_path, terminal_ok):
    from btruth.identity import identify_sources
    from btruth.effective import element_status
    project, store = make_project(tmp_path)
    imp(store, project, step2_like_dxf(tmp_path / "a.dxf"), "平面図", "設計図", "建築平面図")
    imp(store, project, write_text(tmp_path / "rooms.csv", "room_no,room_name,area\n101,事務室,14.80\n"), "面積表", "設計図", "求積表")
    a = register(store, project, proposal([element("r101", "部屋", [claim("室番号", "101", [ev("平面図@1#21")]),
                                                                  claim("室名", "事務室", [ev("平面図@1#21")])], [ev("平面図@1#21")])],
                                          [relation("in", "集める", "r101", STOREY)], sources=["平面図@1"]))
    approve(store, project, a.interpretation_id)
    b = register(store, project, proposal([element("t101", "部屋", [claim("室番号", "101", [ev("面積表@1#1")]),
                                                                  claim("天井高", 2700, [ev("面積表@1#1")], "mm")], [ev("面積表@1#1")])],
                                          [relation("in", "集める", "t101", STOREY)], sources=["面積表@1"]))
    res = identify_sources(store, project, b.interpretation_id, recorded_by="テスト")
    link = store.one("select element_id, verdict from identity_link where run_id=?", res.run_id)
    assert link["verdict"] == "一致" and link["element_id"] == a.element_ids["r101"]
    assert element_status(store, b.element_ids["t101"]) == "同じ要素に統合"
