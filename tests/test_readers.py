"""Readers only turn a file into clue rows (0-1, B-1): values unrounded, extras in format_extra."""
from __future__ import annotations

import json

from helpers import STEP1, STEP1_JW, write_dxf


def test_reader_is_chosen_by_file_format(tmp_path):
    from btruth.readers import reader_for

    assert reader_for(tmp_path / "a.dxf").name == "dxf"
    assert reader_for(tmp_path / "a.DXF").name == "dxf"
    assert reader_for(tmp_path / "a.csv").name == "csv"
    assert reader_for(tmp_path / "a.txt").name == "text"
    assert reader_for(tmp_path / "a.md").name == "text"
    assert reader_for(tmp_path / "a.jww") is None


def test_dxf_reader_keeps_values_unrounded(tmp_path):
    from btruth.readers import reader_for

    path = write_dxf(tmp_path / "f.dxf", [
        ("LINE", "WALL_CENTER", {"start": (1234.56789012345, -0.000123456789), "end": (6000.0000001, 4000)}),
        ("CIRCLE", "GRID", {"center": (0.1, 0.2), "radius": 399.9999999}),
        ("ARC", "GRID", {"center": (10, 20), "radius": 5, "start": 12.345678, "end": 270.000001}),
        ("TEXT", "ROOM_NAME", {"text": "101 事務室 X^d1", "insert": (3000, 2000), "height": 350, "rotation": 0.123456}),
        ("LWPOLYLINE", "ROOM_BOUNDARY", {"points": [(0, 0), (100.5, 0), (100.5, 50.25)], "close": True}),
        ("POINT", "GRID", {"location": (7.25, 8.5)}),
        ("INSERT", "DOOR", {"name": "DOOR_S", "insert": (2300, 1500)}),
    ], layers=["WALL_CENTER", "GRID", "ROOM_NAME", "ROOM_BOUNDARY", "DOOR"])
    result = reader_for(path).read(path)
    assert result.format == "dxf"
    assert result.unit_factor == 1.0
    top = [c for c in result.clues if c.parent_index is None]
    by_kind = {c.kind: c for c in top}
    line = by_kind["LINE"].geometry
    assert line["start"] == [1234.56789012345, -0.000123456789, 0.0]
    assert line["end"] == [6000.0000001, 4000.0, 0.0]
    assert by_kind["CIRCLE"].geometry["radius"] == 399.9999999
    assert by_kind["ARC"].geometry["start_angle"] == 12.345678
    text = by_kind["TEXT"]
    assert text.text_raw == "101 事務室 X^d1"           # control characters stay (B-1)
    assert text.geometry["rotation"] == 0.123456
    assert text.style["height"] == 350
    assert by_kind["LWPOLYLINE"].geometry["points"][2][:2] == [100.5, 50.25]
    assert by_kind["LWPOLYLINE"].geometry["closed"] is True
    assert by_kind["INSERT"].style["block_name"] == "DOOR_S"
    assert all("handle" in c.format_extra for c in top)
    # the block definition and its children are clues too, with the parent set
    defs = [c for c in result.clues if c.kind == "BLOCK_DEF"]
    assert [d.text_raw for d in defs] == ["DOOR_S"]
    children = [c for c in result.clues if c.parent_index is not None]
    assert len(children) == 1 and result.clues[children[0].parent_index].kind == "BLOCK_DEF"


def test_dxf_reader_reads_the_sample_files():
    from btruth.readers import reader_for

    r = reader_for(STEP1).read(STEP1)
    top = [c for c in r.clues if c.parent_index is None]
    assert sum(c.kind == "LINE" for c in top) == 12
    assert sum(c.kind == "TEXT" for c in top) == 5
    assert sum(c.kind == "CIRCLE" for c in top) == 4
    texts = {c.text_raw for c in top if c.kind == "TEXT"}
    assert "101 事務室" in texts
    # Jw_cad export: needs recovery and the Japanese code page; both are noted, nothing is dropped
    rj = reader_for(STEP1_JW).read(STEP1_JW)
    topj = [c for c in rj.clues if c.parent_index is None]
    assert sum(c.kind == "LINE" for c in topj) == 12
    assert sum(c.kind == "TEXT" for c in topj) == 5
    assert "101 事務室" in {c.text_raw for c in topj if c.kind == "TEXT"}
    assert {c.layer_raw for c in topj if c.kind == "LINE"} == {"_0-2_GRID", "_0-3_ROOM_BOUNDARY", "_0-5_WALL_CENTER"}
    note_kinds = {k for k, _ in rj.notes}
    assert "文字コード" in note_kinds
    assert "読み込みの修復" in note_kinds
    # raw coordinates are kept as Jw_cad wrote them (the frame is aligned only when comparing)
    x1 = [c for c in topj if c.kind == "TEXT" and c.text_raw == "X1"][0]
    assert x1.geometry["insert"][0] == 210000000.0


def test_csv_reader_rows_and_cells(tmp_path):
    from btruth.readers import reader_for

    p = tmp_path / "wall_types.csv"
    p.write_text("﻿type_code,name,total_thickness_mm\nWT-3,外壁,100\nWT-1,間仕切,115.5\n", encoding="utf-8")
    r = reader_for(p).read(p)
    rows = [c for c in r.clues if c.kind == "ROW"]
    cells = [c for c in r.clues if c.kind == "CELL"]
    assert len(rows) == 2 and len(cells) == 6
    assert rows[0].text_raw == "WT-3,外壁,100"
    assert rows[0].format_extra["columns"] == ["type_code", "name", "total_thickness_mm"]
    assert rows[1].format_extra["values"]["total_thickness_mm"] == "115.5"   # text, not a number
    assert r.clues[cells[0].parent_index] is rows[0]
    assert cells[2].format_extra["column"] == "total_thickness_mm"


def test_csv_reader_falls_back_to_cp932(tmp_path):
    from btruth.readers import reader_for

    p = tmp_path / "sjis.csv"
    p.write_bytes("符号,名前\nWT-1,間仕切\n".encode("cp932"))
    r = reader_for(p).read(p)
    assert [c.text_raw for c in r.clues if c.kind == "ROW"] == ["WT-1,間仕切"]
    assert ("文字コード", {"encoding": "cp932", "tried_first": "utf-8-sig"}) in r.notes


def test_text_reader_paragraphs_and_sentences(tmp_path):
    from btruth.readers import reader_for

    p = tmp_path / "minutes.txt"
    p.write_text("第3回打合せ\n\nWT-1 の間仕切は PB 二重張りとする。WT-2 の遮音性能は次回確認。\n\n以上\n", encoding="utf-8")
    r = reader_for(p).read(p)
    paras = [c for c in r.clues if c.kind == "PARAGRAPH"]
    sents = [c for c in r.clues if c.kind == "SENTENCE"]
    assert [c.text_raw for c in paras] == ["第3回打合せ", "WT-1 の間仕切は PB 二重張りとする。WT-2 の遮音性能は次回確認。", "以上"]
    assert [c.text_raw for c in sents if r.clues[c.parent_index] is paras[1]] == [
        "WT-1 の間仕切は PB 二重張りとする。", "WT-2 の遮音性能は次回確認。"]
    assert paras[1].format_extra["line_start"] == 3


def test_geometry_round_trips_through_json():
    """B-1 / B-14: the value stored is exactly the value read (JSON keeps the shortest exact repr)."""
    v = 1234.56789012345
    assert json.loads(json.dumps(v)) == v
