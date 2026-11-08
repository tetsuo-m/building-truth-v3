"""Text reader (minutes, specifications): paragraphs and their sentences become clues (B-1, C-3).

A paragraph is a run of non-blank lines; a sentence ends at 。！？!? or a line break. The text is
kept as written; deciding what is a decision (〜とする) and what is pending is the interpreter's job.
"""
from __future__ import annotations

import re
from pathlib import Path

from btruth.readers.base import ClueRecord, ReadResult, Reader

SENTENCE_END = re.compile(r"(?<=[。！？!?])")


class TextReader(Reader):
    name = "text"
    version = "text/1"
    formats = ("txt", "md")
    note = "段落を PARAGRAPH、一文を SENTENCE の手掛かりにする"

    def read(self, path: Path, settings: dict | None = None) -> ReadResult:
        settings = settings or {}
        data = Path(path).read_bytes()
        text, used = None, None
        for enc in ("utf-8-sig", "cp932"):
            try:
                text, used = data.decode(enc), enc
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            text, used = data.decode("utf-8", errors="replace"), "utf-8(errors=replace)"
        result = ReadResult(format=Path(path).suffix.lower().lstrip("."), reader_name=self.name,
                            reader_version=self.version, unit_factor=1.0,
                            notes=[("文字コード", {"encoding": used})])
        lines = text.splitlines()
        para_lines: list[tuple[int, str]] = []

        def flush():
            if not para_lines:
                return
            start, end = para_lines[0][0], para_lines[-1][0]
            raw = "\n".join(l for _, l in para_lines)
            result.clues.append(ClueRecord(kind="PARAGRAPH", text_raw=raw,
                                           format_extra={"line_start": start, "line_end": end}))
            parent_index = len(result.clues) - 1
            index = 0
            for _, line in para_lines:
                for piece in SENTENCE_END.split(line):
                    piece = piece.strip()
                    if not piece:
                        continue
                    index += 1
                    result.clues.append(ClueRecord(kind="SENTENCE", text_raw=piece, parent_index=parent_index,
                                                   format_extra={"index": index}))
            para_lines.clear()

        for no, line in enumerate(lines, start=1):
            if line.strip():
                para_lines.append((no, line))
            else:
                flush()
        flush()
        result.notes.append(("文章の形", {"lines": len(lines),
                                       "paragraphs": sum(c.kind == "PARAGRAPH" for c in result.clues)}))
        return result
