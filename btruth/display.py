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
    if not frames:          # nothing shown comes from a drawing with grid labels
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


def fmt(value, frame: dict | None = None) -> str:
    """A value as a person reads it: numbers plain, lists of points as coordinates, dicts as 「名 値・名 値」."""
    value = shift(value, frame) if frame else value
    if isinstance(value, dict):
        return "・".join(f"{k} {fmt(v)}" for k, v in value.items())
    if isinstance(value, list):
        if value and all(_is_point(x) for x in value):
            return "〜".join("(" + ", ".join(f"{c:g}" for c in x[:2]) + ")" for x in value)
        return "、".join(fmt(x) for x in value)
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def element_label(store: Store, project, eid: str) -> str:
    from btruth.effective import effective_name, effective_value, proposed_kind_of, proposed_value
    kind = proposed_kind_of(store, eid) or "要素"
    name = effective_name(store, project, eid)
    if not name:
        tag = effective_value(store, project, eid, "符号", through_type=False)
        name = tag.value if tag.present else proposed_value(store, eid, "符号")
    return f"{kind}{(' ' + str(name)) if name else ''}"


def issue_sentence(store: Store, project, i: dict, frame) -> str:
    """What differs, in one or two plain sentences (第6段の依頼書 §1)."""
    f = i.get("facts") or {}
    k = i["kind"]
    subj = element_label(store, project, i["subject_ids"][0]) if i["subject_ids"] else "要素"
    attr = f.get("属性") or (i.get("basis") or {}).get("属性") or ""
    if k == "決定が未反映":
        hi, lo = f.get("正とみなす", {}), f.get("従", {})
        return (f"{subj} の「{attr}」が食い違っている。{hi.get('出どころ')}（格 {hi.get('格')}）は {fmt(hi.get('値'))}、"
                f"{lo.get('出どころ')}（格 {lo.get('格')}）は {fmt(lo.get('値'))}。格の高い {hi.get('出どころ')} を正とみなす。確定は人が選ぶ。")
    if k == "決定が未反映（人の判断と食い違う）":
        return (f"{subj} の「{attr}」：人の判断（格 {f.get('判断の格')}）は {fmt(f.get('判断'))}、{f.get('出どころ')}"
                f"（格 {f.get('議事録の格')}）の決定は {fmt(f.get('議事録'))}。黙って書き換えない。")
    if k == "言い分の食い違い（主と従）":
        why = f"（{f['理由']}）" if f.get("理由") else ""
        return (f"{subj} の「{attr}」：基準の {f.get('基準')} は {fmt(f.get('主の値'), frame)}、{f.get('従')} は "
                f"{fmt(f.get('従の値'), frame)}。{why}")
    if k == "設計図と施工図の食い違い":
        design = "、".join(f"{d['出どころ']} {fmt(d['値'])}" for d in f.get("設計図", []))
        site = f.get("施工図", {})
        return f"{subj} の「{attr}」：設計図は {design}、施工図 {site.get('出どころ')} は {fmt(site.get('値'))}。どちらが正かは決めない。"
    if k == "議事録の未決":
        return f"{f.get('出どころ')} に、{subj} の「{attr}」について「{fmt(f.get('文'))}」とある（未決。格を持たない）。"
    if k == "言い分の食い違い（型と実物）":
        if attr == "層の例外":
            return f"{subj} の注記は {fmt(f.get('実物の注記'))}、型は {fmt(f.get('型'))}。注記を黙って勝たせない。"
        return f"{subj} の「{attr}」が、型と実物で食い違っている。"
    if k == "名前がない空間":
        return f"名前のない閉じた空間（{subj}）がある。黙って名前を付けない。"
    if k == "壁と境界のずれ":
        return f"{subj} と、その境界が {fmt(f.get('ずれ_mm'))} mm ずれている（壁芯は部屋割り線に従う、の前提）。"
    if k == "建具表にない符号":
        return f"{subj}：符号 {f.get('符号')} が建具表にない。建具の種類は AI の提案のまま、承認まで数えない。"
    if k == "柱の偏心が上限を超える":
        return f"{subj} が通り芯の交点から {fmt(f.get('偏心_mm'))} mm 離れている（上限 {fmt(f.get('上限_mm'))} mm）。"
    if k == "向かい合う境界の種類の食い違い":
        return f"同じ線の両側で、境界の種類（物理的／仮想）が {fmt(f.get('区間'), frame)} で食い違っている。"
    if k == "壁が途中で終わる":
        return f"{subj} の {fmt(f.get('uncovered_intervals_mm'))}（境界の始点からの mm）に、壁も開口もない。"
    if k == "壁が境界の外に出ている":
        return f"{subj} が、境界の区間から {fmt(round(f.get('outside_mm', 0), 1))} mm 外に出ている。"
    if k == "移動の承認待ち":
        return f"移動（意味の変更なし）の新しい位置が {len(f.get('item_ids') or [])} 件、まとめての承認を待っている。"
    return str(f.get("note") or "（詳しくは --detail）")


def issue_lines(store: Store, project, issues: list[dict], folder: str | None = None, detail: bool = False) -> list[str]:
    """`btruth issues`: one block per issue, in plain sentences, with the command to type (第6段の依頼書 §1).
    The issue's id is the one to type; the elements are shown for reference. JSON only with `detail`."""
    lines, frames = [], []
    folder = folder or "<物件のフォルダ>"
    for n, i in enumerate(issues, start=1):
        frame = next((f for f in (frame_of_element(store, s) for s in i["subject_ids"]) if f), None)
        frames.append(frame)
        held = "・保留中" if i.get("held") else ""
        lines.append(f"■ {i['kind']}［{i['severity']}{held}］")
        lines.append(f"  要確認の ID：{i['id']}")
        if i["subject_ids"]:
            lines.append("  対象：" + "、".join(f"{element_label(store, project, s)}（要素 {s} ）" for s in i["subject_ids"]))
        lines.append("  何が：" + issue_sentence(store, project, i, frame))
        if i.get("proposal") and i["proposal"].get("text"):
            lines.append(f"  修正案：{i['proposal']['text']}")
        if i["options"]:
            lines.append("  選べること：")
            for o in i["options"]:
                lines.append(f"    ［{o['code']}］ {o['label']}")
            first = i["options"][0]["code"]
            lines.append(f"  打つ例：.venv\\Scripts\\python -m btruth choose {folder} --issue {i['id'][:8]} --option {first} --reason \"…\"")
        if detail:
            lines.append(f"  事実（--detail）：{json.dumps(shift_facts(i['facts'], frame), ensure_ascii=False)}")
            if i.get("proposal"):
                lines.append(f"  修正案（--detail）：{json.dumps(i['proposal'], ensure_ascii=False)}")
        lines.append("")
    if any(frames):
        lines.append(frame_note(frames))
    return lines
