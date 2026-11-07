"""Shared value for the hook tests: the repository root (the folder that holds .claude/ and tests/)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
