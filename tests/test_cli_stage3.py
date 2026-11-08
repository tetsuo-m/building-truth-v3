"""The stage-3 commands through the command line: propose / items / issues / show / clues, and the
confirmation commands, which ask y/N and refuse outside a terminal (G-1 (b), (c))."""
from __future__ import annotations

import subprocess
import sys

from conftest import ROOT, subprocess_env
from helpers import FIXTURES, import_sample, STEP2


def run(*args, stdin: str | None = None, terminal: bool = False):
    return subprocess.run([sys.executable, "-m", "btruth", *map(str, args)], cwd=ROOT, capture_output=True,
                          text=True, encoding="utf-8", input=stdin, env=subprocess_env(terminal))


def prepared(tmp_path, dxf=None):
    project, store = import_sample(tmp_path, dxf) if dxf else import_sample(tmp_path)
    store.close()
    fixture = "step2_fixed" if dxf is STEP2 else "step1_fixed"
    r = run("propose", project.folder, FIXTURES / f"{fixture}.json")
    assert r.returncode == 0, r.stderr
    interp = [line for line in r.stdout.splitlines() if "解釈の ID" in line][0].split()[-1]
    return project, interp


def test_approve_asks_after_listing_and_writes_on_yes(tmp_path):
    project, interp = prepared(tmp_path)
    r = run("approve", project.folder, "--interpretation", interp, "--reason", "図面と見比べた", stdin="y\n", terminal=True)
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert out.index("空間の境界") < out.index("確定しますか")        # the listing comes before the question
    assert "承認を記録しました" in out
    r = run("items", project.folder)
    assert "承認済み" in r.stdout and "提案中" not in r.stdout


def test_approve_writes_nothing_on_no(tmp_path):
    project, interp = prepared(tmp_path)
    r = run("approve", project.folder, "--interpretation", interp, "--reason", "x", stdin="n\n", terminal=True)
    assert r.returncode == 0, r.stderr
    assert "記録しません" in r.stdout
    r = run("items", project.folder)
    assert "承認済み" not in r.stdout


def test_approve_refuses_outside_a_terminal(tmp_path):
    """F-11: on Windows, a command run by Claude Code looked like a terminal to v2. The judgement here
    requires stdin, stdout and stderr to be terminals and no AI-agent environment."""
    project, interp = prepared(tmp_path)
    r = run("approve", project.folder, "--interpretation", interp, "--reason", "x", stdin="y\n", terminal=False)
    assert r.returncode != 0
    assert "端末" in r.stderr
    r = run("items", project.folder)
    assert "承認済み" not in r.stdout


def test_decide_name_exclude_room_through_the_command(tmp_path):
    project, interp = prepared(tmp_path, STEP2)
    assert run("approve", project.folder, "--interpretation", interp, "--reason", "ok", stdin="y\n", terminal=True).returncode == 0
    r = run("issues", project.folder)
    assert "名前がない空間" in r.stdout
    block = r.stdout.split("■ 名前がない空間")[1].split("■ ")[0]
    room_id = [line for line in block.splitlines() if line.strip().startswith("対象：")][0].split("要素 ")[1].split()[0]
    r = run("name", project.folder, "--element", room_id, "--name", "倉庫", "--reason", "確認した", stdin="y\n", terminal=True)
    assert r.returncode == 0, r.stderr
    r = run("issues", project.folder)
    assert "開いている要確認はありません" in r.stdout
    r = run("exclude-room", project.folder, "--element", room_id, "--reason", "やはり PS", stdin="y\n", terminal=True)
    assert r.returncode == 0, r.stderr
    # a decision on a value, by id prefix
    r = run("items", project.folder, "--kind", "壁")
    wall_id = [line for line in r.stdout.splitlines() if "壁" in line and "要素" in line][0].split("要素 ")[1].split()[0]
    r = run("decide", project.folder, "--element", wall_id[:8], "--attribute", "厚さ", "--value", "100", "--unit", "mm",
            "--reason", "壁種表どおり", stdin="y\n", terminal=True)
    assert r.returncode == 0, r.stderr
    assert "判断を記録しました" in r.stdout


def test_show_writes_the_understanding_screen(tmp_path):
    project, interp = prepared(tmp_path, STEP2)
    out = project.folder / "out" / "show.html"
    r = run("show", project.folder, "--out", out)
    assert r.returncode == 0, r.stderr
    html = out.read_text(encoding="utf-8")
    assert html.startswith("<!DOCTYPE html>")
    assert "<svg" in html and "data-evidence" in html          # elements carry the ids of their evidence clues
    assert "名前がない空間" in html and "読み残し" in html and "はじかれた" in html


def test_clues_command_dumps_observed_clues_as_json(tmp_path):
    import json
    project, _ = prepared(tmp_path)
    r = run("clues", project.folder, "平面図@1")
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["version"]["source_name"] == "平面図" and len(data["clues"]) == 21
    assert data["clues"][0]["roles"] == ["GRID"] and data["clues"][12]["kind"] == "LINE"


def test_the_command_still_never_needs_a_database_path():
    help_text = "".join(run(sub, "--help").stdout for sub in
                        ("approve", "reject", "hold", "decide", "name", "exclude-room", "propose", "show", "measure"))
    assert "--db" not in help_text and ".sqlite" not in help_text
