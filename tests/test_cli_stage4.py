"""Stage 4 through the command line: identify / diff / rechecks, and the confirmation commands approve-moves and
resolve-recheck (terminal only, listing then y/N; G-1 (b), (c)). Also the kit for a blind measurement (BRIEF §1-2)."""
from __future__ import annotations

import json
import subprocess
import sys

from conftest import ROOT, subprocess_env
from helpers import FIXTURES, STEP2, STEP2_MOVED, import_sample


def run(*args, stdin: str | None = None, terminal: bool = False):
    return subprocess.run([sys.executable, "-m", "btruth", *map(str, args)], cwd=ROOT, capture_output=True,
                          text=True, encoding="utf-8", input=stdin, env=subprocess_env(terminal))


def prepared(tmp_path):
    project, store = import_sample(tmp_path, STEP2)
    store.close()
    r = run("propose", project.folder, FIXTURES / "step2_fixed.json")
    assert r.returncode == 0, r.stderr
    interp = [line for line in r.stdout.splitlines() if "解釈の ID" in line][0].split()[-1]
    assert run("approve", project.folder, "--interpretation", interp, "--reason", "ok", stdin="y\n", terminal=True).returncode == 0
    r = run("import", project.folder, STEP2_MOVED, "--source", "平面図", "--next")
    assert r.returncode == 0, r.stderr
    return project


