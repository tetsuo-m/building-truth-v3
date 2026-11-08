"""Claude Code's reading of samples/step5 (BRIEF_v3_step5 §4: the database the person tries holds the AI's reading,
not a fixture). The plan is step2.dxf plus a door, so the reading of step2 (make_claude_proposals.read(2)) is reused
for the first 23 clues, and the door, its opening, the door type of the schedule and the two sentences of the
minutes are read here. All data is fictional. Run from the repository root:

    python samples/ai_run/make_claude_step5.py

The door's kind (片開き扉) is left to the door schedule (its primary source, C-5); the opening is the partner of
its own part of the two boundaries of the partition (C-2c). What I read: the INSERT DOOR_S (平面図@1#24) sits on the partition (x = 2300) at y = 1900, its tag "AD-1"
(#25) beside it; the block's leaf is 800 long. The partition runs from (2300, 4000) to (2300, 0), so the opening
starts 2100 from the wall's start and is 800 wide. The door schedule has one row AD-1 (片開き扉, W800, H2000).
The minutes say "AD-1 の幅を 900 とする。" (a decision) and "WT-3 の外壁の断熱は次回までに検討する。" (not decided).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from make_claude_proposals import OUTSIDE, STOREY, ev, read  # noqa: E402


def main() -> None:
    p = read(2)
    p["agent"]["version"] = "2026-11-08 第5段"
    p["source_versions"] = ["平面図@1", "壁種表@1", "仕上表@1", "建具表@1", "議事録4@1"]
    p["summary"] = "Claude Code の読み（第5段の試し）：二室、壁 5、間仕切に扉 AD-1（開口 800）、建具表 AD-1、議事録の決定と未決"
    p["elements"] += [
        {"ref": "opening_P", "kind": "開口", "confidence": 0.85,
         "reason": "間仕切の上の扉のブロック。開き幅 800。壁の始点 (2300,4000) から 2100 の所から 800",
         "evidence": [ev("平面図@1#24", "主の根拠", "扉のブロック")],
         "claims": [{"attribute": "位置", "value": 2100, "unit": "mm", "confidence": 0.85, "evidence": [ev("平面図@1#24")]},
                    {"attribute": "幅", "value": 800, "unit": "mm", "confidence": 0.8, "evidence": [ev("平面図@1#24")]}]},
        {"ref": "door_P", "kind": "建具", "confidence": 0.85, "reason": "扉のブロックと符号の文字 AD-1",
         "evidence": [ev("平面図@1#24"), ev("平面図@1#25", "主の根拠", "符号")],
         "claims": [{"attribute": "符号", "value": "AD-1", "confidence": 0.95, "evidence": [ev("平面図@1#25")]},
                   ]},   # 建具の種類 comes from the door schedule (its primary source; C-5), not from the block's shape
        {"ref": "type_AD1", "kind": "建具の型", "confidence": 0.95, "reason": "建具表の行 AD-1",
         "evidence": [ev("建具表@1#1")],
         "claims": [{"attribute": "符号", "value": "AD-1", "confidence": 0.95, "evidence": [ev("建具表@1#1")]},
                    {"attribute": "建具の種類", "value": "片開き扉", "confidence": 0.95, "evidence": [ev("建具表@1#1")]},
                    {"attribute": "幅", "value": 800, "unit": "mm", "confidence": 0.95, "evidence": [ev("建具表@1#1")]},
                    {"attribute": "高さ", "value": 2000, "unit": "mm", "confidence": 0.95, "evidence": [ev("建具表@1#1")]},
                    {"attribute": "仕様", "value": "木製フラッシュ", "confidence": 0.95, "evidence": [ev("建具表@1#1")]}]},
    ]
    p["relations"] += [
        {"ref": "opening_P_voids", "kind": "くり抜く", "from": "opening_P", "to": "wall_P", "role": {"位置": 2100}, "confidence": 0.85},
        {"ref": "door_P_fills", "kind": "ふさぐ", "from": "door_P", "to": "opening_P", "confidence": 0.85},
        # the opening is the partner of its own part of both boundaries of the partition (C-2c: 壁の区間と開口の区間)
        {"ref": "left_E_opening", "kind": "境界の相手", "from": "room_left_side2", "to": "opening_P", "confidence": 0.85},
        {"ref": "right_W_opening", "kind": "境界の相手", "from": "room_101_side4", "to": "opening_P", "confidence": 0.85},
        {"ref": "door_P_storey", "kind": "含む", "from": "door_P", "to": STOREY, "confidence": 0.95},
        {"ref": "door_P_type", "kind": "型である", "from": "door_P", "to": "type_AD1", "confidence": 0.9,
         "reason": "図面の符号 AD-1 が建具表の行と同じ", "evidence": [ev("建具表@1#1", "主の根拠")]},
    ]
    p["claims"] += [
        {"subject": "type_AD1", "attribute": "幅", "value": 900, "unit": "mm", "statement_kind": "決定", "source": "議事録4@1",
         "confidence": 0.9, "reason": "「〜とする」は決定", "evidence": [ev("議事録4@1#4", "主の根拠", "AD-1 の幅を 900 とする。")]},
        {"subject": "type_WT3", "attribute": "断熱", "value": "次回までに検討する", "statement_kind": "未決", "source": "議事録4@1",
         "confidence": 0.9, "reason": "「検討する」は未決（格を持たない）",
         "evidence": [ev("議事録4@1#5", "主の根拠", "WT-3 の外壁の断熱は次回までに検討する。")]},
    ]
    out = HERE / "step5_claude.json"
    out.write_text(json.dumps(p, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    main()
