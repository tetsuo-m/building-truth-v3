"""PreToolUse hook: Claude Code must not record confirmations (human decision Q56).

Commands that record a decision of a person are run by the person only:
  btruth decide / approve / reject, and btruth rule --set
also when called from `python -c` or a here-document that runs btruth.
When stopped, the hook prints the command so that the person can run it.

Limits (written in DECISIONS.md): a script file that calls these commands, or the automated tests
(which use temporary databases), are not seen by this hook.
Input: the hook JSON on stdin. Standard library only.
"""
from __future__ import annotations

import json
import re
import shlex
import sys

CONFIRM = {"decide", "approve", "reject"}
SEGMENT_SPLIT = re.compile(r"&&|\|\||;|\||\n")
# python -c / here-documents that drive btruth from inside Python
INLINE = [
    re.compile(r"""['"]btruth['"]\s*,\s*['"](decide|approve|reject)['"]"""),
    re.compile(r"""btruth['"]?\s+(decide|approve|reject)\b"""),
    re.compile(r"""['"]rule['"]\s*,.*['"]--set['"]"""),
]
API = re.compile(r"\b(add_decision|add_adopted|add_point_adopted|set_rule|review)\s*\(")
IMPORTS_BTRUTH = re.compile(r"\b(from|import)\s+btruth\b")


def _btruth_subcommand(tokens: list[str]) -> tuple[str | None, list[str]]:
    """Find `... -m btruth <sub> args` or `btruth <sub> args` in one command segment."""
    for i, t in enumerate(tokens):
        base = re.split(r"[\\/]", t)[-1]
        if base == "btruth" and (i == 0 or tokens[i - 1] in ("-m",) or i > 0):
            rest = tokens[i + 1:]
            sub = next((x for x in rest if not x.startswith("-")), None)
            return sub, rest
    return None, []


def blocked(command: str) -> bool:
    for seg in SEGMENT_SPLIT.split(command):
        try:
            toks = shlex.split(seg, posix=True)
        except ValueError:
            toks = seg.split()
        sub, rest = _btruth_subcommand(toks)
        if sub in CONFIRM:
            return True
        if sub == "rule" and "--set" in rest:
            return True
    if any(p.search(command) for p in INLINE):
        return True
    if IMPORTS_BTRUTH.search(command) and API.search(command):
        return True
    return False


def main() -> int:
    # Windows defaults to cp932; Claude Code (and the tests) read the message as UTF-8.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    if data.get("tool_name") != "Bash":
        return 0
    cmd = str((data.get("tool_input") or {}).get("command", ""))
    if blocked(cmd):
        print("このコマンドは人が実行してください（承認・判断を確定させるコマンドは、Claude Code は実行しません）：\n"
              + cmd, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
