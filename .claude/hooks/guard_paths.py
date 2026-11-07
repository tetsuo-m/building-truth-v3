"""PreToolUse hook: keep Claude Code inside this project folder.

Blocks (exit code 2) any tool call that would read or write a path outside
the project directory, or anything under a folder named ``building_db``,
``building-truth-v1`` or ``building-truth-v2`` (the earlier implementations
that this project must not read; v3 BRIEF 1.5-2).

Human decision Q60: the person may name extra folders in the environment variable
BTRUTH_EXTRA_DIRS (absolute paths, separated by os.pathsep) for one session; those count as
inside. Unset or empty, the hook behaves exactly as before. The forbidden names stay forbidden
everywhere, extra folders included.

Input: the hook JSON on stdin (tool_name, tool_input, cwd).
Standard library only, so it runs on Windows and Linux without a venv.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import sys
import tempfile
from pathlib import Path

FORBIDDEN_PARTS = {"building_db", "building-truth-v1", "building-truth-v2"}
FORBIDDEN_LABEL = "building_db / v1 / v2"
PATH_KEYS = ("file_path", "path", "notebook_path")


def project_dir(data: dict) -> Path:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env).resolve()
    # Fallback: the folder that holds .claude/ (this file is .claude/hooks/x.py)
    return Path(__file__).resolve().parents[2]


def extra_roots() -> list[Path]:
    """Folders the person opened for this session (human decision Q60). Absolute entries only."""
    out = []
    for raw in os.environ.get("BTRUTH_EXTRA_DIRS", "").split(os.pathsep):
        raw = raw.strip()
        if raw and Path(raw).is_absolute() and not _forbidden_name(raw):
            out.append(Path(os.path.normpath(raw)))
    return out


def _outside_msg(raw: str, root: Path, roots: list[Path]) -> str:
    msg = f"'{raw}' is outside the project folder {root}"
    if len(roots) > 1:
        msg += " (and the folders in BTRUTH_EXTRA_DIRS)"
    return msg


def _resolve(raw: str, base: Path) -> Path:
    p = Path(os.path.expanduser(raw))
    if not p.is_absolute():
        p = base / p
    return Path(os.path.normpath(str(p)))


def _inside(p: Path, root: Path) -> bool:
    try:
        p.relative_to(root)
        return True
    except ValueError:
        return False


def _forbidden_name(text: str) -> bool:
    parts = re.split(r"[\\/]+", text)
    return any(part in FORBIDDEN_PARTS for part in parts) or any(
        name in text for name in FORBIDDEN_PARTS
    )


def check_path(raw: str, base: Path, root: Path, roots: list[Path] | None = None) -> str | None:
    roots = roots or [root]
    if not raw:
        return None
    if _forbidden_name(raw):
        return f"blocked: '{raw}' points at a forbidden folder ({FORBIDDEN_LABEL})"
    p = _resolve(raw, base)
    if _forbidden_name(str(p)):
        return f"blocked: '{raw}' points at a forbidden folder ({FORBIDDEN_LABEL})"
    if not any(_inside(p, r) for r in roots):
        return "blocked: " + _outside_msg(raw, root, roots)
    return None


def _looks_like_path(tok: str) -> bool:
    return (
        tok.startswith(("/", "~", "..", "\\"))
        or re.match(r"^[A-Za-z]:[\\/]", tok) is not None
        or "/../" in tok
        or "\\..\\" in tok
    )


DRIVE_PATH = re.compile(r"""[A-Za-z]:[\\/][^\s"'|;&<>]*""")


def check_bash(cmd: str, base: Path, root: Path, roots: list[Path] | None = None) -> str | None:
    roots = roots or [root]
    if _forbidden_name(cmd):
        return f"blocked: the command mentions a forbidden folder ({FORBIDDEN_LABEL})"
    try:
        tokens = shlex.split(cmd, posix=True)
    except ValueError:
        tokens = cmd.split()
    allowed_roots = roots + [Path(tempfile.gettempdir()).resolve(), Path("/dev")]
    # Windows drive paths: shlex (posix) eats the backslashes, so check them on the raw text too.
    for piece in DRIVE_PATH.findall(cmd):
        p = _resolve(piece, base)
        if not any(_inside(p, r) for r in allowed_roots):
            return "blocked: the command refers to " + _outside_msg(piece, root, roots)
    prev = None
    for tok in tokens:
        # The program itself (first word, or after a pipe/;/&&) may live anywhere.
        is_program = prev is None or prev in {"|", "||", "&&", ";", "&"}
        prev = tok
        if is_program:
            continue
        for piece in re.split(r"[=,:](?=[/~.])", tok):
            if not _looks_like_path(piece):
                continue
            p = _resolve(piece, base)
            if not any(_inside(p, r) for r in allowed_roots):
                return "blocked: the command refers to " + _outside_msg(piece, root, roots)
    return None


def evaluate(data: dict) -> str | None:
    root = project_dir(data)
    roots = [root] + extra_roots()
    base = Path(data.get("cwd") or root)
    tool = data.get("tool_name", "")
    ti = data.get("tool_input") or {}
    if tool == "Bash":
        return check_bash(str(ti.get("command", "")), base, root, roots)
    for key in PATH_KEYS:
        if key in ti and ti[key]:
            msg = check_path(str(ti[key]), base, root, roots)
            if msg:
                return msg
    pattern = str(ti.get("pattern", "")) if tool == "Glob" else ""
    if pattern and (_forbidden_name(pattern) or _looks_like_path(pattern)):
        return check_path(pattern.split("*")[0] or ".", base, root, roots) or (
            "blocked: glob pattern points at a forbidden folder"
            if _forbidden_name(pattern) else None
        )
    return None


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0  # not our business; never break the session on bad input
    msg = evaluate(data)
    if msg:
        print(msg, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
