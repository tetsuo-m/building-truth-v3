"""Claude Code's own reading of samples/step1 and samples/step2 (BRIEF step3 §3-7: AI の読みの測定).

Written by Claude Code on 2026-11-08 after reading the clues with `btruth clues` and following
.claude/skills/read-drawing/SKILL.md. It is *not* derived from tests/fixtures/make_fixtures.py; it is the
agent's reading, kept as a script so the proposal JSON can be regenerated without typing errors.
All data is fictional (the samples are fictional). Run from the repository root:

    python samples/ai_run/make_claude_proposals.py

What I read (step1.dxf, 21 clues): four GRID lines with a label text and a circle each (X1 at x=0, X2 at
x=6000, Y1 at y=0, Y2 at y=4000); four ROOM_BOUNDARY lines closing a 6000 x 4000 rectangle; four
WALL_CENTER lines exactly on those boundaries; one ROOM_NAME text "101 事務室" at (3000, 2000), inside.
The wall-type table has one row WT-3 (ALC 100); the finish schedule has one row for room 101 (ceiling 2700).
step2.dxf adds a ROOM_BOUNDARY line and a WALL_CENTER line at x = 2300 from y = 4000 down to y = 0, so the
rectangle splits into a left room (0..2300, no name text) and a right room (2300..6000, the text at x = 3000
is inside it). Jw_cad's export puts the origin at (210000000, 148500000); I keep its coordinates (B-1).
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent
STOREY = {"find": {"kind": "階", "name": "1階"}}
OUTSIDE = {"find": {"kind": "外部"}}


def ev(ref, role="主の根拠", reason=None):
    d = {"clue": ref, "role": role}
    if reason:
        d["reason"] = reason
    return d


def read(step: int) -> dict:
    ox, oy = (0.0, 0.0) if step == 1 else (210000000.0, 148500000.0)

    def P(x, y):
        return [ox + x, oy + y]

    plan = "平面図@1"
    elements, relations, unreadable = [], [], []

    # 通り芯: label text is the key; the line is the axis; the circle only frames the label (補助)
    axes = {"X1": (1, 2, 3, P(0, -1500), P(0, 5500)), "X2": (4, 5, 6, P(6000, -1500), P(6000, 5500)),
            "Y1": (7, 8, 9, P(-1500, 0), P(7500, 0)), "Y2": (10, 11, 12, P(-1500, 4000), P(7500, 4000))}
    for label, (line, circle, text, a, b) in axes.items():
        elements.append({"ref": f"axis_{label}", "kind": "通り芯", "confidence": 0.97,
                         "reason": f"GRID の線の端に符号「{label}」の文字と丸がある",
                         "evidence": [ev(f"{plan}#{line}", "主の根拠", "通り芯の線"), ev(f"{plan}#{text}", "主の根拠", "符号"),
                                      ev(f"{plan}#{circle}", "補助", "符号を囲む丸")],
                         "claims": [{"attribute": "符号", "value": label, "confidence": 0.97, "evidence": [ev(f"{plan}#{text}")]},
                                    {"attribute": "線分", "value": [a, b], "unit": "mm", "confidence": 0.97,
                                     "evidence": [ev(f"{plan}#{line}")]}]})

    # 壁種 WT-3 from the wall-type table (a type, E-5)
    elements.append({"ref": "type_WT3", "kind": "壁種", "confidence": 0.95, "reason": "壁種表の唯一の行",
                     "evidence": [ev("壁種表@1#1")],
                     "claims": [{"attribute": "符号", "value": "WT-3", "confidence": 0.95, "evidence": [ev("壁種表@1#1")]},
                                {"attribute": "厚さ", "value": 100, "unit": "mm", "confidence": 0.95, "evidence": [ev("壁種表@1#1")]},
                                {"attribute": "構成", "value": {"core": "ALC", "core_thickness_mm": 100, "total_thickness_mm": 100,
                                                              "boards_per_side": 0, "role": "外壁"},
                                 "confidence": 0.9, "evidence": [ev("壁種表@1#1")]}]})

    # outer walls: WALL_CENTER lines coincide with the boundary lines; the extent is the physical boundary (C-2e)
    outer = {"S": (14, 13, P(0, 0), P(6000, 0)), "E": (16, 15, P(6000, 0), P(6000, 4000)),
             "N": (18, 17, P(6000, 4000), P(0, 4000)), "W": (20, 19, P(0, 4000), P(0, 0))}
    for side, (wc, rb, a, b) in outer.items():
        elements.append({"ref": f"wall_{side}", "kind": "壁", "confidence": 0.9,
                         "reason": "WALL_CENTER の線が部屋割り線と同じ位置。片側が部屋、片側が外部",
                         "evidence": [ev(f"{plan}#{wc}", "主の根拠", "壁芯線（位置）"), ev(f"{plan}#{rb}", "補助", "部屋割り線（範囲）")],
                         "claims": [{"attribute": "芯線", "value": [a, b], "unit": "mm", "confidence": 0.9, "evidence": [ev(f"{plan}#{wc}")]}]})
        relations.append({"ref": f"wall_{side}_storey", "kind": "含む", "from": f"wall_{side}", "to": STOREY, "confidence": 0.95})
        relations.append({"ref": f"wall_{side}_type", "kind": "型である", "from": f"wall_{side}", "to": "type_WT3", "confidence": 0.5,
                          "reason": "図面に壁種の記号がない。壁種表に WT-3 の一行だけなので、低い確かさで提案する（確定は人）",
                          "evidence": [ev("壁種表@1#1", "補助", "表に一行だけ")]})

    def room(ref, corners, rb_seqs, wc_seqs, partners, claims, evidence, reason):
        elements.append({"ref": ref, "kind": "部屋", "confidence": 0.9, "reason": reason,
                         "evidence": [ev(f"{plan}#{s}", "主の根拠", "部屋割り線") for s in rb_seqs] + evidence, "claims": claims})
        relations.append({"ref": f"{ref}_storey", "kind": "集める", "from": ref, "to": STOREY, "confidence": 0.95})
        for i in range(4):
            a, b = corners[i], corners[(i + 1) % 4]
            bref = f"{ref}_side{i + 1}"
            elements.append({"ref": bref, "kind": "空間の境界", "confidence": 0.9,
                             "reason": "部屋の輪郭を反時計回りにたどった一辺。壁芯線が重なるので物理的",
                             "evidence": [ev(f"{plan}#{rb_seqs[i]}", "主の根拠", "部屋割り線"), ev(f"{plan}#{wc_seqs[i]}", "補助", "壁芯線")],
                             "claims": [{"attribute": "線分", "value": [P(*a), P(*b)], "unit": "mm", "confidence": 0.9,
                                         "evidence": [ev(f"{plan}#{rb_seqs[i]}")]},
                                        {"attribute": "境界の種類", "value": "物理的", "confidence": 0.85,
                                         "evidence": [ev(f"{plan}#{wc_seqs[i]}", "主の根拠", "壁芯線が重なる")]}]})
            relations.append({"ref": f"{bref}_bounds", "kind": "区切る", "from": bref, "to": ref, "role": {"順": i + 1, "向き": "反時計回り"},
                              "confidence": 0.9})
            relations.append({"ref": f"{bref}_wall", "kind": "境界の相手", "from": bref, "to": partners[i], "confidence": 0.9,
                              "reason": "壁芯線が境界の線分と同じ位置"})

    def outside_side(ref, a, b, rb, wc, wall, faces):
        elements.append({"ref": ref, "kind": "空間の境界", "confidence": 0.85, "reason": "外壁の外側の境界（外部の側）",
                         "evidence": [ev(f"{plan}#{rb}", "主の根拠"), ev(f"{plan}#{wc}", "補助")],
                         "claims": [{"attribute": "線分", "value": [P(*a), P(*b)], "unit": "mm", "confidence": 0.85, "evidence": [ev(f"{plan}#{rb}")]},
                                    {"attribute": "境界の種類", "value": "物理的", "confidence": 0.85, "evidence": [ev(f"{plan}#{wc}")]}]})
        relations.append({"ref": f"{ref}_bounds", "kind": "区切る", "from": ref, "to": OUTSIDE, "confidence": 0.85})
        relations.append({"ref": f"{ref}_wall", "kind": "境界の相手", "from": ref, "to": wall, "confidence": 0.85})
        for f in faces:
            relations.append({"ref": f"{ref}_vs_{f}", "kind": "向かい合う", "from": ref, "to": f, "confidence": 0.85})

    ceiling = {"attribute": "天井高", "value": 2700, "unit": "mm", "confidence": 0.9,
               "evidence": [ev("仕上表@1#1", "主の根拠", "room_no 101 の行の ceiling_height_mm"), ev(f"{plan}#21", "補助", "室番号が一致")]}
    named = [{"attribute": "室番号", "value": "101", "confidence": 0.95, "evidence": [ev(f"{plan}#21")]},
             {"attribute": "室名", "value": "事務室", "confidence": 0.95, "evidence": [ev(f"{plan}#21")]}, ceiling]
    if step == 1:
        room("room_101", [(0, 0), (6000, 0), (6000, 4000), (0, 4000)], [13, 15, 17, 19], [14, 16, 18, 20],
             ["wall_S", "wall_E", "wall_N", "wall_W"], named, [ev(f"{plan}#21", "主の根拠", "室名の文字が輪郭の内側")],
             "四本の部屋割り線が一つの閉じた輪郭。室名の文字 (3000,2000) が内側")
        outside_side("out_S", (6000, 0), (0, 0), 13, 14, "wall_S", ["room_101_side1"])
        outside_side("out_E", (6000, 4000), (6000, 0), 15, 16, "wall_E", ["room_101_side2"])
        outside_side("out_N", (0, 4000), (6000, 4000), 17, 18, "wall_N", ["room_101_side3"])
        outside_side("out_W", (0, 0), (0, 4000), 19, 20, "wall_W", ["room_101_side4"])
        summary = "Claude Code の読み：一部屋（101 事務室）、外壁 4、通り芯 4、壁種 WT-3、天井高 2700"
    else:
        elements.append({"ref": "wall_P", "kind": "壁", "confidence": 0.9, "reason": "x=2300 の WALL_CENTER。両側が部屋（間仕切）",
                         "evidence": [ev(f"{plan}#23", "主の根拠", "壁芯線"), ev(f"{plan}#22", "補助", "部屋割り線")],
                         "claims": [{"attribute": "芯線", "value": [P(2300, 4000), P(2300, 0)], "unit": "mm", "confidence": 0.9,
                                     "evidence": [ev(f"{plan}#23")]}]})
        relations.append({"ref": "wall_P_storey", "kind": "含む", "from": "wall_P", "to": STOREY, "confidence": 0.95})
        relations.append({"ref": "wall_P_type", "kind": "型である", "from": "wall_P", "to": "type_WT3", "confidence": 0.4,
                          "reason": "間仕切なのに表の唯一の行は外壁 WT-3。確かさはさらに低い（確定は人）",
                          "evidence": [ev("壁種表@1#1", "補助")]})
        room("room_left", [(0, 0), (2300, 0), (2300, 4000), (0, 4000)], [13, 22, 17, 19], [14, 23, 18, 20],
             ["wall_S", "wall_P", "wall_N", "wall_W"], [], [],
             "左の閉じた輪郭（x 0〜2300）。室名の文字がないので名前は書かない")
        room("room_101", [(2300, 0), (6000, 0), (6000, 4000), (2300, 4000)], [13, 15, 17, 22], [14, 16, 18, 23],
             ["wall_S", "wall_E", "wall_N", "wall_P"], named, [ev(f"{plan}#21", "主の根拠", "室名の文字が右の輪郭の内側")],
             "右の閉じた輪郭（x 2300〜6000）。室名の文字 (3000,2000) が内側")
        relations.append({"ref": "partition_faces", "kind": "向かい合う", "from": "room_left_side2", "to": "room_101_side4", "confidence": 0.9})
        outside_side("out_S", (6000, 0), (0, 0), 13, 14, "wall_S", ["room_left_side1", "room_101_side1"])
        outside_side("out_E", (6000, 4000), (6000, 0), 15, 16, "wall_E", ["room_101_side2"])
        outside_side("out_N", (0, 4000), (6000, 4000), 17, 18, "wall_N", ["room_left_side3", "room_101_side3"])
        outside_side("out_W", (0, 0), (0, 4000), 19, 20, "wall_W", ["room_left_side4"])
        summary = "Claude Code の読み：間仕切で二室（左は名前なし、右は 101 事務室）、壁 5、通り芯 4、壁種 WT-3"

    return {"agent": {"name": "Claude Code", "kind": "Claude Code", "model": "claude-fable-5-1", "version": "2026-11-08",
                      "instructions_sha256": None},
            "source_versions": [plan, "壁種表@1", "仕上表@1"], "summary": summary,
            "assumptions": [{"ref": "a_center_follows", "level": 1, "kind": "壁芯は部屋割り線に従う", "value": "従う", "confidence": 0.9,
                             "reason": "WALL_CENTER と ROOM_BOUNDARY の線が、すべての辺で同じ位置にある",
                             "evidence": [ev(f"{plan}#13"), ev(f"{plan}#14")]}],
            "elements": elements, "relations": relations, "claims": [], "unreadable": unreadable}


if __name__ == "__main__":
    for step in (1, 2):
        out = HERE / f"step{step}_claude.json"
        out.write_text(json.dumps(read(step), ensure_ascii=False, indent=1), encoding="utf-8")
        print("wrote", out)
