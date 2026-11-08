"""The fictional samples of stage 5 (BRIEF_v3_step5 §4): a plan with a door, a door schedule, minutes.

All of it is fictional. The plan is samples/step2/step2.dxf (Jw_cad's coordinates, origin (210000000, 148500000))
with a door on the partition: an INSERT (seq 24) and its tag "AD-1" (seq 25). The first 23 entities are those of
step2.dxf, so the clue numbers of a reading of step2 stay valid. Run from the repository root:

    python samples/step5/make_samples.py
"""
from __future__ import annotations

from pathlib import Path

import ezdxf
from ezdxf import recover

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
OX, OY = 210000000.0, 148500000.0


def main() -> None:
    doc, _ = recover.readfile(ROOT / "samples" / "step2" / "step2.dxf")
    if "DOOR_S" not in doc.blocks:
        blk = doc.blocks.new(name="DOOR_S")
        blk.add_line((0, 0), (0, -800))
        blk.add_arc((0, 0), 800, 270, 360)
    if "_0-6_DOOR" not in doc.layers:
        doc.layers.add("_0-6_DOOR")
    msp = doc.modelspace()
    msp.add_blockref("DOOR_S", (OX + 2300, OY + 1900), dxfattribs={"layer": "_0-6_DOOR"})
    msp.add_text("AD-1", dxfattribs={"layer": "_0-6_DOOR", "height": 200}).set_placement((OX + 2450, OY + 1500))
    doc.saveas(HERE / "plan.dxf")
    (HERE / "door_schedule.csv").write_text("code,type,width,height,spec\nAD-1,片開き扉,800,2000,木製フラッシュ\n", encoding="utf-8")
    (HERE / "minutes.md").write_text("# 第4回 打合せ（架空）\n\nAD-1 の幅を 900 とする。WT-3 の外壁の断熱は次回までに検討する。\n",
                                     encoding="utf-8")
    print("wrote", HERE / "plan.dxf", HERE / "door_schedule.csv", HERE / "minutes.md")


if __name__ == "__main__":
    main()
