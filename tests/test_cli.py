"""The btruth command: init / import / report / compare take the project folder only (G-1 (a))."""
from __future__ import annotations

import subprocess
import sys

from conftest import ROOT
from helpers import STEP1, STEP1_JW


def run(*args, cwd=ROOT):
    return subprocess.run([sys.executable, "-m", "btruth", *map(str, args)], cwd=cwd, capture_output=True,
                          text=True, encoding="utf-8")


def test_init_import_report_compare_through_the_command(tmp_path):
    folder = tmp_path / "proj"
    r = run("init", folder, "--name", "架空の物件")
    assert r.returncode == 0, r.stderr
    assert (folder / "settings" / "project.csv").exists()
    r = run("import", folder, STEP1, "--source", "平面図", "--kind", "設計図", "--drawing-type", "建築平面図")
    assert r.returncode == 0, r.stderr
    assert "step1.dxf" in r.stdout
    r = run("import", folder, STEP1, "--source", "平面図")
    assert r.returncode == 0 and "同じ中身" in r.stdout
    r = run("import", folder, STEP1_JW, "--source", "平面図", "--next")
    assert r.returncode == 0, r.stderr
    assert "次の版" in r.stdout
    r = run("import", folder, STEP1_JW, "--source", "別の図面", "--next")
    assert r.returncode != 0 and "ありません" in r.stderr
    r = run("import", folder, STEP1, "--source", "平面図", "--new")
    assert r.returncode != 0 and "すでにあります" in r.stderr
    r = run("versions", folder)
    assert r.returncode == 0 and "平面図@1" in r.stdout and "平面図@2" in r.stdout
    r = run("compare", folder, "平面図@1", "平面図@2")
    assert r.returncode == 0, r.stderr
    assert "一致 21" in r.stdout and "追加の候補 0" in r.stdout and "前の版だけ 0" in r.stdout
    out = folder / "out" / "report.html"
    r = run("report", folder, "--out", out, "--html")
    assert r.returncode == 0, r.stderr
    assert out.exists()
    r = run("report", folder)
    assert r.returncode == 0 and "読み残し" in r.stdout


def test_the_command_never_needs_a_database_path(tmp_path):
    """The hook of G-1 (a) stops commands that mention *.sqlite / *.db; btruth must not need them."""
    folder = tmp_path / "proj"
    assert run("init", folder, "--name", "x").returncode == 0
    help_text = run("import", "--help").stdout + run("report", "--help").stdout + run("init", "--help").stdout
    assert "--db" not in help_text and ".sqlite" not in help_text


def test_the_confirmation_subcommands_exist_and_say_they_are_terminal_only():
    """Stage 3 (BRIEF step3 §3-3): approve / reject / decide / hold / name / exclude-room exist; their help
    says that they run from a terminal only and ask y/N (G-1 (c))."""
    r = run("--help")
    for word in ("approve", "decide", "reject", "hold", "name", "exclude-room"):
        assert word in r.stdout
    assert "端末" in run("approve", "--help").stdout
