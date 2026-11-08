"""The understanding screen (理解の確認の画面; CONCEPT B-4, design 3-7 第3段): one HTML file.

What it shows, and why:
  * the clues of every drawing version as an SVG (lines, circles, texts) — the ground truth (B-1);
  * every proposed element with its status (提案中 / 承認済み / 却下 / 保留 / はじかれた), its kind, name,
    confidence and reason; clicking an element lights up the clues that are its evidence (B-3: the AI
    shows *why* it read what it read, on the original lines);
  * the open issues (要確認), the rejected proposals with the rule's reason (v2 Q52), and the clues no
    interpretation uses yet (読み残し; B-3).
The person looks at this screen and approves in the terminal (G-1). The screen writes nothing and
offers no button that could confirm anything. The file is recorded in `generation` (M-1).
"""
from __future__ import annotations

import html
from pathlib import Path

from btruth.common import dumps, loads, now_iso, sha256_of
from btruth.display import claim_text, frame_note, frame_of_element, frame_of_version, shift_facts
from btruth.effective import (effective_name, effective_value, item_status, open_issues, proposed_kind_of, proposed_value,
                              room_area_m2, room_perimeter_m, is_approved_element)
from btruth.project import ProjectFolder
from btruth.report import UNREAD_SQL
from btruth.store import Store


def _svg_items(store: Store, version_id: str) -> tuple[list[dict], list[float] | None]:
    uf = store.scalar("select unit_factor from source_version where id=?", version_id) or 1.0
    items, xs, ys = [], [], []
    for c in store.all("select id, kind, layer_raw, geometry_json, text_raw, style_json, generated_from from clue "
                       "where source_version_id=? and parent_clue_id is null and kind <> 'BLOCK_DEF' order by seq", version_id):
        g = loads(c["geometry_json"]) or {}
        st = loads(c["style_json"]) or {}
        it = {"id": c["id"], "kind": c["kind"], "layer": c["layer_raw"] or "", "text": c["text_raw"] or "",
              "generated": bool(c["generated_from"])}
        try:
            if c["kind"] == "LINE":
                it["points"] = [[g["start"][0] * uf, g["start"][1] * uf], [g["end"][0] * uf, g["end"][1] * uf]]
            elif c["kind"] in ("LWPOLYLINE", "POLYLINE"):
                it["points"] = [[p[0] * uf, p[1] * uf] for p in g.get("points") or []]
                it["closed"] = bool(g.get("closed"))
            elif c["kind"] in ("CIRCLE", "ARC"):
                it["center"] = [g["center"][0] * uf, g["center"][1] * uf]
                it["radius"] = g["radius"] * uf
            elif c["kind"] in ("TEXT", "MTEXT", "INSERT"):
                it["insert"] = [g["insert"][0] * uf, g["insert"][1] * uf]
                it["height"] = (st.get("height") or 300) * uf
            elif c["kind"] == "POINT":
                it["insert"] = [g["location"][0] * uf, g["location"][1] * uf]
            else:
                continue
        except (KeyError, IndexError, TypeError):
            continue
        for p in it.get("points") or ([it["insert"]] if "insert" in it else []) or ([it["center"]] if "center" in it else []):
            xs.append(p[0]); ys.append(p[1])
        if "center" in it:
            xs += [it["center"][0] - it["radius"], it["center"][0] + it["radius"]]
            ys += [it["center"][1] - it["radius"], it["center"][1] + it["radius"]]
        items.append(it)
    bbox = [min(xs), min(ys), max(xs), max(ys)] if xs else None
    return items, bbox


