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
    lines = stdout.splitlines()
    i = next(n for n, l in enumerate(lines) if l.startswith(kind + " "))
    return lines[i + 1].split("要確認 ")[1].split()[0]


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
    assert "決定が未反映 " not in run("issues", project.folder).stdout
    # the check can be run at any time; the answered issue is not raised again
    r = run("check", project.folder)
    assert r.returncode == 0, r.stderr
    assert "決定が未反映 " not in run("issues", project.folder).stdout


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


def test_choose_refuses_outside_a_terminal(tmp_path):
    project, interp = prepared(tmp_path)
    assert run("approve", project.folder, "--interpretation", interp, "--reason", "ok", stdin="y\n", terminal=True).returncode == 0
    iid = issue_line(run("issues", project.folder).stdout, "決定が未反映")
    r = run("choose", project.folder, "--issue", iid, "--option", "adopt_higher", "--reason", "x", stdin="y\n", terminal=False)
    assert r.returncode != 0 and "端末" in r.stderr
    assert "決定が未反映" in run("issues", project.folder).stdout
    assert "端末" in run("choose", "--help").stdout
