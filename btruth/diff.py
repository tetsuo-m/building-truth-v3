"""The difference report of an identity run (design 3-7 第4段, H-1; CONCEPT B-7, A-2).

It reads the vessel only and writes the text or HTML file, recorded in `generation` (M-1). What it shows:
the frame, the mesh numbers, the count per verdict (一致・移動・追加・消えた・判断できない・意味が変わった,
分割・統合), what was handled automatically and what was handed to the person, the moves waiting for the batch
approval with their size, the recheck marks and the issues of the run.
"""
from __future__ import annotations

import html
from pathlib import Path

from btruth.common import dumps, loads, now_iso, sha256_of
from btruth.effective import effective_name, item_status, proposed_kind_of
from btruth.project import ProjectFolder
from btruth.store import Store

VERDICTS = ("一致", "移動", "追加", "消えた", "判断できない", "意味が変わった")


def _version_name(store: Store, vid: str) -> str:
    r = store.one("select s.name, v.seq, v.file_name from source_version v join source s on s.id=v.source_id where v.id=?", vid)
    return f"{r['name']}@{r['seq']}（{r['file_name']}）" if r else vid


def build_diff(store: Store, project: ProjectFolder, run_id: str) -> dict:
    run = store.one("select * from identity_run where id=?", run_id)
    counts = loads(run["counts_json"]) or {}
    mesh = loads(run["mesh_json"]) or {}
    links = []
    for l in store.all("select * from identity_link where run_id=? order by rowid", run_id):
        eid = l["element_id"]
        facts = loads(l["facts_json"]) or {}
        item = store.one("select id from interpretation_item where interpretation_id=? and element_id=?", run["interpretation_id"], eid)
        links.append({"element_id": eid, "kind": proposed_kind_of(store, eid) or "？",
                      "name": effective_name(store, project, eid) or "", "verdict": l["verdict"], "reason": l["reason"] or "",
                      "move_mm": facts.get("移動量_mm"), "item_id": item["id"] if item else None,
                      "item_status": item_status(store, item["id"]) if item else None,
                      "candidates": loads(l["candidates_json"]), "basis": loads(l["basis_json"]) or {}})
    marks = [dict(m) for m in store.all("select id, review_id, reason, detail_json from recheck_mark where caused_by_id=? order by rowid",
                                        run_id)]
    issues = [{"id": i["id"], "kind": i["kind"], "severity": i["severity"], "subjects": loads(i["subject_ids_json"]) or []}
              for i in store.all("select * from issue where identity_run_id=? order by rowid", run_id)]
    impact = [dict(r) for r in store.all("select element_id, reason, action, depth from impact where run_id=? order by rowid", run_id)]
    return {"run_id": run_id, "generated_at": now_iso(), "base": _version_name(store, run["base_source_version_id"]),
            "new": _version_name(store, run["new_source_version_id"]), "frame": loads(run["frame_json"]) or {},
            "mesh": {k: mesh.get(k) for k in ("nodes_base", "nodes_new", "edges_base", "edges_new")} |
                    {"anchors": len(mesh.get("anchors") or []), "moved": len(mesh.get("moved") or []),
                     "edges_split": len(mesh.get("edges_split") or []),
                     "faces": [f.get("verdict") for f in mesh.get("faces") or []]},
            "counts": counts, "links": links, "recheck_marks": marks, "issues": issues, "impact": impact}


