"""Writes the fixed interpretations (提案の JSON) for samples/step1 and samples/step2 (design 3-5-1 (1)).

The fixtures are *fictional* readings of fictional drawings. They are what a correct reading of the
sample would propose; the tests register them, approve them inside a temporary database and check
the expected values of samples/*/expected.md. Run this file to regenerate the JSON after a change:

    python tests/fixtures/make_fixtures.py

Clue references are "<source>@<seq>#<clue seq>"; the tests import the samples with these source
names: 平面図 (the DXF), 壁種表 (wall_types.csv), 仕上表 (finish_schedule.csv). The clue seq is the
order of the entities in the DXF (see btruth.readers.dxf_reader); it is the same in step1.dxf and
step2.dxf for the first 21 entities (the partition of step2 is seq 22 / 23).
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent

AGENT = {"name": "固定の解釈（テスト）", "kind": "固定の解釈", "model": None, "version": "fixtures/1",
         "instructions_sha256": None}

# clue seq in step1.dxf / step2.dxf (the first 21 are the same)
GRID = {"X1": (1, 3, 2), "X2": (4, 6, 5), "Y1": (7, 9, 8), "Y2": (10, 12, 11)}     # (line, text, circle)
RB = {"S": 13, "E": 15, "N": 17, "W": 19}       # ROOM_BOUNDARY lines of the outer rectangle
WC = {"S": 14, "E": 16, "N": 18, "W": 20}       # WALL_CENTER lines of the outer rectangle
ROOM_TEXT = 21
RB_PART, WC_PART = 22, 23                       # step2 only


def clue(seq: int, role: str = "主の根拠", reason: str | None = None, source: str = "平面図@1") -> dict:
    d = {"clue": f"{source}#{seq}", "role": role}
    if reason:
        d["reason"] = reason
    return d


def build(step: int) -> dict:
    x0, y0 = (0.0, 0.0) if step == 1 else (210000000.0, 148500000.0)   # step2 keeps Jw_cad's coordinates (B-1)

    def P(x, y):
        return [x0 + x, y0 + y]

    elements, relations = [], []
    storey = {"find": {"kind": "階", "name": "1階"}}
    outside = {"find": {"kind": "外部"}}

    # --- 通り芯 (IfcGridAxis): the label is the key (B-11), the line and the circle are evidence
    grid_lines = {"X1": (P(0, -1500), P(0, 5500)), "X2": (P(6000, -1500), P(6000, 5500)),
                  "Y1": (P(-1500, 0), P(7500, 0)), "Y2": (P(-1500, 4000), P(7500, 4000))}
    for label, (line, text, circle) in GRID.items():
        elements.append({
            "ref": f"grid_{label}", "kind": "通り芯", "confidence": 0.98,
            "reason": f"GRID レイヤの線と、その端の符号の文字「{label}」（丸で囲む）",
            "evidence": [clue(line, "主の根拠", "通り芯の線"), clue(text, "主の根拠", "符号の文字"),
                         clue(circle, "補助", "符号を囲む丸")],
            "claims": [
                {"attribute": "符号", "value": label, "confidence": 0.98, "evidence": [clue(text)]},
                {"attribute": "線分", "value": list(grid_lines[label]), "unit": "mm", "confidence": 0.98,
                 "evidence": [clue(line)]},
            ]})

    # --- 壁種 WT-3 (type, from the wall-type table)
    elements.append({
        "ref": "wt3", "kind": "壁種", "confidence": 0.95, "reason": "壁種表の行 WT-3",
        "evidence": [clue(1, "主の根拠", "壁種表の行", source="壁種表@1")],
        "claims": [
            {"attribute": "符号", "value": "WT-3", "confidence": 0.95, "evidence": [clue(1, source="壁種表@1")]},
            {"attribute": "構成", "value": {"core": "ALC", "core_thickness_mm": 100, "board_thickness_mm": 0,
                                          "boards_per_side": 0, "total_thickness_mm": 100, "role": "外壁"},
             "confidence": 0.95, "evidence": [clue(1, source="壁種表@1")]},
            {"attribute": "厚さ", "value": 100, "unit": "mm", "confidence": 0.95, "evidence": [clue(1, source="壁種表@1")]},
        ]})

    # --- outer walls (the centre line gives the position; the extent comes from the boundaries, C-2e)
    wall_lines = {"S": (P(0, 0), P(6000, 0)), "E": (P(6000, 0), P(6000, 4000)),
                  "N": (P(6000, 4000), P(0, 4000)), "W": (P(0, 4000), P(0, 0))}
    for side in ("S", "E", "N", "W"):
        elements.append({
            "ref": f"wall_{side}", "kind": "壁", "confidence": 0.9,
            "reason": "壁芯線（WALL_CENTER）が部屋割り線と重なり、両側が部屋と外部。範囲は境界の区間で決める（C-2e）",
            "evidence": [clue(WC[side], "主の根拠", "壁芯線"), clue(RB[side], "補助", "部屋割り線（範囲の根拠）")],
            "claims": [
                {"attribute": "芯線", "value": list(wall_lines[side]), "unit": "mm", "confidence": 0.9,
                 "evidence": [clue(WC[side])]},
            ]})
        relations.append({"ref": f"wall_{side}_in_storey", "kind": "含む", "from": f"wall_{side}", "to": storey,
                          "reason": "一階建ての 1階（E-2）", "confidence": 0.95})
        relations.append({"ref": f"wall_{side}_type", "kind": "型である", "from": f"wall_{side}", "to": "wt3",
                          "reason": "図面に壁種の記号がなく、壁種表に WT-3 の一行だけ（確かさは低め。確定は人）",
                          "confidence": 0.6, "evidence": [clue(1, "補助", "壁種表に一行だけ", source="壁種表@1")]})

    def room(ref: str, corners: list[tuple[float, float]], rb_seqs: list[int], wc_seqs: list[int],
             partners: list[str], name_claims: list[dict], name_evidence: list[dict], reason: str,
             extra_evidence: list[dict] | None = None):
        """A room as a counter-clockwise ring of corners; one boundary per side (C-2c)."""
        elements.append({"ref": ref, "kind": "部屋", "confidence": 0.9, "reason": reason,
                         "evidence": [clue(s, "主の根拠", "部屋割り線（閉じた輪郭）") for s in rb_seqs] + name_evidence
                         + (extra_evidence or []),
                         "claims": name_claims})
        relations.append({"ref": f"{ref}_in_storey", "kind": "集める", "from": ref, "to": storey,
                          "reason": "1階の部屋", "confidence": 0.95})
        n = len(corners)
        for i in range(n):
            a, b = corners[i], corners[(i + 1) % n]
            bref = f"{ref}_b{i + 1}"
            elements.append({
                "ref": bref, "kind": "空間の境界", "confidence": 0.9,
                "reason": "部屋の輪郭の角と角のあいだの一直線の区間（決定 Q13）。壁芯線が重なるので物理的",
                "evidence": [clue(rb_seqs[i], "主の根拠", "部屋割り線"), clue(wc_seqs[i], "補助", "壁芯線が重なる")],
                "claims": [
                    {"attribute": "線分", "value": [P(*a), P(*b)], "unit": "mm", "confidence": 0.9,
                     "evidence": [clue(rb_seqs[i])]},
                    {"attribute": "境界の種類", "value": "物理的", "confidence": 0.85,
                     "evidence": [clue(wc_seqs[i], "主の根拠", "壁芯線が重なる")]},
                ]})
            relations.append({"ref": f"{bref}_bounds", "kind": "区切る", "from": bref, "to": ref,
                              "role": {"順": i + 1, "向き": "反時計回り"}, "confidence": 0.9})
            relations.append({"ref": f"{bref}_partner", "kind": "境界の相手", "from": bref, "to": partners[i],
                              "reason": "壁芯線が境界の線分に重なる", "confidence": 0.9})

    def outside_boundary(ref: str, a, b, rb_seq: int, wc_seq: int, wall_ref: str, facing: list[str]):
        elements.append({
            "ref": ref, "kind": "空間の境界", "confidence": 0.85,
            "reason": "外壁の外側。外部の側の境界（決定 Q17）",
            "evidence": [clue(rb_seq, "主の根拠", "部屋割り線"), clue(wc_seq, "補助", "壁芯線")],
            "claims": [
                {"attribute": "線分", "value": [P(*a), P(*b)], "unit": "mm", "confidence": 0.85,
                 "evidence": [clue(rb_seq)]},
                {"attribute": "境界の種類", "value": "物理的", "confidence": 0.85, "evidence": [clue(wc_seq)]},
            ]})
        relations.append({"ref": f"{ref}_bounds", "kind": "区切る", "from": ref, "to": outside, "confidence": 0.85})
        relations.append({"ref": f"{ref}_partner", "kind": "境界の相手", "from": ref, "to": wall_ref, "confidence": 0.85})
        for other in facing:
            relations.append({"ref": f"{ref}_faces_{other}", "kind": "向かい合う", "from": ref, "to": other,
                              "reason": "同じ部屋割り線の両側", "confidence": 0.85})

    ceiling = {"attribute": "天井高", "value": 2700, "unit": "mm", "confidence": 0.9,
               "evidence": [clue(1, "主の根拠", "仕上表の行 101", source="仕上表@1"),
                            clue(ROOM_TEXT, "補助", "室番号 101 が一致")]}
    name_101 = [
        {"attribute": "室番号", "value": "101", "confidence": 0.95, "evidence": [clue(ROOM_TEXT)]},
        {"attribute": "室名", "value": "事務室", "confidence": 0.95, "evidence": [clue(ROOM_TEXT)]},
        ceiling,
    ]
    if step == 1:
        room("room_101", [(0, 0), (6000, 0), (6000, 4000), (0, 4000)],
             [RB["S"], RB["E"], RB["N"], RB["W"]], [WC["S"], WC["E"], WC["N"], WC["W"]],
             ["wall_S", "wall_E", "wall_N", "wall_W"], name_101,
             [clue(ROOM_TEXT, "主の根拠", "室名の文字が輪郭の内側にある")],
             "四本の部屋割り線が閉じた輪郭を作り、室名の文字が内側にある")
        outside_boundary("out_S", (6000, 0), (0, 0), RB["S"], WC["S"], "wall_S", ["room_101_b1"])
        outside_boundary("out_E", (6000, 4000), (6000, 0), RB["E"], WC["E"], "wall_E", ["room_101_b2"])
        outside_boundary("out_N", (0, 4000), (6000, 4000), RB["N"], WC["N"], "wall_N", ["room_101_b3"])
        outside_boundary("out_W", (0, 0), (0, 4000), RB["W"], WC["W"], "wall_W", ["room_101_b4"])
        summary = "step1：一部屋の平面図を、壁種表・仕上表とともに読んだ固定の解釈"
    else:
        # the partition (x = 2300) splits the rectangle; the left room has no name text (expected.md)
        elements.append({
            "ref": "wall_A", "kind": "壁", "confidence": 0.9,
            "reason": "間仕切の壁芯線。範囲は左右の部屋の境界の区間（C-2e）",
            "evidence": [clue(WC_PART, "主の根拠", "壁芯線"), clue(RB_PART, "補助", "部屋割り線")],
            "claims": [{"attribute": "芯線", "value": [P(2300, 0), P(2300, 4000)], "unit": "mm", "confidence": 0.9,
                        "evidence": [clue(WC_PART)]}]})
        relations.append({"ref": "wall_A_in_storey", "kind": "含む", "from": "wall_A", "to": storey, "confidence": 0.95})
        relations.append({"ref": "wall_A_type", "kind": "型である", "from": "wall_A", "to": "wt3", "confidence": 0.6,
                          "reason": "図面に壁種の記号がなく、壁種表に WT-3 の一行だけ",
                          "evidence": [clue(1, "補助", source="壁種表@1")]})
        room("room_left", [(0, 0), (2300, 0), (2300, 4000), (0, 4000)],
             [RB["S"], RB_PART, RB["N"], RB["W"]], [WC["S"], WC_PART, WC["N"], WC["W"]],
             ["wall_S", "wall_A", "wall_N", "wall_W"], [],
             [], "左の閉じた輪郭。室名の文字がないので名前の言い分は出さない（推測しない）")
        room("room_101", [(2300, 0), (6000, 0), (6000, 4000), (2300, 4000)],
             [RB["S"], RB["E"], RB["N"], RB_PART], [WC["S"], WC["E"], WC["N"], WC_PART],
             ["wall_S", "wall_E", "wall_N", "wall_A"], name_101,
             [clue(ROOM_TEXT, "主の根拠", "室名の文字が右の輪郭の内側にある")],
             "右の閉じた輪郭。室名の文字 (3000,2000) が内側にある")
        relations.append({"ref": "left_E_faces_right_W", "kind": "向かい合う", "from": "room_left_b2", "to": "room_101_b4",
                          "reason": "間仕切の両側", "confidence": 0.9})
        outside_boundary("out_S", (6000, 0), (0, 0), RB["S"], WC["S"], "wall_S", ["room_left_b1", "room_101_b1"])
        outside_boundary("out_E", (6000, 4000), (6000, 0), RB["E"], WC["E"], "wall_E", ["room_101_b2"])
        outside_boundary("out_N", (0, 4000), (6000, 4000), RB["N"], WC["N"], "wall_N", ["room_left_b3", "room_101_b3"])
        outside_boundary("out_W", (0, 0), (0, 4000), RB["W"], WC["W"], "wall_W", ["room_left_b4"])
        summary = "step2：間仕切で二つに分かれた平面図を、壁種表・仕上表とともに読んだ固定の解釈"

    return {
        "agent": AGENT,
        "source_versions": ["平面図@1", "壁種表@1", "仕上表@1"],
        "summary": summary,
        "assumptions": [{
            "ref": "a_follow", "level": 1, "kind": "壁芯は部屋割り線に従う", "value": "従う", "confidence": 0.9,
            "reason": "レイヤの役割（WALL_CENTER と ROOM_BOUNDARY）が同じ位置に重なっている",
            "evidence": [clue(WC["S"], "主の根拠"), clue(RB["S"], "主の根拠")],
        }],
        "elements": elements,
        "relations": relations,
        "claims": [],
        "unreadable": [],
    }


def main() -> None:
    for step in (1, 2):
        path = HERE / f"step{step}_fixed.json"
        path.write_text(json.dumps(build(step), ensure_ascii=False, indent=1), encoding="utf-8")
        print("wrote", path)


if __name__ == "__main__":
    main()
