"""PreToolUse hook: Claude Code must not record confirmations (CONCEPT D-3, design G-1) nor write the
database file directly (G-1 (a), failure F-13).

Stopped (exit code 2):
  * btruth decide / approve / reject / hold / name / exclude-room / approve-moves / resolve-recheck (stage 4) / choose (stage 5),
    and btruth rule --set — also when
    called from `python -c`, a here-document, or a subprocess call inside Python;
  * Python code that imports btruth and calls the review API (approve_items, decide, ...);
  * any Bash command that names a database file (*.sqlite, *.sqlite3, *.db) or uses sqlite3;
  * Edit / Write / MultiEdit / NotebookEdit whose target is a database file.
When stopped, the hook prints the command so that the person can run it.

Limits: a script *file* that Claude Code writes and then runs is not seen by this hook (design 3-9 F-13,
the remaining hole). Standard library only, so it runs on Windows and Linux without a venv.
"""
from __future__ import annotations

import json
import re
import shlex
import sys

CONFIRM = {"decide", "approve", "reject", "hold", "name", "exclude-room", "approve-moves", "resolve-recheck", "choose"}
CONFIRM_RE = "|".join(re.escape(c) for c in sorted(CONFIRM))
SEGMENT_SPLIT = re.compile(r"&&|\|\||;|\||\n")
# python -c / here-documents that drive btruth from inside Python
INLINE = [
    re.compile(r"""['"]btruth['"]\s*,\s*['"](%s)['"]""" % CONFIRM_RE),
    re.compile(r"""btruth['"]?\s+(%s)\b""" % CONFIRM_RE),
    re.compile(r"""['"]rule['"]\s*,.*['"]--set['"]"""),
]
API = re.compile(r"\b(approve_items|approve_interpretation|approve_moves|resolve_recheck|choose_option|reject_items|hold_items|hold_issue|decide|name_element|"
                 r"exclude_room|add_decision|add_adopted|set_rule|review)\s*\(")
IMPORTS_BTRUTH = re.compile(r"\b(from|import)\s+btruth\b")
DB_FILE = re.compile(r"(?i)\.(sqlite3?|db)(?![\w])")
SQLITE3 = re.compile(r"(?i)(?<![\w.])sqlite3(?![\w])")
PATH_KEYS = ("file_path", "path", "notebook_path")
WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}

MSG_CONFIRM = "このコマンドは人が実行してください（承認・判断を確定させるコマンドは、Claude Code は実行しません。D-3）："
MSG_DB = ("DB のファイル（*.sqlite / *.db）を直接扱うコマンドや sqlite3 は、Claude Code は実行しません"
          "（G-1 (a)、F-13。正本には btruth のコマンドを通して、物件のフォルダを渡して書く）：")
MSG_DB_TOOL = "DB のファイルは Claude Code が直接書き換えません（G-1 (a)、F-13）："


def _btruth_subcommand(tokens: list[str]) -> tuple[str | None, list[str]]:
    """Find `... -m btruth <sub> args` or `btruth <sub> args` in one command segment."""
    for i, t in enumerate(tokens):
        base = re.split(r"[\\/]", t)[-1]
        if base == "btruth":
            rest = tokens[i + 1:]
            sub = next((x for x in rest if not x.startswith("-")), None)
            return sub, rest
    return None, []


def blocked_confirm(command: str) -> bool:
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


def blocked_db(command: str) -> bool:
    return bool(DB_FILE.search(command) or SQLITE3.search(command))


def blocked(command: str) -> bool:          # kept for older tests / callers
    return blocked_confirm(command) or blocked_db(command)


def db_target(tool_input: dict) -> str | None:
    for key in PATH_KEYS:
        raw = tool_input.get(key)
        if raw and DB_FILE.search(str(raw).strip().strip("'\"")):
            return str(raw)
    return None


def main() -> int:
    # Windows defaults to cp932; Claude Code (and the tests) read the message as UTF-8.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    tool = data.get("tool_name")
    ti = data.get("tool_input") or {}
    if tool == "Bash":
        cmd = str(ti.get("command", ""))
        if blocked_confirm(cmd):
            print(MSG_CONFIRM + "\n" + cmd, file=sys.stderr)
            return 2
        if blocked_db(cmd):
            print(MSG_DB + "\n" + cmd, file=sys.stderr)
            return 2
        return 0
    if tool in WRITE_TOOLS:
        target = db_target(ti)
        if target:
            print(MSG_DB_TOOL + "\n" + f"{tool} {target}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