def render_text(d: dict) -> str:
    c = d["counts"]
    lines = [f"差分のレポート  同定 {d['run_id']}", f"  前の版 {d['base']}", f"  新しい版 {d['new']}",
             f"  座標の枠: {'揃えた' if d['frame'].get('aligned') else '揃えていない'}  {d['frame'].get('note', '')}",
             f"  節点の網の目: 節点 {d['mesh']['nodes_base']}→{d['mesh']['nodes_new']}  辺 {d['mesh']['edges_base']}→{d['mesh']['edges_new']}"
             f"  足場 {d['mesh']['anchors']}  動いた節点 {d['mesh']['moved']}  分かれた辺 {d['mesh']['edges_split']}"
             f"  面 {'・'.join(x or '？' for x in d['mesh']['faces'])}", "",
             "数:"]
    lines.append("  " + "  ".join(f"{v} {c.get(v, 0)}" for v in VERDICTS) + f"  分割 {c.get('分割', 0)}  統合 {c.get('統合', 0)}")
    lines.append(f"  自動で処理した数 {c.get('自動で処理した数', 0)}  人に渡した数 {c.get('人に渡した数', 0)}"
                 f"  追加の候補の手掛かり {c.get('追加の候補の手掛かり', 0)}  再確認の印 {len(d['recheck_marks'])}  要確認 {len(d['issues'])}")
    for v in VERDICTS:
        rows = [l for l in d["links"] if l["verdict"] == v]
        if not rows or v == "一致":
            continue
        lines += ["", f"{v}:"]
        for l in rows:
            mv = f"  移動 {l['move_mm']:.1f} mm" if l["move_mm"] is not None else ""
            st = f"  [{l['item_status']}] item {l['item_id']}" if l["item_id"] else ""
            lines.append(f"  {l['kind']} {l['name']} {l['element_id']}{mv}  {l['reason']}{st}")
    same = [l for l in d["links"] if l["verdict"] == "一致"]
    if same:
        lines += ["", f"一致: {len(same)} 件（" + "、".join(sorted({l['kind'] for l in same})) + "）"]
    if d["recheck_marks"]:
        lines += ["", "再確認の印（判断の根拠が変わった。保つ／変える／取り消す を人が選ぶ）:"]
        lines += [f"  印 {m['id']}  判断 {m['review_id']}  {m['reason']}" for m in d["recheck_marks"]]
    if d["issues"]:
        lines += ["", "要確認:"]
        lines += [f"  {i['kind']} [{i['severity']}]  {i['id']}  対象 {len(i['subjects'])}" for i in d["issues"]]
    return "\n".join(lines)


def render_html(d: dict) -> str:
    e = html.escape
    def mm(v):
        return "" if v is None else f"{v:.1f}"

    rows = "".join(f"<tr class='v-{e(l['verdict'])}'><td>{e(l['verdict'])}</td><td>{e(l['kind'])}</td><td>{e(l['name'])}</td>"
                   f"<td><code>{e(l['element_id'])}</code></td><td>{mm(l['move_mm'])}</td>"
                   f"<td>{e(l['reason'])}</td><td>{e(l['item_status'] or '')}</td></tr>" for l in d["links"])
    return ("<!DOCTYPE html><html lang='ja'><head><meta charset='utf-8'><title>差分のレポート</title>"
            "<style>body{font-family:sans-serif;margin:1.5rem}table{border-collapse:collapse}td,th{border:1px solid #ccc;"
            "padding:.2rem .5rem}.v-移動{background:#fff6d6}.v-判断できない,.v-消えた,.v-意味が変わった{background:#fde2e2}</style>"
            f"</head><body><h1>差分のレポート</h1><pre>{e(render_text(d))}</pre>"
            "<table><tr><th>結果</th><th>種類</th><th>名前</th><th>要素</th><th>移動 mm</th><th>理由</th><th>承認</th></tr>"
            f"{rows}</table></body></html>")


def write_diff(store: Store, project: ProjectFolder, run_id: str, out: Path, html: bool = False,
               recorded_by: str = "差分のレポート") -> Path:
    d = build_diff(store, project, run_id)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(d) if html else render_text(d), encoding="utf-8")
    store.insert("generation", recorded_by, kind="差分のレポート", as_of_json=dumps({"identity_run_id": run_id, "at": d["generated_at"]}),
                 path=str(out), sha256=sha256_of(out), marker_json=dumps({"format": "html" if html else "text"}))
    store.commit()
    return out
