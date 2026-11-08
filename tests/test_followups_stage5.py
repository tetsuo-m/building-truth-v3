"""Findings of the person's trial of stage 5 (out\\try5, 2026-11-08):

1. the opening's width (and height) has the door schedule as its primary source (C-2d, authority.csv): opening ←ふさぐ
   door →型である door type. The type's effective width is the primary claim; the drawing's width is the secondary.
   An adoption on the type carries to the opening; an adoption on the opening itself wins (E-5, 決定 9). A drawing
   that differs beyond the measuring tolerance gets a fix proposal for the drawing;
2. the opening's primary discipline follows the wall it voids (Q31);
3. a person's judgement on 主の分野 wins over the one computed from the authority table (Q29 への足し, E-3);
4. choosing an option of 決定が未反映 records the document taken as 正 in review.basis_source_version_id, and
   `values` shows the adopted value's basis document and its rank (決定 Q8).
"""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from conftest import ROOT, subprocess_env
from stage5 import check, open_of
from test_consistency import door_project


def choose(store, project, issue_id, code, reason="決めた"):
    from btruth.review import choose_option
    return choose_option(store, project, issue_id, code, reason=reason, reviewed_by="てっちゃん")


def late_issue(store, project):
    check(store, project)
    [late] = open_of(store, project, "決定が未反映")
    return late


# ---------------------------------------------------------------- 1. the opening's width follows its door type
def test_the_opening_width_comes_from_the_door_type_as_primary(tmp_path, terminal_ok):
    from btruth.effective import effective_value
    project, store, r = door_project(tmp_path)
    opening, ad1 = r.element_ids["opening_A"], r.element_ids["ad1"]
    v = effective_value(store, project, opening, "幅")
    assert v.value == 800 and v.via_type == ad1 and "主" in v.note
    late = late_issue(store, project)
    choose(store, project, late["id"], "type_width")
    v = effective_value(store, project, opening, "幅")
    assert v.value == 900 and v.status == "採用" and v.via_type == ad1
    from btruth.propose import opening_segment
    from btruth import geometry
    assert geometry.length(opening_segment(store, project, opening)) == pytest.approx(900.0)
    assert effective_value(store, project, opening, "高さ").value == 2000


def test_an_adoption_on_the_opening_wins_over_the_type(tmp_path, terminal_ok):
    from btruth.effective import effective_value
    from btruth.review import decide
    project, store, r = door_project(tmp_path)
    opening, ad1 = r.element_ids["opening_A"], r.element_ids["ad1"]
    choose(store, project, late_issue(store, project)["id"], "opening_width")
    decide(store, project, ad1, "幅", 1000, reason="型を広げる", reviewed_by="てっちゃん", unit="mm")
    v = effective_value(store, project, opening, "幅")
    assert v.value == 900 and v.status == "採用" and v.via_type is None


def test_a_drawing_that_differs_from_the_schedule_gets_a_fix_for_the_drawing(tmp_path, terminal_ok):
    project, store, r = door_project(tmp_path, schedule_rows="AD-1,片開き扉,1200,2000,木製フラッシュ\n", minutes=False, type_width=1200)
    check(store, project)
    opening = r.element_ids["opening_A"]
    diffs = [i for i in open_of(store, project, "言い分の食い違い（主と従）") if opening in i["subject_ids"]]
    assert len(diffs) == 1
    d = diffs[0]
    assert d["facts"]["属性"] == "幅" and d["facts"]["主の値"] == 1200 and d["facts"]["従の値"] == 800
    assert "平面図" in json.dumps(d["proposal"], ensure_ascii=False)


# ---------------------------------------------------------------- 2 and 3. the primary discipline
def test_the_opening_follows_its_wall_and_a_judgement_wins(tmp_path, terminal_ok):
    from btruth.consistency import primary_discipline
    from btruth.review import decide
    project, store, r = door_project(tmp_path)
    from btruth.intake import import_file  # noqa: F401
    store.insert("source_attribute", "テスト", source_id=store.scalar("select id from source where name='平面図'"),
                 attribute="分野", value="建築", origin="テスト")
    store.commit()
    wall, opening = r.element_ids["wall_A"], r.element_ids["opening_A"]
    assert primary_discipline(store, project, wall) == "建築"
    assert primary_discipline(store, project, opening) == "建築"
    decide(store, project, wall, "主の分野", "構造", reason="RC の耐力壁と分かった", reviewed_by="てっちゃん")
    assert primary_discipline(store, project, wall) == "構造"
    assert primary_discipline(store, project, opening) == "構造"


# ---------------------------------------------------------------- 4. the basis document of a choice, and how values shows it
def run(*args, stdin=None, terminal=False):
    return subprocess.run([sys.executable, "-m", "btruth", *map(str, args)], cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", input=stdin, env=subprocess_env(terminal))


def test_choose_records_the_basis_document_and_values_shows_it(tmp_path, terminal_ok):
    from btruth.review import decide
    project, store, r = door_project(tmp_path)
    ad1 = r.element_ids["ad1"]
    rid = choose(store, project, late_issue(store, project)["id"], "type_width")
    minutes_v1 = store.scalar("select v.id from source_version v join source s on s.id=v.source_id where s.name='議事録4'")
    assert store.scalar("select basis_source_version_id from review where id=?", rid) == minutes_v1
    decide(store, project, r.element_ids["wall_A"], "耐火", "1時間", reason="特記", reviewed_by="てっちゃん")
    store.close()
    out = run("values", project.folder, "--element", ad1).stdout
    assert "採用 決定  人の判断（根拠 議事録4@1、議事録、格 2）  900" in out
    out = run("values", project.folder, "--element", r.element_ids["wall_A"]).stdout
    assert "人の判断（根拠の書類なし、設計図と同格 5）" in out
    out = run("values", project.folder, "--element", r.element_ids["opening_A"]).stdout
    assert "幅: 900  [採用]" in out and "ふさぐ建具の型" in out and "建具表@1  800" in out
