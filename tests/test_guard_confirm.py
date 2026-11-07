"""The Claude Code hook must stop commands that record a confirmation (human decision).

Human decision Q56: decide / approve / reject / rule --set are run by a person, never by Claude Code.
The hook is fed exactly the JSON that Claude Code sends to a PreToolUse hook.
"""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from conftest import ROOT

HOOK = ROOT / ".claude" / "hooks" / "guard_confirm.py"

BLOCKED = [
    "python -m btruth decide --db out/a.sqlite --issue wall_boundary_deviation:W-1,E-1 --choice align",
    "python3 -m btruth approve --db examples/ai_run/demo.sqlite --proposal P-6e94aa6c0b P-5c5a95be38",
    r".venv\Scripts\python.exe -m btruth reject --db out\a.sqlite --proposal P-1 --reason x",
    "python -m btruth rule --db out/a.sqlite --set gap_tol_mm 30",
    "cd /home/claude/building-truth-v2 && python3 -m btruth approve --db x.sqlite --proposal P-1",
    "python3 -m btruth decide --db x.sqlite --target W-1 --set-type WT-1",
    "python3 -m btruth approve --help",
    "python3 -c \"from btruth import ai, store; ai.review(store.connect('x'), ['P-1'], 'approve', None)\"",
    "python3 - <<'EOF'\nimport subprocess\nsubprocess.run(['python3', '-m', 'btruth', 'approve', '--db', 'x', '--proposal', 'P-1'])\nEOF",
]
ALLOWED = [
    "python -m btruth show --db out/a.sqlite --json",
    "python -m btruth propose --db out/a.sqlite examples/ai_run/proposal.json",
    "python -m btruth proposals --db out/a.sqlite",
    "python -m btruth rule --db out/a.sqlite",
    "python -m btruth report --db out/a.sqlite --out out/a.html",
    "python -m pytest -q",
    "grep -n 'def cmd_decide' btruth/cli.py",
    "git commit -m 'Fix decide wording'",
]


def hook(command):
    data = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(ROOT)}
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(data), capture_output=True, text=True,
                          encoding="utf-8")


@pytest.mark.parametrize("command", BLOCKED)
def test_confirmation_commands_are_stopped(command):
    r = hook(command)
    assert r.returncode == 2
    assert "このコマンドは人が実行してください" in r.stderr
    assert command.splitlines()[0][:40] in r.stderr          # the command itself is shown


@pytest.mark.parametrize("command", ALLOWED)
def test_other_commands_pass(command):
    r = hook(command)
    assert r.returncode == 0, r.stderr


def test_hook_is_registered_in_settings():
    s = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    cmds = [h["command"] for e in s["hooks"]["PreToolUse"] for h in e["hooks"]]
    assert any("guard_confirm.py" in c for c in cmds)
    deny = s["permissions"]["deny"]
    assert {"Bash(*btruth decide*)", "Bash(*btruth approve*)", "Bash(*btruth reject*)"} <= set(deny)