def build_show(store: Store, project: ProjectFolder) -> dict:
    proj = store.one("select id, name from project")
    data = {"project": {"id": proj["id"], "name": proj["name"], "folder": str(project.folder)}, "generated_at": now_iso(),
            "drawings": [], "elements": [], "issues": [], "rejected": [], "unread": []}
    for v in store.all("select v.id, v.seq, v.file_name, s.name as source_name from source_version v join source s on s.id=v.source_id "
                       "where v.format in ('dxf','jww') order by s.name, v.seq"):
        items, bbox = _svg_items(store, v["id"])
        unread = [r["id"] for r in store.all(UNREAD_SQL, v["id"]) if r["generated_from"] is None]
        data["drawings"].append({"id": v["id"], "label": f"{v['source_name']}@{v['seq']} {v['file_name']}", "clues": items,
                                 "bbox": bbox, "unread": unread})
        data["unread"].append({"version": f"{v['source_name']}@{v['seq']}", "count": len(unread), "clue_ids": unread})
        data.setdefault("frames", []).append(frame_of_version(store, v["id"]))
    for item in store.all("select i.*, p.summary, a.name as agent from interpretation_item i join interpretation p on p.id=i.interpretation_id "
                          "join agent a on a.id=p.agent_id where i.kind='要素を作る' order by i.rowid"):
        eid = item["element_id"]
        status = item_status(store, item["id"])
        evidence = [e["clue_id"] for e in store.all("select clue_id from interpretation_evidence where item_id=? and clue_id is not null", item["id"])]
        for c in store.all("select id from claim where subject_id=? and interpretation_id=?", eid, item["interpretation_id"]):
            evidence += [e["clue_id"] for e in store.all("select clue_id from claim_evidence where claim_id=?", c["id"])]
        claims = []
        for c in store.all("select attribute, value_json, mode, confidence, source_version_id from claim where subject_id=? order by rowid", eid):
            # shown in the frame of the grid labels of the version it was read from; stored values unchanged
            claims.append({"attribute": c["attribute"], "value": claim_text(store, c["value_json"], c["source_version_id"]),
                           "mode": c["mode"], "confidence": c["confidence"]})
        kind = proposed_kind_of(store, eid)
        entry = {"id": eid, "item_id": item["id"], "kind": kind, "name": effective_name(store, project, eid) or _pname(store, eid),
                 "status": status, "confidence": item["confidence"], "reason": item["reason"], "rule_reason": item["rule_check_reason"],
                 "evidence": sorted(set(evidence)), "claims": claims, "agent": item["agent"], "interpretation": item["interpretation_id"]}
        if kind == "部屋" and is_approved_element(store, eid):
            entry["area_m2"] = room_area_m2(store, project, eid)
            entry["perimeter_m"] = room_perimeter_m(store, project, eid)
        data["elements"].append(entry)
        if status == "はじかれた":
            data["rejected"].append(entry)
    for r in store.all("select i.*, p.summary from interpretation_item i join interpretation p on p.id=i.interpretation_id "
                       "where i.kind <> '要素を作る' and i.rule_check_status='はじかれた' order by i.rowid"):
        data["rejected"].append({"id": r["relation_id"] or r["claim_id"] or r["assumption_id"] or r["id"], "item_id": r["id"],
                                 "kind": r["kind"], "name": "", "status": "はじかれた", "reason": r["reason"],
                                 "rule_reason": r["rule_check_reason"], "evidence": [], "claims": []})
    for i in open_issues(store, project):
        subjects = [{"id": s, "kind": proposed_kind_of(store, s), "name": effective_name(store, project, s) or _pname(store, s)}
                    for s in i["subject_ids"]]
        evidence = []
        for s in i["subject_ids"]:
            for e in store.all("select e.clue_id from interpretation_evidence e join interpretation_item it on it.id=e.item_id "
                               "where it.element_id=? and e.clue_id is not null", s):
                evidence.append(e["clue_id"])
        data["issues"].append({"id": i["id"], "kind": i["kind"], "severity": i["severity"], "subjects": subjects,
                               "facts": shift_facts(i["facts"], next((f for f in (frame_of_element(store, x) for x in i["subject_ids"]) if f), None)),
                               "options": [o["label"] for o in i["options"]], "held": i["held"],
                               "evidence": sorted(set(evidence))})
    return data


def _pname(store, eid):
    for a in ("名前", "室名", "室番号", "符号"):
        v = proposed_value(store, eid, a)
        if v not in (None, ""):
            return str(v)
    return ""


