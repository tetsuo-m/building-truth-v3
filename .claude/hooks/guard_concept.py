"""PreToolUse hook: Claude Code must not change CONCEPT.md (CONCEPT.md G-2: only the person edits it).

Stops (exit code 2):
  - Edit / Write / MultiEdit / NotebookEdit whose target is CONCEPT.md (any folder, any letter case);
  - Bash command segments that mention CONCEPT.md and could rewrite it: any redirection in the segment,
    or a program that is not on the read-only list (sed/perl with an in-place flag, tee, mv, cp, rm,
    python, here-documents, ...), or a git subcommand that rewrites the working copy
    (checkout, restore, reset, stash, mv, rm, clean, ...).
Lets through: reading (Read, Grep, cat, head, tail, grep, sed -n, wc, diff, ...), git diff/log/show/
blame/add/commit, and anything that does not mention CONCEPT.md.

Input: the hook JSON on stdin. Standard library only.
"""
from __future__ import annotations

import json
import re
import shlex
import sys

TARGET = "concept.md"
PATH_KEYS = ("file_path", "path", "notebook_path")
WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
MENTION = re.compile(r"(?i)(?<![\w.-])concept\.md\b")
SEGMENT_SPLIT = re.compile(r"&&|\|\||;|\||\n")
READ_ONLY = {
    "cat", "head", "tail", "grep", "egrep", "fgrep", "rg", "wc", "less", "more", "diff", "cmp",
    "md5sum", "sha256sum", "shasum", "file", "stat", "ls", "find", "sort", "uniq", "cut", "nl", "od",
    "strings", "echo", "printf", "test", "[", "true", "iconv", "nkf", "column", "tr", "fold", "expand",
}
INPLACE_OK = {"sed", "awk", "gawk", "perl"}          # read-only unless an in-place flag is present
INPLACE_FLAG = re.compile(r"^(-i|--in-place|-[a-zA-Z]*i[a-zA-Z]*|-pi|-ni|-pie|-i\.\S*)$")
GIT_READ = {"diff", "log", "show", "blame", "status", "grep", "add", "commit", "push", "ls-files",
            "cat-file", "rev-parse", "describe", "shortlog", "whatchanged", "difftool"}
MSG = ("CONCEPT.md は Claude Code が書き換えない（CONCEPT.md G-2：直すのは人だけ）。読むのは止めない。"
       "直したいことがあれば、人に文章で示す：")


def _is_target_path(raw: str) -> bool:
    name = re.split(r"[\\/]+", raw.strip().strip("'\""))[-1]
    return name.lower() == TARGET


def _program(tokens: list[str]) -> tuple[str, list[str]]:
    rest = list(tokens)
    while rest and re.match(r"^\w+=", rest[0]):      # FOO=bar cmd ...
        rest.pop(0)
    if not rest:
        return "", []
    prog = re.split(r"[\\/]+", rest[0])[-1].lower()
    if prog.endswith(".exe"):
        prog = prog[:-4]
    return prog, rest[1:]


SEPARATORS = {"&&", "||", ";", "|", "&", ";;", "\n"}


def _segments(cmd: str) -> list[list[str]] | None:
    """Split into command segments with quotes respected (a ';' or '>' inside quotes is text).

    Returns None when the command cannot be tokenised (unbalanced quotes); the caller then falls
    back to the plain text split, which is the more cautious reading.
    """
    try:
        # Keep Windows backslashes as text (posix shlex would otherwise eat them and hide the file name).
        # A newline outside quotes separates commands too (here-document bodies end at their marker).
        lex = shlex.shlex(cmd.replace("\\", "\\\\"), posix=True, punctuation_chars="();<>|&\n")
        lex.whitespace = " \t\r"
        lex.whitespace_split = True
        tokens = list(lex)
    except ValueError:
        return None
    # shlex glues adjacent punctuation into one token ("); " -> ");"); split such runs into operators.
    flat = []
    for t in tokens:
        if re.fullmatch(r"[();<>|&\n]+", t):
            flat.extend(re.findall(r"&&|\|\||;;|>>|<<|[();<>|&\n]", t))
        else:
            flat.append(t)
    segments, cur = [], []
    for t in flat:
        if t in SEPARATORS:
            if cur:
                segments.append(cur)
            cur = []
        else:
            cur.append(t)
    if cur:
        segments.append(cur)
    return segments


def _tokens_may_write(tokens: list[str]) -> bool:
    if any(t in (">", ">>", ">|", "&>", ">&") for t in tokens):
        return True
    return _program_may_write(*_program(tokens))


def _segment_may_write(seg: str) -> bool:
    if ">" in seg:
        return True
    try:
        tokens = shlex.split(seg, posix=True)
    except ValueError:
        tokens = seg.split()
    return _program_may_write(*_program(tokens))


def _program_may_write(prog: str, args: list[str]) -> bool:
    if prog in READ_ONLY:
        return False
    if prog in INPLACE_OK:
        return any(INPLACE_FLAG.match(a) for a in args)
    if prog == "git":
        sub = next((a for a in args if not a.startswith("-")), "")
        return sub not in GIT_READ
    return True


def check_bash(cmd: str) -> bool:
    segments = _segments(cmd)
    if segments is not None:
        for tokens in segments:
            if any(MENTION.search(t) for t in tokens) and _tokens_may_write(tokens):
                return True
        return False
    # Fallback (unbalanced quotes): judge the plain text, cautiously.
    for seg in SEGMENT_SPLIT.split(cmd):
        if MENTION.search(seg) and _segment_may_write(seg):
            return True
    if "<<" in cmd and MENTION.search(cmd):
        first = SEGMENT_SPLIT.split(cmd)[0]
        if _segment_may_write(first):
            return True
    return False


def evaluate(data: dict) -> bool:
    tool = data.get("tool_name", "")
    ti = data.get("tool_input") or {}
    if tool == "Bash":
        return check_bash(str(ti.get("command", "")))
    if tool in WRITE_TOOLS:
        return any(key in ti and ti[key] and _is_target_path(str(ti[key])) for key in PATH_KEYS)
    return False


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    if evaluate(data):
        ti = data.get("tool_input") or {}
        shown = ti.get("command") if data.get("tool_name") == "Bash" else \
            f"{data.get('tool_name')} {ti.get('file_path') or ti.get('notebook_path') or ''}"
        print(MSG + "\n" + str(shown), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
