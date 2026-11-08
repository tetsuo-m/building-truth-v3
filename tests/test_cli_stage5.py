"""Stage 5 through the command line: check, the check after an approval (also one item at a time), identify-sources,
and the confirmation command choose (terminal only, listing then y/N; G-1 (b), (c))."""
from __future__ import annotations

import json
import subprocess
import sys

from conftest import ROOT, subprocess_env
from stage5 import wall_type_project, wall_type_reading


def run(*args, stdin: str | None = None, terminal: bool = False):
    return subprocess.run([sys.executable, "-m", "btruth", *map(str, args)], cwd=ROOT, capture_output=True,
                          text=True, encoding="utf-8", input=stdin, env=subprocess_env(terminal))


def prepared(tmp_path):
    project, store = wall_type_project(tmp_path)
    p = wall_type_reading(store)
    store.close()
    path = tmp_path / "reading.json"
    path.write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
    r = run("propose", project.folder, path)
    assert r.returncode == 0, r.stderr
    interp = [line for line in r.stdout.splitlines() if "解釈の ID" in line][0].split()[-1]
    return project, interp


def issue_line(stdout: str, kind: str) -> str:
    """The issue's id from the block of `btruth issues` that starts with ■ <kind>［ (第6段の表示)."""
    block = stdout.split(f"■ {kind}［")[1].split("■ ")[0]
    return [l for l in block.splitlines() if "要確認の ID：" in l][0].split("要確認の ID：")[1].strip()


def test_the_check_runs_after_approval_and_choose_applies_an_option(tmp_path):
    project, interp = prepared(tmp_path)
    r = run("approve", project.folder, "--interpretation", interp, "--reason", "見比べた", stdin="y\n", terminal=True)
    assert r.returncode == 0, r.stderr
    assert "承認の後の照らし" in r.stdout
    r = run("issues", project.folder)
    assert "決定が未反映" in r.stdout and "設計図と施工図の食い違い" in r.stdout
    assert "［adopt_higher］" in r.stdout and "修正案" in r.stdout
    iid = issue_line(r.stdout, "決定が未反映")
    # no: nothing written
    r = run("choose", project.folder, "--issue", iid, "--option", "adopt_higher", "--reason", "x", stdin="n\n", terminal=True)
    assert r.returncode == 0 and "記録しません" in r.stdout
    assert "決定が未反映" in run("issues", project.folder).stdout
    r = run("choose", project.folder, "--issue", iid, "--option", "adopt_higher", "--reason", "議事録どおり", stdin="y\n", terminal=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.index("採用を書く") < r.stdout.index("確定しますか")
    assert "■ 決定が未反映［" not in run("issues", project.folder).stdout
    # the check can be run at any time; the answered issue is not raised again
    r = run("check", project.folder)
    assert r.returncode == 0, r.stderr
    assert "■ 決定が未反映［" not in run("issues", project.folder).stdout


def test_one_item_approval_also_runs_the_check(tmp_path):
    project, interp = prepared(tmp_path)
    r = run("items", project.folder, "--interpretation", interp)
    items = [l.split("要素 ")[1].split()[0] for l in r.stdout.splitlines() if "壁種" in l and "要素 " in l]
    from btruth.project import ProjectFolder, open_store
    with open_store(ProjectFolder.load(project.folder)) as store:
        item_ids = [store.scalar("select id from interpretation_item where element_id=? and kind='要素を作る'", e) for e in items]
    r = run("approve", project.folder, "--item", item_ids[0], "--reason", "一つ", stdin="y\n", terminal=True)
    assert r.returncode == 0, r.stderr
    assert "承認の後の照らし" in r.stdout


def test_the_trial_flow_for_the_person_with_the_ai_reading_of_step5(tmp_path):
    """BRIEF_v3_step5 §4: the database the person tries holds the AI's reading only (no fixture)."""
    folder = tmp_path / "try5"
    s5 = ROOT / "samples" / "step5"
    s1 = ROOT / "samples" / "step1"
    assert run("init", folder, "--name", "架空").returncode == 0
    for args in ((s5 / "plan.dxf", "--source", "平面図", "--kind", "設計図", "--drawing-type", "建築平面図"),
                 (s1 / "wall_types.csv", "--source", "壁種表", "--kind", "設計図", "--drawing-type", "壁種表"),
                 (s1 / "finish_schedule.csv", "--source", "仕上表", "--kind", "設計図", "--drawing-type", "仕上表"),
                 (s5 / "door_schedule.csv", "--source", "建具表", "--kind", "設計図", "--drawing-type", "建具表"),
                 (s5 / "minutes.md", "--source", "議事録4", "--kind", "議事録", "--document-date", "2026-10-15")):
        assert run("import", folder, *args).returncode == 0
    r = run("propose", folder, ROOT / "samples" / "ai_run" / "step5_claude.json")
    assert "はじかれた 0" in r.stdout and "知らない名前" not in r.stdout
    interp = [line for line in r.stdout.splitlines() if "解釈の ID" in line][0].split()[-1]
    assert "固定" not in run("items", folder).stdout
    assert run("approve", folder, "--interpretation", interp[:8], "--reason", "図面と見比べた", stdin="y\n", terminal=True).returncode == 0
    assert run("show", folder).returncode == 0          # the screens run on tables, minutes and the new issue kinds
    assert run("report", folder).returncode == 0
    out = run("issues", folder).stdout
    kinds = sorted(l[2:].split("［")[0] for l in out.splitlines() if l.startswith("■ "))
    assert kinds == ["名前がない空間", "決定が未反映", "議事録の未決"], out
    for code in ("type_width", "door_width", "opening_width", "keep_lower"):
        assert f"［{code}］" in out
    iid = issue_line(out, "決定が未反映")
    from btruth.project import ProjectFolder, open_store
    with open_store(ProjectFolder.load(folder)) as store:
        opening = store.scalar("select subject_id from claim where attribute='種類' and value_json='\"開口\"'")
        door_type = store.scalar("select subject_id from claim where attribute='種類' and value_json='\"建具の型\"'")
    assert run("choose", folder, "--issue", iid[:8], "--option", "opening_width", "--reason", "開口だけ 900", stdin="y\n",
               terminal=True).returncode == 0
    r = run("values", folder, "--element", opening[:8])
    assert "幅: 900  [採用]" in r.stdout and "210002300" not in r.stdout
    r = run("values", folder, "--element", door_type[:8])
    assert "幅: 800  [承認済みの観測]" in r.stdout and "観測 決定  議事録4@1  900" in r.stdout
    assert "■ 決定が未反映［" not in run("issues", folder).stdout


def test_choose_refuses_outside_a_terminal(tmp_path):
    project, interp = prepared(tmp_path)
    assert run("approve", project.folder, "--interpretation", interp, "--reason", "ok", stdin="y\n", terminal=True).returncode == 0
    iid = issue_line(run("issues", project.folder).stdout, "決定が未反映")
    r = run("choose", project.folder, "--issue", iid, "--option", "adopt_higher", "--reason", "x", stdin="y\n", terminal=False)
    assert r.returncode != 0 and "端末" in r.stderr
    assert "決定が未反映" in run("issues", project.folder).stdout
    assert "端末" in run("choose", "--help").stdout