STATUS_CLASS = {"承認済み": "ok", "既定": "ok", "提案中": "pending", "保留": "pending", "却下": "rejected", "はじかれた": "rejected"}

CSS = """
body{font-family:sans-serif;font-size:14px;margin:0;display:flex;height:100vh}
#left{flex:1;overflow:auto;padding:8px;border-right:1px solid #ccc}
#right{width:46%;overflow:auto;padding:8px}
svg{background:#fafafa;border:1px solid #ddd;width:100%;height:auto}
.clue{stroke:#333;stroke-width:1;fill:none;vector-effect:non-scaling-stroke}
text.clue{fill:#333;stroke:none}
.clue.gen{stroke:#aaa}
.clue.unread{stroke:#c60}
text.clue.unread{fill:#c60}
.clue.hl{stroke:#e00;stroke-width:3;fill:none}
text.clue.hl{fill:#e00}
.el{cursor:pointer;padding:3px 6px;border-bottom:1px solid #eee}
.el:hover,.el.sel{background:#fff3c4}
.el .st{display:inline-block;min-width:5em;font-size:12px;padding:0 4px;border-radius:3px;margin-right:4px}
.ok{background:#d6f5d6}.pending{background:#eee}.rejected{background:#f8d0d0}
.id{color:#888;font-family:monospace;font-size:11px}
table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:2px 6px;font-size:12px}
h2{font-size:15px;margin:12px 0 4px}
.note{color:#666;font-size:12px}
"""

JS = """
function hl(ids){
  document.querySelectorAll('.clue.hl').forEach(function(e){e.classList.remove('hl')});
  document.querySelectorAll('.el.sel').forEach(function(e){e.classList.remove('sel')});
  (ids||[]).forEach(function(id){var e=document.getElementById('c-'+id); if(e){e.classList.add('hl')}});
}
document.querySelectorAll('[data-evidence]').forEach(function(row){
  row.addEventListener('click', function(){hl(row.dataset.evidence.split(' ').filter(Boolean)); row.classList.add('sel')});
});
"""


def _svg(d: dict) -> str:
    e = html.escape
    if not d["bbox"]:
        return "<p class=note>図形の手掛かりがない</p>"
    x0, y0, x1, y1 = d["bbox"]
    pad = max((x1 - x0), (y1 - y0)) * 0.03 + 1
    w, h = (x1 - x0) + 2 * pad, (y1 - y0) + 2 * pad
    unread = set(d["unread"])

    def X(x):
        return f"{x - x0 + pad:.3f}"

    def Y(y):                      # drawing y goes up; SVG y goes down
        return f"{y1 - y + pad:.3f}"

    out = [f'<svg viewBox="0 0 {w:.3f} {h:.3f}" xmlns="http://www.w3.org/2000/svg">']
    for c in d["clues"]:
        cls = "clue" + (" gen" if c["generated"] else "") + (" unread" if c["id"] in unread else "")
        title = f"<title>{e(c['kind'])} {e(c['layer'])} {e(c['text'])}</title>"
        cid = f'id="c-{c["id"]}"'
        if "points" in c and len(c["points"]) >= 2:
            pts = " ".join(f"{X(p[0])},{Y(p[1])}" for p in c["points"])
            tag = "polygon" if c.get("closed") else "polyline"
            out.append(f'<{tag} {cid} class="{cls}" points="{pts}">{title}</{tag}>')
        elif "center" in c:
            out.append(f'<circle {cid} class="{cls}" cx="{X(c["center"][0])}" cy="{Y(c["center"][1])}" r="{c["radius"]:.3f}">{title}</circle>')
        elif "insert" in c:
            size = c.get("height") or (w * 0.01)
            label = c["text"] or ("▣" if c["kind"] == "INSERT" else "·")
            out.append(f'<text {cid} class="{cls}" x="{X(c["insert"][0])}" y="{Y(c["insert"][1])}" font-size="{size:.3f}">{e(label)}{title}</text>')
    out.append("</svg>")
    return "\n".join(out)


