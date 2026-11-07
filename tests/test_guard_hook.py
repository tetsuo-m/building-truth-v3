"""The Claude Code hook must block reads outside the project and of building_db/.

Human decision Q60: folders named in the environment variable BTRUTH_EXTRA_DIRS (os.pathsep-separated,
set by the person for one session) count as inside. Everything else stays blocked as before.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from conftest import ROOT

HOOK = ROOT / ".claude" / "hooks" / "guard_paths.py"
# Folders for the tests only: outside the project and outside the temp folder (which Bash may use).
EXTRA = ROOT.parent / "extra-data-for-tests"
EXTRA2 = ROOT.parent / "second-extra-folder"
OTHER = ROOT.parent / "some-other-folder"


def hook(tool, tool_input, extra_dirs=None):
    data = {"tool_name": tool, "tool_input": tool_input, "cwd": str(ROOT)}
    env = {"CLAUDE_PROJECT_DIR": str(ROOT), "PATH": ""}
    if extra_dirs is not None:
        env["BTRUTH_EXTRA_DIRS"] = extra_dirs
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(data),
                          capture_output=True, text=True, env=env).returncode


def test_inside_project_is_allowed():
    assert hook("Read", {"file_path": str(ROOT / "BRIEF.md")}) == 0
    assert hook("Read", {"file_path": "samples/step1/expected.md"}) == 0
    assert hook("Bash", {"command": "python -m pytest -q tests"}) == 0


def test_outside_project_is_blocked():
    assert hook("Read", {"file_path": str(ROOT.parent / "building-truth-v1" / "BRIEF.md")}) == 2
    assert hook("Read", {"file_path": "../other/x.py"}) == 2
    assert hook("Grep", {"pattern": "def", "path": ".."}) == 2
    assert hook("Bash", {"command": "cat ../building-truth/README.md"}) == 2


def test_building_db_is_blocked_everywhere():
    assert hook("Read", {"file_path": str(ROOT / "building_db" / "cli.py")}) == 2
    assert hook("Glob", {"pattern": "building_db/**/*.py"}) == 2
    assert hook("Bash", {"command": "ls building_db"}) == 2


# ---------------------------------------------------------------- v3 BRIEF 1.5-2: v2 must not be read either
def test_building_truth_v2_is_blocked_everywhere():
    v2 = ROOT.parent / "building-truth-v2"
    assert hook("Read", {"file_path": str(v2 / "btruth" / "store.py")}) == 2
    assert hook("Read", {"file_path": "../building-truth-v2/QUESTIONS.md"}) == 2
    assert hook("Grep", {"pattern": "def", "path": str(v2)}) == 2
    assert hook("Glob", {"pattern": str(v2 / "**" / "*.py")}) == 2
    assert hook("Bash", {"command": f"cat {v2 / 'DECISIONS.md'}"}) == 2
    assert hook("Bash", {"command": "ls ../building-truth-v2"}) == 2
    # even inside a folder the person opened for the session
    e = str(EXTRA)
    assert hook("Read", {"file_path": str(EXTRA / "building-truth-v2" / "x.md")}, e) == 2
    assert hook("Bash", {"command": f"ls {EXTRA / 'building-truth-v2'}"}, e) == 2


def test_v3_itself_is_not_mistaken_for_v2():
    assert hook("Read", {"file_path": str(ROOT / "v2_decisions.md")}) == 0
    assert hook("Bash", {"command": "grep -n Q51 v2_decisions.md"}) == 0


# ---------------------------------------------------------------- v3 BRIEF 1.5-2 / 1.5-3: settings.json
def _settings():
    return json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))


def test_settings_deny_v2_folder():
    deny = set(_settings()["permissions"]["deny"])
    assert {"Read(**/building-truth-v2/**)", "Edit(**/building-truth-v2/**)",
            "Bash(*building-truth-v2*)"} <= deny


def test_settings_leave_outside_folders_to_guard_paths():
    # The '../**' rules blocked the folders the person opened with BTRUTH_EXTRA_DIRS;
    # the hook guard_paths.py is the only gate for "outside" now.
    deny = _settings()["permissions"]["deny"]
    assert not any(rule.endswith("(../**)") for rule in deny), deny
    # Write(...) rules never match in Claude Code (the Edit(...) rules cover the Write tool).
    assert not any(rule.startswith("Write(") for rule in deny), deny
    cmds = [h["command"] for e in _settings()["hooks"]["PreToolUse"] for h in e["hooks"]]
    assert any("guard_paths.py" in c for c in cmds)


# ---------------------------------------------------------------- human decision Q60: BTRUTH_EXTRA_DIRS
def test_extra_dir_from_env_is_allowed():
    e = str(EXTRA)
    assert hook("Read", {"file_path": str(EXTRA / "data" / "a.dxf")}, e) == 0
    assert hook("Write", {"file_path": str(EXTRA / "out" / "r.html")}, e) == 0
    assert hook("Glob", {"pattern": str(EXTRA / "data" / "*.dxf")}, e) == 0
    assert hook("Grep", {"pattern": "LAYER", "path": str(EXTRA / "data")}, e) == 0
    assert hook("Bash", {"command": f"python -m btruth import {EXTRA / 'data' / 'a.dxf'} --db {EXTRA / 'out' / 'a.sqlite'}"}, e) == 0


def test_two_extra_dirs_are_separated_by_pathsep():
    e = os.pathsep.join([str(EXTRA), str(EXTRA2)])
    assert hook("Read", {"file_path": str(EXTRA / "x.md")}, e) == 0
    assert hook("Read", {"file_path": str(EXTRA2 / "x.md")}, e) == 0
    assert hook("Read", {"file_path": str(OTHER / "x.md")}, e) == 2


def test_other_folders_stay_blocked_with_extra_dir():
    e = str(EXTRA)
    assert hook("Read", {"file_path": str(OTHER / "x.md")}, e) == 2
    assert hook("Bash", {"command": f"ls {OTHER}"}, e) == 2
    assert hook("Read", {"file_path": "../other/x.py"}, e) == 2
    # a folder whose name merely starts with the extra folder's name is not inside it
    assert hook("Read", {"file_path": str(ROOT.parent / (EXTRA.name + "-2") / "x.md")}, e) == 2


def test_forbidden_names_stay_blocked_inside_extra_dir():
    e = str(EXTRA)
    assert hook("Read", {"file_path": str(EXTRA / "building_db" / "cli.py")}, e) == 2
    assert hook("Bash", {"command": f"ls {EXTRA / 'building_db'}"}, e) == 2
    assert hook("Read", {"file_path": str(EXTRA / "building-truth-v1" / "BRIEF.md")}, e) == 2


@pytest.mark.parametrize("value", ["", "   ", os.pathsep])
def test_empty_env_behaves_as_before(value):
    assert hook("Read", {"file_path": str(EXTRA / "x.md")}, value) == 2
    assert hook("Bash", {"command": f"ls {EXTRA}"}, value) == 2
    assert hook("Read", {"file_path": str(ROOT / "BRIEF.md")}, value) == 0


def test_relative_entry_in_env_is_ignored():
    # Only absolute folders count; a relative or empty entry must not open anything.
    assert hook("Read", {"file_path": str(EXTRA / "x.md")}, "..") == 2
    assert hook("Read", {"file_path": str(ROOT.parent / "x.md")}, "..") == 2
