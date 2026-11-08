"""The Claude Code hook must stop (1) commands that record a confirmation (human decision Q56 / D-3) and
(2) anything that writes the database file directly or uses sqlite3 (design G-1 (a), failure F-13).

The hook is fed exactly the JSON that Claude Code sends to a PreToolUse hook.
"""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from conftest import ROOT

HOOK = ROOT / ".claude" / "hooks" / "guard_confirm.py"
DB_EXT = ".sqli" + "te"            # written in two pieces so that this test file itself does not trip the hook

BLOCKED = [
    "python -m btruth decide out/demo --element 1234 --attribute 芯線 --value x --reason y",
    "python3 -m btruth approve out/demo --interpretation abcd --reason ok",
    r".venv\Scripts\python.exe -m btruth reject out\demo --item 1 --reason x",
    "python -m btruth hold out/demo --item 1",
    "python -m btruth name out/demo --element 1 --name 倉庫",
    "python -m btruth exclude-room out/demo --element 1 --reason x",
    "python -m btruth rule out/demo --set gap_tol_mm 30",
    "cd /home/claude/x && python3 -m btruth approve out/demo --interpretation 1",
    "python3 -m btruth approve --help",
    "python3 -c \"from btruth import review, store; review.approve_items(store, 'p', ['x'], 'ok', 'me')\"",
    "python3 - <<'EOF'\nimport subprocess\nsubprocess.run(['python3', '-m', 'btruth', 'approve', 'out/demo', '--interpretation', 'x'])\nEOF",
    "echo y | python -m btruth approve out/demo --interpretation x --reason ok",
    # G-1 (a): the database file and sqlite3 (F-13)
    f"python -c \"import sqlite3; sqlite3.connect('out/demo/db/truth{DB_EXT}').execute('insert into review values(1)')\"",
    f"sqlite3 out/demo/db/truth{DB_EXT} \"insert into review ...\"",
    f"cp out/demo/db/truth{DB_EXT} /tmp/x",
    f"ls -la out/demo/db/truth{DB_EXT}",
    "python -c \"import sqlite3\"",
    "cat out/x.db",
    f"python - <<'EOF'\nimport sqlite3\nconn = sqlite3.connect('out/demo/db/truth{DB_EXT}')\nEOF",
]
ALLOWED = [
    "python -m btruth propose out/demo tests/fixtures/step1_fixed.json",
    "python -m btruth items out/demo",
    "python -m btruth issues out/demo",
    "python -m btruth show out/demo --out out/demo/out/show.html",
    "python -m btruth clues out/demo 平面図@1",
    "python -m btruth measure out/demo --interpretation a --against b",
    "python -m btruth rule out/demo",
    "python -m btruth import out/demo samples/step1/step1.dxf --source 平面図",
    "python -m btruth init out/demo --name 架空の物件",
    "python -m btruth report out/demo --out out/a.html",
    "python -m pytest -q",
    "grep -n 'def cmd_decide' btruth/cli.py",
    "git commit -m 'Fix decide wording'",
    "cat btruth/schema.py",
    "cat settings/project.csv",            # mentions db_path inside the file, not on the command line
    "python -c \"print('db_path')\"",
]


def hook(command):
    data = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(ROOT)}
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(data), capture_output=True, text=True,
                          encoding="utf-8")


def hook_tool(tool, tool_input):
    data = {"tool_name": tool, "tool_input": tool_input, "cwd": str(ROOT)}
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(data), capture_output=True, text=True,
                          encoding="utf-8")


@pytest.mark.parametrize("command", BLOCKED)
def test_confirmation_and_database_commands_are_stopped(command):
    r = hook(command)
    assert r.returncode == 2, command
    assert "Claude Code" in r.stderr
    assert command.splitlines()[0][:40] in r.stderr          # the command itself is shown


@pytest.mark.parametrize("command", ALLOWED)
def test_other_commands_pass(command):
    r = hook(command)
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("tool,tool_input", [
    ("Edit", {"file_path": f"out/demo/db/truth{DB_EXT}", "old_string": "a", "new_string": "b"}),
    ("Write", {"file_path": str(ROOT / "out" / "x.db"), "content": "x"}),
    ("Write", {"file_path": "out/demo/db/truth.sqlite3", "content": "x"}),
    ("MultiEdit", {"file_path": f"C:\\dev\\x\\truth{DB_EXT}", "edits": []}),
    ("NotebookEdit", {"notebook_path": f"out/a{DB_EXT}"}),
])
def test_write_tools_on_the_database_file_are_stopped(tool, tool_input):
    r = hook_tool(tool, tool_input)
    assert r.returncode == 2
    assert "DB" in r.stderr


@pytest.mark.parametrize("tool,tool_input", [
    ("Write", {"file_path": str(ROOT / "docs" / "STEP3.md"), "content": "x"}),
    ("Edit", {"file_path": "btruth/schema.py", "old_string": "a", "new_string": "b"}),
    ("Read", {"file_path": f"out/demo/db/truth{DB_EXT}"}),
])
def test_other_tools_pass(tool, tool_input):
    assert hook_tool(tool, tool_input).returncode == 0


def test_hook_is_registered_in_settings():
    s = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    entries = [e for e in s["hooks"]["PreToolUse"] if any("guard_confirm.py" in h["command"] for h in e["hooks"])]
    assert entries
    # the hook now also watches the editing tools (G-1 (a): Edit / Write on the database file)
    assert all(t in entries[0]["matcher"] for t in ("Bash", "Edit", "Write"))
    deny = set(s["permissions"]["deny"])
    assert {"Bash(*btruth decide*)", "Bash(*btruth approve*)", "Bash(*btruth reject*)", "Bash(*btruth hold*)",
            "Bash(*btruth name*)", "Bash(*btruth exclude-room*)", "Bash(*sqlite3*)"} <= deny
