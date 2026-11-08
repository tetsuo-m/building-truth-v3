"""Coordinates as the person sees them (the person's trial of stage 4, 2026-11-08).

A Jw_cad export puts the drawing far from the origin (210000000, 148500000). The stored values stay exactly as
read (B-1: never rounded, never shifted). What is *shown* to the person (items, the listings before y/N, diff,
show, issues) is shifted to the frame of the version's grid labels: the crossing of the smallest X and Y labels
(compare.find_origin, the same frame the version comparison and the identity run use, F-9), in mm. One line says
which frame it is (FRAME_NOTE). A version without grid labels is shown as stored, and the line says so.
"""
from __future__ import annotations

import json

from btruth.common import dumps, loads
from btruth.store import Store

_CACHE: dict[tuple[int, str], dict | None] = {}


def frame_of_version(store: Store, version_id: str | None) -> dict | None:
    """{"x", "y", "labels", "uf", "version"} or None (no grid labels, or not a drawing)."""
    if not version_id:
        return None
    key = (id(store.conn), version_id)
    if key not in _CACHE:
        from btruth.compare import _load_clues, find_origin
        rows = [dict(r) for r in store.all(
            "select l.* from layer_roles_loaded l where l.table_load_id in (select id from table_load where kind='layer_roles') "
            "order by l.rowid")]
        clues = _load_clues(store, version_id, rows)
        origin = find_origin(clues)
        name = store.one("select s.name, v.seq from source_version v join source s on s.id=v.source_id where v.id=?", version_id)
        _CACHE[key] = None if origin is None else {
            "x": origin["x"], "y": origin["y"], "labels": origin["labels"], "uf": clues[0]["uf"] if clues else 1.0,
            "version": f"{name['name']}@{name['seq']}" if name else version_id}
    return _CACHE[key]


def frame_note(frames) -> str:
    frames = [f for f in frames if f]
    if not frames:
        return "座標：ファイルの座標のまま（通り芯の符号がない版）。"
    labels = frames[0]["labels"]
    versions = "、".join(sorted({f["version"] for f in frames}))
    return (f"座標：{versions} の通り芯の符号 {labels[0]}・{labels[1]} の交点を原点にした値（mm）。"
            f"保存した値は、ファイルの座標のまま（丸めない・揃えない）。")


def _is_point(v) -> bool:
    return isinstance(v, list) and len(v) in (2, 3) and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v)


def shift(value, frame: dict | None):
    """Points ([x, y] / [x, y, z]) inside lists of points are shifted; anything else is left as it is."""
    if frame is None:
        return value
    if _is_point(value):
        return [value[0] * frame["uf"] - frame["x"], value[1] * frame["uf"] - frame["y"]] + list(value[2:])
    if isinstance(value, list) and value and all(_is_point(p) or isinstance(p, list) for p in value):
        return [shift(p, frame) for p in value]
    return value


def claim_text(store: Store, value_json: str | None, version_id: str | None) -> str:
    """The claim's value as shown: coordinates shifted to the frame of the version it was read from."""
    value = loads(value_json)
    return dumps(shift(value, frame_of_version(store, version_id)))


# facts of issues: only these keys hold absolute drawing coordinates (the rest are distances along a line)
ABSOLUTE_KEYS = ("outside_points", "壁の芯線", "candidates")


def shift_facts(facts: dict, frame: dict | None) -> dict:
    if not isinstance(facts, dict) or frame is None:
        return facts
    return {k: (shift(v, frame) if k in ABSOLUTE_KEYS else v) for k, v in facts.items()}


def frame_of_element(store: Store, element_id: str) -> dict | None:
    row = store.one("select source_version_id from claim where subject_id=? and attribute in ('線分','芯線') "
                    "and source_version_id is not null order by rowid desc limit 1", element_id)
    return frame_of_version(store, row["source_version_id"]) if row else None


def issue_lines(store: Store, project, issues: list[dict]) -> list[str]:
    """The lines of `btruth issues`, with coordinates in the grid frame and one line about the frame."""
    from btruth.effective import effective_name, proposed_kind_of
    lines, frames = [], []
    for i in issues:
        subjects = "、".join(f"{proposed_kind_of(store, s) or '要素'} 要素 {s} {effective_name(store, project, s) or ''}".rstrip()
                             for s in i["subject_ids"])
        held = "（保留中）" if i.get("held") else ""
        lines.append(f"{i['kind']} [{i['severity']}]{held}  {subjects}")
        lines.append(f"    要確認 {i['id']}  選択肢: {' / '.join(o['label'] for o in i['options'])}")
        frame = next((f for f in (frame_of_element(store, s) for s in i["subject_ids"]) if f), None)
        frames.append(frame)
        if i.get("facts"):
            lines.append(f"    事実: {json.dumps(shift_facts(i['facts'], frame), ensure_ascii=False)[:300]}")
    if any(frames):
        lines.append(frame_note(frames))
    return lines
