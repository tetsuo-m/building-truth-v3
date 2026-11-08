from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ClueRecord:
    """One clue as the reader saw it (B-1). `parent_index` points at another record of the same
    result (block definition for its entities, row for its cells, paragraph for its sentences)."""
    kind: str
    layer_raw: str | None = None
    geometry: dict | None = None
    text_raw: str | None = None
    style: dict | None = None
    format_extra: dict | None = None
    parent_index: int | None = None


@dataclass
class ReadResult:
    format: str
    reader_name: str
    reader_version: str
    unit_factor: float
    clues: list[ClueRecord] = field(default_factory=list)
    notes: list[tuple[str, dict]] = field(default_factory=list)    # (kind for intake_log, detail)


class Reader:
    name: str = ""
    version: str = ""
    formats: tuple[str, ...] = ()
    note: str = ""

    def read(self, path: Path, settings: dict | None = None) -> ReadResult:   # pragma: no cover
        raise NotImplementedError
