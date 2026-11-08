"""Readers turn one file into clue records and nothing else (design 0-1, B-1, B-2).

Adding a reader (JWW later) adds a module here; the tables of the vessel do not change.
"""
from __future__ import annotations

from pathlib import Path

from btruth.readers.base import ClueRecord, ReadResult, Reader
from btruth.readers.csv_reader import CsvReader
from btruth.readers.dxf_reader import DxfReader
from btruth.readers.ids_reader import IdsReader
from btruth.readers.text_reader import TextReader

READERS: list[Reader] = [DxfReader(), CsvReader(), TextReader(), IdsReader()]


def reader_for(path: Path) -> Reader | None:
    suffix = Path(path).suffix.lower().lstrip(".")
    for r in READERS:
        if suffix in r.formats:
            return r
    return None


__all__ = ["ClueRecord", "ReadResult", "Reader", "READERS", "reader_for"]
