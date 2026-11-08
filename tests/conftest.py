"""Shared values and fixtures for the tests: the repository root, and the terminal override for the
confirmation commands (BRIEF step3 §3-4: it works only for databases under the temporary folder)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def terminal_ok(monkeypatch):
    """Let the confirmation commands believe they run in a terminal — for *temporary* databases only.
    The override is the environment variable BTRUTH_TEST_TERMINAL=ok; btruth.review honours it only when
    the database lies under the system's temporary folder (pytest's tmp_path does)."""
    monkeypatch.setenv("BTRUTH_TEST_TERMINAL", "ok")
    yield


@pytest.fixture
def no_terminal(monkeypatch):
    """Make sure no override is active: the confirmation commands must refuse (G-1 (b))."""
    monkeypatch.delenv("BTRUTH_TEST_TERMINAL", raising=False)
    yield


def subprocess_env(terminal: bool) -> dict:
    env = dict(os.environ)
    if terminal:
        env["BTRUTH_TEST_TERMINAL"] = "ok"
    else:
        env.pop("BTRUTH_TEST_TERMINAL", None)
    return env
