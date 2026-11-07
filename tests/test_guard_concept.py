"""The Claude Code hook must stop Claude Code from changing CONCEPT.md (CONCEPT.md G-2: only the person edits it).

Reading stays allowed: the Read tool, cat/grep/head/sed -n, git diff/log/add/commit.
Blocked: Edit/Write/MultiEdit/NotebookEdit on the file, and Bash commands that rewrite it
(redirection, sed -i, tee, mv, cp, rm, git checkout/restore, Python or other programs that mention it).
"""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from conftest import ROOT

HOOK = ROOT / ".claude" / "hooks" / "guard_concept.py"
MSG = "CONCEPT.md"
CONCEPT = ROOT / "CONCEPT.md"


def hook(tool, tool_input):
    data = {"tool_name": tool, "tool_input": tool_input, "cwd": str(ROOT)}
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(data), capture_output=True,
                          text=True, encoding="utf-8", env={"CLAUDE_PROJECT_DIR": str(ROOT), "PATH": ""})


BLOCKED_TOOLS = [
    ("Edit", {"file_path": str(CONCEPT), "old_string": "a", "new_string": "b"}),
    ("Edit", {"file_path": "CONCEPT.md", "old_string": "a", "new_string": "b"}),
    ("Write", {"file_path": str(CONCEPT), "content": "x"}),
    ("Write", {"file_path": "./docs/../CONCEPT.md", "content": "x"}),
    ("MultiEdit", {"file_path": str(CONCEPT), "edits": []}),
    ("NotebookEdit", {"notebook_path": str(CONCEPT)}),
    ("Write", {"file_path": "concept.md", "content": "x"}),          # case must not open a way around
]
BLOCKED_BASH = [
    "echo x > CONCEPT.md",
    "cat extra.md >> CONCEPT.md",
    "sed -i 's/a/b/' CONCEPT.md",
    "sed --in-place 's/a/b/' CONCEPT.md",
    "cat CONCEPT.md | sed 's/a/b/' > CONCEPT.md",
    "echo x | tee CONCEPT.md",
    "mv draft.md CONCEPT.md",
    "cp draft.md CONCEPT.md",
    "rm CONCEPT.md",
    "git checkout -- CONCEPT.md",
    "git restore CONCEPT.md",
    "git checkout HEAD~1 -- CONCEPT.md",
    "git stash push CONCEPT.md",
    "python -c \"open('CONCEPT.md','w').write('x')\"",
    "cd docs && echo x > ../CONCEPT.md",
    "python - <<'EOF'\nfrom pathlib import Path\nPath('CONCEPT.md').write_text('x')\nEOF",
    "cat CONCEPT.md && echo y > CONCEPT.md",
    "truncate -s 0 CONCEPT.md",
    "perl -pi -e 's/a/b/' CONCEPT.md",
    f"echo x > {CONCEPT}",
]
ALLOWED_TOOLS = [
    ("Read", {"file_path": str(CONCEPT)}),
    ("Grep", {"pattern": "B-5", "path": str(CONCEPT)}),
    ("Edit", {"file_path": str(ROOT / "DECISIONS.md"), "old_string": "a", "new_string": "b"}),
    ("Write", {"file_path": str(ROOT / "docs" / "CONCEPT_GAP.md"), "content": "x"}),
    ("Write", {"file_path": str(ROOT / "docs" / "NOT_CONCEPT.md"), "content": "x"}),
]
ALLOWED_BASH = [
    "cat CONCEPT.md",
    "grep -n 'B-5' CONCEPT.md",
    "head -20 CONCEPT.md",
    "tail -n +100 CONCEPT.md",
    "sed -n 1,10p CONCEPT.md",
    "wc -l CONCEPT.md",
    "diff CONCEPT.md docs/CONCEPT_GAP.md",
    "git diff CONCEPT.md",
    "git log --oneline -- CONCEPT.md",
    "git add CONCEPT.md CLAUDE.md",
    "git commit -m 'Add CONCEPT.md as the top-level premise'",
    "git show HEAD:CONCEPT.md",
    "echo x > docs/CONCEPT_GAP.md",
    "python -m pytest -q tests",
    "sed -i 's/a/b/' DECISIONS.md",
    # punctuation inside quotes is text, not a command separator or a redirection
    "git commit -m 'Add CONCEPT.md as the premise; hook that stops changes (CONCEPT.md G-2)'",
    "git commit -m 'Guard CONCEPT.md' -m 'Co-Authored-By: A B <noreply@example.com>'",
    "git commit -m 'CONCEPT.md: reading | writing; a > b'",
    # a Python one-liner about another file, followed by a git command that only mentions CONCEPT.md
    "python -c \"print(len('x'));\" && git add CONCEPT.md && git commit -m 'x'",
    "python - <<'EOF'\nfrom pathlib import Path\np = Path('DECISIONS.md'); print(p.read_text()[:3])\nEOF\ngit add CONCEPT.md",
]


@pytest.mark.parametrize("tool,tool_input", BLOCKED_TOOLS)
def test_write_tools_on_concept_are_stopped(tool, tool_input):
    r = hook(tool, tool_input)
    assert r.returncode == 2
    assert MSG in r.stderr and "書き換え" in r.stderr


@pytest.mark.parametrize("command", BLOCKED_BASH)
def test_bash_commands_that_rewrite_concept_are_stopped(command):
    r = hook("Bash", {"command": command})
    assert r.returncode == 2, r.stderr
    assert MSG in r.stderr and "書き換え" in r.stderr


@pytest.mark.parametrize("tool,tool_input", ALLOWED_TOOLS)
def test_reading_and_other_files_pass(tool, tool_input):
    r = hook(tool, tool_input)
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("command", ALLOWED_BASH)
def test_read_only_bash_passes(command):
    r = hook("Bash", {"command": command})
    assert r.returncode == 0, r.stderr
