"""CSV reader: each data row is a ROW clue (the raw line), each cell a CELL clue under its row.

Cells stay text (B-1: the reader does not interpret "115.5" as a number). The header is kept in
format_extra so the table reader of stage 5 can use column names. Encoding: the project's setting
first (utf-8-sig), then cp932; the choice is noted for intake_log.
"""
from __future__ import annotations

import csv
from pathlib import Path

from btruth.readers.base import ClueRecord, ReadResult, Reader


class CsvReader(Reader):
    name = "csv"
    version = "csv/1"
    formats = ("csv", "tsv")
    note = "行を ROW、セルを CELL の手掛かりにする。値は文字のまま"

    def read(self, path: Path, settings: dict | None = None) -> ReadResult:
        settings = settings or {}
        first = settings.get("csv_encoding") or "utf-8-sig"
        data = Path(path).read_bytes()
        text, used = None, None
        for enc in (first, "cp932", "utf-8"):
            try:
                text = data.decode(enc)
                used = enc
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            text, used = data.decode(first, errors="replace"), first + "(errors=replace)"
        notes = [("文字コード", {"encoding": used, "tried_first": first})]
        result = ReadResult(format=Path(path).suffix.lower().lstrip("."), reader_name=self.name,
                            reader_version=self.version, unit_factor=1.0, notes=notes)
        delimiter = "\t" if result.format == "tsv" else ","
        lines = text.splitlines()
        if not lines:
            return result
        header = next(csv.reader([lines[0]], delimiter=delimiter))
        header = [h.lstrip("﻿") for h in header]
        row_no = 0
        for line_no, line in enumerate(lines[1:], start=2):
            if not line.strip():
                continue
            row_no += 1
            values = next(csv.reader([line], delimiter=delimiter))
            row = ClueRecord(kind="ROW", layer_raw=None, geometry=None, text_raw=line, style=None,
                             format_extra={"row_no": row_no, "line_no": line_no, "columns": header,
                                           "values": {h: (values[i] if i < len(values) else None) for i, h in enumerate(header)}})
            result.clues.append(row)
            parent_index = len(result.clues) - 1
            for col_no, value in enumerate(values):
                column = header[col_no] if col_no < len(header) else None
                result.clues.append(ClueRecord(kind="CELL", text_raw=value, parent_index=parent_index,
                                               format_extra={"row_no": row_no, "col_no": col_no + 1, "column": column}))
        result.notes.append(("表の形", {"columns": header, "rows": row_no}))
        return result
