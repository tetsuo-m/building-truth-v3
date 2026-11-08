"""Stage 6 through the command line, on the stage-5 samples with the AI's reading only (no fixture; BRIEF step6 §4):
approve → type_width → the drawing fix → writeback → tables → IFC, and the confirmation commands confirm-drawing
and allow-ifc (terminal only)."""
from __future__ import annotations

import csv
import subprocess
import sys

from conftest import ROOT, subprocess_env


def run(*args, stdin=None, terminal=False):
    return subprocess.run([sys.executable, "-m", "btruth", *map(str, args)], cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", input=stdin, env=subprocess_env(terminal))


def issue_id(stdout: str, kind: str, contains: str | None = None) -> str:
    for block in stdout.split("■ ")[1:]:
        if block.startswith(kind + "［") and (contains is None or contains in block):
            return [l for l in block.splitlines() if "要確認の ID：" in l][0].split("要確認の ID：")[1].strip()
    raise AssertionError(stdout)


def build(folder):
    s5, s1 = ROOT / "samples" / "step5", ROOT / "samples" / "step1"
    assert run("init", folder, "--name", "架空").returncode == 0
    for args in ((s5 / "plan.dxf", "--source", "平面図", "--kind", "設計図", "--drawing-type", "建築平面図", "--discipline", "建築"),
                 (s1 / "wall_types.csv", "--source", "壁種表", "--kind", "設計図", "--drawing-type", "壁種表", "--discipline", "建築"),
                 (s1 / "finish_schedule.csv", "--source", "仕上表", "--kind", "設計図", "--drawing-type", "仕上表", "--discipline", "建築"),
                 (s5 / "door_schedule.csv", "--source", "建具表", "--kind", "設計図", "--drawing-type", "建具表", "--discipline", "建築"),
                 (s5 / "minutes.md", "--source", "議事録4", "--kind", "議事録", "--document-date", "2026-10-15")):
        assert run("import", folder, *args).returncode == 0
    r = run("propose", folder, ROOT / "samples" / "ai_run" / "step5_claude.json")
    return [l for l in r.stdout.splitlines() if "解釈の ID" in l][0].split()[-1]


def test_the_trial_flow_of_stage6(tmp_path):
    folder = tmp_path / "try6"
    interp = build(folder)
    assert "固定" not in run("items", folder).stdout
    assert run("approve", folder, "--interpretation", interp[:8], "--reason", "見比べた", stdin="y\n", terminal=True).returncode == 0
    out = run("issues", folder).stdout
    late = issue_id(out, "決定が未反映")
    r = run("choose", folder, "--issue", late[:8], "--option", "type_width", "--reason", "議事録どおり", stdin="y\n", terminal=True)
    assert r.returncode == 0, r.stderr
    out = run("issues", folder).stdout
    fix = issue_id(out, "言い分の食い違い（主と従）", contains="図面の修正案")
    assert "型の値が人の判断で変わった" in out
    r = run("choose", folder, "--issue", fix[:8], "--option", "fix_secondary", "--reason", "図面を 900 に直す", stdin="y\n", terminal=True)
    assert r.returncode == 0, r.stderr
    # writeback from the person's original drawing (the sample) into a new file
    original = ROOT / "samples" / "step5" / "plan.dxf"
    r = run("writeback", folder, "--source", "平面図", "--original", original, "--out", folder / "out" / "plan_wb.dxf")
    assert r.returncode == 0, r.stderr
    assert "未確認" in run("writebacks", folder).stdout
    wid = [l for l in run("writebacks", folder).stdout.splitlines() if l.startswith("書き戻し ")][0].split()[1]
    r = run("confirm-drawing", folder, "--writeback", wid[:8], "--reason", "Jw_cad で確かめた", stdin="y\n", terminal=True)
    assert r.returncode == 0 and "人が CAD で確認済み" in run("writebacks", folder).stdout
    # tables and the IFC
    assert run("tables", folder).returncode == 0
    rows = list(csv.DictReader(open(folder / "out" / "tables" / "area.csv", encoding="utf-8-sig")))
    assert len(rows) == 2
    r = run("ifc", folder)
    assert r.returncode == 0, r.stderr
    assert (folder / "out" / "model.ifc").exists() and (folder / "out" / "model.map.csv").exists()


def test_allow_ifc_and_confirm_drawing_refuse_outside_a_terminal(tmp_path):
    folder = tmp_path / "t"
    build(folder)
    for sub in ("allow-ifc", "confirm-drawing"):
        assert "端末" in run(sub, "--help").stdout
    r = run("allow-ifc", folder, "--generation", "x", "--reason", "x", stdin="y\n", terminal=False)
    assert r.returncode != 0 and "端末" in r.stderr