def test_identify_then_approve_moves_through_the_command(tmp_path):
    project = prepared(tmp_path)
    r = run("identify", project.folder, "平面図@1", "平面図@2")
    assert r.returncode == 0, r.stderr
    assert "移動 7" in r.stdout and "同定の ID" in r.stdout
    run_id = [line for line in r.stdout.splitlines() if "同定の ID" in line][0].split()[-1]
    r = run("diff", project.folder, "--run", run_id)
    assert r.returncode == 0 and "人に渡した数" in r.stdout and "500.0 mm" in r.stdout
    # no: nothing written
    r = run("approve-moves", project.folder, "--run", run_id, "--reason", "x", stdin="n\n", terminal=True)
    assert r.returncode == 0 and "記録しません" in r.stdout
    assert "提案中" in run("diff", project.folder, "--run", run_id).stdout
    # yes: the listing comes before the question, then the check after the moves runs
    r = run("approve-moves", project.folder, "--run", run_id, "--reason", "図面の変更を確かめた", stdin="y\n", terminal=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.index("移動") < r.stdout.index("確定しますか")
    assert "承認を記録しました" in r.stdout
    r = run("issues", project.folder)
    assert "名前がない空間" in r.stdout and "移動の承認待ち" not in r.stdout and "壁と境界のずれ" not in r.stdout
    r = run("diff", project.folder, "--run", run_id, "--out", tmp_path / "diff.html", "--html")
    assert r.returncode == 0 and (tmp_path / "diff.html").exists()


def test_approve_moves_refuses_outside_a_terminal(tmp_path):
    project = prepared(tmp_path)
    r = run("identify", project.folder, "平面図@1", "平面図@2")
    run_id = [line for line in r.stdout.splitlines() if "同定の ID" in line][0].split()[-1]
    r = run("approve-moves", project.folder, "--run", run_id, "--reason", "x", stdin="y\n", terminal=False)
    assert r.returncode != 0 and "端末" in r.stderr
    assert "提案中" in run("diff", project.folder, "--run", run_id).stdout


def test_rechecks_and_resolve_recheck_through_the_command(tmp_path):
    project = prepared(tmp_path)
    r = run("items", project.folder, "--kind", "壁")
    # the partition wall: the one whose centre line is at x = 2300 (Jw_cad coordinates)
    from btruth.project import ProjectFolder, open_store
    p = ProjectFolder.load(project.folder)
    with open_store(p) as store:
        wall = store.scalar("select subject_id from claim where attribute='芯線' and value_json like '%210002300%'")
    value = json.dumps([[210002300.0, 148500000.0], [210002300.0, 148504000.0]])
    assert run("decide", project.folder, "--element", wall, "--attribute", "芯線", "--value", value, "--unit", "mm",
               "--reason", "現地", stdin="y\n", terminal=True).returncode == 0
    r = run("identify", project.folder, "平面図@1", "平面図@2")
    assert "再確認の印 1" in r.stdout
    r = run("rechecks", project.folder)
    assert r.returncode == 0 and "再確認の印" in r.stdout
    mark = [line for line in r.stdout.splitlines() if line.startswith("印 ")][0].split()[1]
    r = run("resolve-recheck", project.folder, "--mark", mark, "--choice", "保つ", "--reason", "壁はそのまま", stdin="y\n",
            terminal=True)
    assert r.returncode == 0, r.stderr
    assert "開いている再確認の印はありません" in run("rechecks", project.folder).stdout


def test_new_confirmation_commands_say_they_are_terminal_only():
    for sub in ("approve-moves", "resolve-recheck"):
        r = run(sub, "--help")
        assert r.returncode == 0 and "端末" in r.stdout


# ---------------------------------------------------------------- the blind measurement kit (BRIEF §1-2, docs/MEASURE.md)
def test_measurement_kit_holds_clues_and_instructions_only(tmp_path):
    project, store = import_sample(tmp_path, STEP2)
    store.close()
    dest = tmp_path / "kit"
    r = run("kit", project.folder, "--versions", "平面図@1", "壁種表@1", "仕上表@1", "--dest", dest)
    assert r.returncode == 0, r.stderr
    names = sorted(str(p.relative_to(dest)).replace("\\", "/") for p in dest.rglob("*") if p.is_file())
    assert "TASK.md" in names
    assert ".claude/skills/read-drawing/SKILL.md" in names
    assert ".claude/hooks/guard_confirm.py" in names and ".claude/settings.json" in names
    assert any(n.startswith("clues/") and n.endswith(".json") for n in names)
    # no answers: no fixture, no expected values, no database, no btruth code
    for n in names:
        assert "fixed" not in n and "expected" not in n and not n.endswith((".sqlite", ".db")) and not n.startswith("btruth/")
    clues = json.loads(next((dest / "clues").glob("*.json")).read_text(encoding="utf-8"))
    assert clues["version"]["source_name"] in ("平面図", "壁種表", "仕上表") and clues["clues"]
    task = (dest / "TASK.md").read_text(encoding="utf-8")
    assert "proposal.json" in task and "承認" in task


def test_measure_can_mark_earlier_numbers_as_known_answers(tmp_path):
    project, store = import_sample(tmp_path, STEP2)
    store.close()
    r = run("propose", project.folder, FIXTURES / "step2_fixed.json")
    interp = [line for line in r.stdout.splitlines() if "解釈の ID" in line][0].split()[-1]
    r = run("measure", project.folder, "--interpretation", interp, "--against", interp)
    assert r.returncode == 0, r.stderr
    from btruth.project import ProjectFolder, open_store
    p = ProjectFolder.load(project.folder)
    with open_store(p) as s:
        sid = s.scalar("select id from run_summary where kind='AI の解釈の正しさの測定'")
    r = run("measure", project.folder, "--mark", sid[:8], "--note", "答えを知った状態の数字（第3段）")
    assert r.returncode == 0, r.stderr
    with open_store(p) as s:
        row = s.one("select counts_json from run_summary where kind='測定の印'")
        d = json.loads(row["counts_json"])
        assert d["marks"] == sid and d["condition"] == "答えを知った状態"


def test_the_trial_flow_for_the_person_with_the_ai_reading_only(tmp_path):
    """BRIEF_v3_step4 §4 and F-14: the database the person tries holds no fixture. The steps of docs/STEP4.md:
    the AI reading of version 1 is approved, the identity run already made, the moves approved in one batch."""
    from helpers import FINISH_SCHEDULE, WALL_TYPES
    folder = tmp_path / "try4"
    assert run("init", folder, "--name", "架空").returncode == 0
    for f, src, dt in ((STEP2, "平面図", "建築平面図"), (WALL_TYPES, "壁種表", "壁種表"), (FINISH_SCHEDULE, "仕上表", "仕上表")):
        assert run("import", folder, f, "--source", src, "--kind", "設計図", "--drawing-type", dt).returncode == 0
    r = run("propose", folder, ROOT / "samples" / "ai_run" / "step2_claude.json")
    interp = [line for line in r.stdout.splitlines() if "解釈の ID" in line][0].split()[-1]
    assert run("import", folder, STEP2_MOVED, "--source", "平面図", "--next").returncode == 0
    r = run("identify", folder, "平面図@1", "平面図@2")
    run_id = [line for line in r.stdout.splitlines() if "同定の ID" in line][0].split()[-1]
    assert "移動 7" in r.stdout
    assert "固定" not in run("items", folder).stdout
    # the moves wait for the AI reading itself
    r = run("approve-moves", folder, "--run", run_id[:8], "--reason", "x", stdin="y\n", terminal=True)
    assert r.returncode == 4 and "承認されていない" in r.stderr
    assert run("approve", folder, "--interpretation", interp[:8], "--reason", "図面と見比べた", stdin="y\n", terminal=True).returncode == 0
    r = run("approve-moves", folder, "--run", run_id[:8], "--reason", "図面の変更を確かめた", stdin="y\n", terminal=True)
    assert r.returncode == 0, r.stderr
    r = run("issues", folder)
    assert "名前がない空間" in r.stdout and "移動の承認待ち" not in r.stdout and "壁と境界のずれ" not in r.stdout
    r = run("diff", folder, "--run", run_id[:8])
    assert "[承認済み]" in r.stdout and "[提案中]" not in r.stdout
