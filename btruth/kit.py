"""The kit for a blind measurement of the AI's reading (BRIEF_v3_step4 §1-2, docs/MEASURE.md; CONCEPT D-9).

The stage-3 measurement was taken in the session that had just written the fixed interpretation, so the
reading knew the answer. A measurement has to be taken by a new Claude Code session that cannot see the fixed
interpretation, the expected-value documents or the test fixtures. The kit is a folder that holds only:
  * clues/<source>@<seq>.json — the observed clues of each version, as `btruth clues` prints them;
  * .claude/skills/read-drawing/SKILL.md — the instructions (its sha256 goes into the proposal);
  * .claude/hooks/*.py and .claude/settings.json — the guards (F-12: a folder without them has no guards);
  * TASK.md — what to do: read the clues, write proposal.json, stop. No btruth, no database, no answers.
The person opens a new Claude Code session in that folder, then registers proposal.json and measures it in a
measurement project of their own (docs/MEASURE.md). Nothing here approves anything.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from btruth.common import loads, sha256_of
from btruth.compare import roles_for
from btruth.project import ProjectFolder
from btruth.store import Store
from btruth.tables import effective_rows

REPO = Path(__file__).resolve().parents[1]
GUARDS = [".claude/hooks/guard_confirm.py", ".claude/hooks/guard_paths.py", ".claude/hooks/guard_concept.py",
          ".claude/settings.json", ".claude/skills/read-drawing/SKILL.md"]

TASK = """# 図面を読む（測定のための作業）

この場所には、図面と表の手掛かり（`clues/` の JSON）と、読み方の手順書（`.claude/skills/read-drawing/SKILL.md`）
だけがあります。手順書に従って、建物の要素として読み、提案の JSON を一つ書いてください。

1. まず手順書の 0 節のとおり、守りが効いているかを確かめる。
2. `clues/` の JSON を読む。`ref`（`平面図@1#13` の形）で根拠を指す。手順書の `btruth clues` の出力と同じ形。
3. 手順書の 3 節の形で、`proposal.json` をこのフォルダに書く。`agent.name` は `Claude Code`、
   `agent.instructions_sha256` は {sha}。
4. 書いたら止まる。登録・承認・測定は人が行う（btruth はここにはない）。承認のコマンドは打たない。

手掛かりの版：{versions}
"""


def write_kit(store: Store, project: ProjectFolder, version_refs: list[str], dest: Path) -> Path:
    from btruth.cli import _resolve_version
    dest = Path(dest)
    if dest.exists() and any(dest.iterdir()):
        raise FileExistsError(f"測定の場所はからにしておく: {dest}")
    (dest / "clues").mkdir(parents=True, exist_ok=True)
    layer_rows = effective_rows(store, project, "layer_roles")
    names = []
    for ref in version_refs:
        vid = _resolve_version(store, ref)
        v = store.one("select v.*, s.name as source_name, s.kind as source_kind from source_version v join source s on s.id=v.source_id "
                      "where v.id=?", vid)
        clues = []
        for c in store.all("select id, seq, kind, layer_raw, geometry_json, text_raw, style_json, format_extra_json from clue "
                           "where source_version_id=? and parent_clue_id is null and generated_from is null and kind <> 'BLOCK_DEF' "
                           "order by seq", vid):
            clues.append({"ref": f"{v['source_name']}@{v['seq']}#{c['seq']}", "seq": c["seq"], "kind": c["kind"],
                          "layer": c["layer_raw"], "roles": list(roles_for(c["layer_raw"], c["kind"], layer_rows)),
                          "geometry": loads(c["geometry_json"]), "text": c["text_raw"], "style": loads(c["style_json"])})
        attrs = {r["attribute"]: r["value"] for r in store.all(
            "select attribute, value from source_attribute where source_id=? order by rowid", v["source_id"])}
        name = f"{v['source_name']}@{v['seq']}"
        names.append(name)
        (dest / "clues" / f"{name}.json").write_text(json.dumps(
            {"version": {"source_name": v["source_name"], "seq": v["seq"], "file_name": v["file_name"],
                         "source_kind": v["source_kind"], "attributes": attrs, "unit_factor": v["unit_factor"]},
             "clues": clues}, ensure_ascii=False, indent=1), encoding="utf-8")
    for rel in GUARDS:
        src = REPO / rel
        if src.exists():
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest / rel)
    sha = sha256_of(REPO / ".claude/skills/read-drawing/SKILL.md")
    (dest / "TASK.md").write_text(TASK.format(sha=sha, versions="、".join(names)), encoding="utf-8")
    return dest
