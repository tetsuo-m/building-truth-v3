"""The IFC of the person's trial flow, checked with IfcOpenShell (F-15, the person's decision 2026-11-08).

The whole flow (approve → type_width → the drawing fix → writeback → tables → IFC) runs inside pytest's temporary
folder, through the command line, with the test terminal override (it works only for databases under the temporary
folder). This is the regular way to check the flow end to end; no script outside the tests calls a confirmation.

IfcOpenShell is not a dependency of btruth. The check runs when IfcOpenShell can be imported here, or when the
environment variable BTRUTH_IFC_PYTHON names a Python that has it (e.g. a separate environment out/_ifcvenv);
otherwise the test is skipped.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import ROOT
from test_cli_stage6 import build, issue_id, run

HELPER = Path(__file__).parent / "ifc_check_helper.py"


def ifc_python() -> str | None:
    if importlib.util.find_spec("ifcopenshell") is not None:
        return sys.executable
    p = os.environ.get("BTRUTH_IFC_PYTHON")
    if p and Path(p).exists():
        return str(Path(p).resolve())
    return None


def check_files(python: str, files: list[Path]) -> list[dict]:
    r = subprocess.run([python, str(HELPER), *map(str, files)], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return [json.loads(line) for line in r.stdout.splitlines() if line.startswith("{")]


@pytest.mark.skipif(ifc_python() is None, reason="IfcOpenShell がない（BTRUTH_IFC_PYTHON で別の環境を指せる）")
def test_the_ifc_of_the_trial_flow_is_valid_ifc4(tmp_path):
    folder = tmp_path / "try6"
    interp = build(folder)
    assert run("approve", folder, "--interpretation", interp[:8], "--reason", "見比べた", stdin="y\n", terminal=True).returncode == 0
    late = issue_id(run("issues", folder).stdout, "決定が未反映")
    assert run("choose", folder, "--issue", late[:8], "--option", "type_width", "--reason", "議事録どおり", stdin="y\n",
               terminal=True).returncode == 0
    fix = issue_id(run("issues", folder).stdout, "言い分の食い違い（主と従）", contains="図面の修正案")
    assert run("choose", folder, "--issue", fix[:8], "--option", "fix_secondary", "--reason", "図面を直す", stdin="y\n",
               terminal=True).returncode == 0
    assert run("writeback", folder, "--source", "平面図", "--original", ROOT / "samples" / "step5" / "plan.dxf",
               "--out", folder / "out" / "plan_wb.dxf").returncode == 0
    assert run("tables", folder).returncode == 0
    r = run("ifc", folder)
    assert r.returncode == 0, r.stderr
    [res] = check_files(ifc_python(), [folder / "out" / "model.ifc"])
    assert res["schema"] == "IFC4"
    assert res["problems"] == []
    assert res["shapes_ok"] > 0 and res["shapes_failed"] == 0