def render_show(data: dict) -> str:
    e = html.escape
    p = data["project"]
    parts = ["<!DOCTYPE html>", '<html lang="ja"><head><meta charset="utf-8">',
             f"<title>{e(p['name'])} — 理解の確認</title>", f"<style>{CSS}</style></head><body>",
             '<div id="left">', f"<h1 style='font-size:17px'>{e(p['name'])} — 理解の確認の画面</h1>",
             f"<p class=note>作成 {e(data['generated_at'])}。要素をクリックすると、根拠の手掛かりが赤く光る。"
             "橙は、まだどの解釈にも使われていない手掛かり（読み残し）。この画面は何も書き換えない。承認・判断は端末のコマンドで行う。</p>",
             f"<p class=note>{e(frame_note(data.get('frames') or []))}</p>"]
    for d in data["drawings"]:
        parts.append(f"<h2>{e(d['label'])}（手掛かり {len(d['clues'])}、読み残し {len(d['unread'])}）</h2>")
        parts.append(_svg(d))
    parts.append("</div><div id=\"right\">")
    parts.append(f"<h2>要素（{len(data['elements'])}）</h2>")
    for el in data["elements"]:
        cls = STATUS_CLASS.get(el["status"], "pending")
        extra = ""
        if el.get("area_m2") is not None:
            extra = f" 面積 {el['area_m2']:.2f} ㎡ 周長 {el['perimeter_m']:.3f} m"
        conf = f" 確かさ {el['confidence']:.2f}" if el.get("confidence") is not None else ""
        parts.append(f'<div class="el" data-evidence="{" ".join(el["evidence"])}"><span class="st {cls}">{e(el["status"])}</span>'
                     f'<b>{e(el["kind"] or "？")}</b> {e(el["name"] or "")}{e(extra)}{e(conf)} <span class=id>{e(el["id"])}</span>'
                     f'<div class=note>{e(el["reason"] or "")}</div></div>')
    parts.append(f"<h2>要確認（開いているもの {len(data['issues'])}）</h2>")
    if not data["issues"]:
        parts.append("<p class=note>なし</p>")
    for i in data["issues"]:
        subs = "、".join(f"{e(s['kind'] or '')} {e(s['name'] or '')} <span class=id>{e(s['id'])}</span>" for s in i["subjects"])
        parts.append(f'<div class="el" data-evidence="{" ".join(i["evidence"])}"><b>{e(i["kind"])}</b> [{e(i["severity"])}]'
                     f'{" （保留中）" if i["held"] else ""} {subs}<div class=note>選択肢: {e(" / ".join(i["options"]))}</div>'
                     f'<div class=note>{e(dumps(i["facts"])[:300])}</div><span class=id>要確認 {e(i["id"])}</span></div>')
    parts.append(f"<h2>はじかれた提案（{len(data['rejected'])}）</h2>")
    if not data["rejected"]:
        parts.append("<p class=note>なし</p>")
    for r in data["rejected"]:
        parts.append(f'<div class="el" data-evidence="{" ".join(r["evidence"])}"><span class="st rejected">はじかれた</span>'
                     f'{e(r["kind"] or "")} {e(r["name"] or "")} <span class=id>{e(str(r["id"]))}</span>'
                     f'<div class=note>{e(r["rule_reason"] or "")}</div></div>')
    parts.append("<h2>読み残し</h2>")
    for u in data["unread"]:
        parts.append(f'<div class="el" data-evidence="{" ".join(u["clue_ids"])}">{e(u["version"])}: {u["count"]} 件（クリックで光る）</div>')
    parts.append(f"</div><script>{JS}</script></body></html>")
    return "\n".join(parts)


def write_show(store: Store, project: ProjectFolder, out_path: Path, recorded_by: str = "理解の確認の画面") -> Path:
    data = build_show(store, project)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_show(data), encoding="utf-8")
    store.insert("generation", recorded_by, kind="理解の確認の画面", path=str(out_path), sha256=sha256_of(out_path),
                 as_of_json=dumps({"versions": [d["id"] for d in data["drawings"]], "generated_at": data["generated_at"]}),
                 marker_json=dumps({"kind": "理解の確認の画面", "format": "html"}))
    store.commit()
    return out_path
