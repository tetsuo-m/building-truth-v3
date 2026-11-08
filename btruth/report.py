"""Report: the clues of every version and the ground for showing what is not yet read (B-3, H-1).

"Not yet read" (読み残し) here means: an observed, top-level clue that no interpretation_evidence,
claim_evidence or assumption_evidence points at. In stage 2 nothing is interpreted, so every observed
clue is unread; stage 3 fills the evidence tables and the count goes down. Generated clues (H-2) are
shown apart and never counted as unread. The written file is recorded in `generation` (M-1).
"""
from __future__ import annotations

import html
from collections import Counter
from pathlib import Path

from btruth.common import dumps, loads, now_iso, sha256_of
from btruth.project import ProjectFolder
from btruth.store import Store

UNREAD_SQL = """
select c.id, c.seq, c.kind, c.layer_raw, c.geometry_json, c.text_raw, c.generated_from
from clue c
where c.source_version_id = ? and c.parent_clue_id is null and c.kind <> 'BLOCK_DEF'
  and not exists (select 1 from interpretation_evidence e where e.clue_id = c.id)
  and not exists (select 1 from claim_evidence e where e.clue_id = c.id)
  and not exists (select 1 from assumption_evidence e where e.clue_id = c.id)
order by c.seq
"""


def _summary(kind: str, geometry: dict | None) -> str:
    g = geometry or {}
    try:
        if kind == "LINE":
            return f"({g['start'][0]}, {g['start'][1]}) - ({g['end'][0]}, {g['end'][1]})"
        if kind == "CIRCLE":
            return f"中心 ({g['center'][0]}, {g['center'][1]}) r={g['radius']}"
        if kind == "ARC":
            return f"中心 ({g['center'][0]}, {g['center'][1]}) r={g['radius']} {g['start_angle']}°→{g['end_angle']}°"
        if kind in ("TEXT", "MTEXT", "INSERT"):
            return f"({g['insert'][0]}, {g['insert'][1]})"
        if kind in ("LWPOLYLINE", "POLYLINE"):
            return f"頂点 {len(g.get('points') or [])}" + ("（閉）" if g.get("closed") else "")
        if kind == "POINT":
            return f"({g['location'][0]}, {g['location'][1]})"
    except (KeyError, IndexError, TypeError):
        pass
    return ""


def build_report(store: Store, project: ProjectFolder) -> dict:
    proj = store.one("select id, name, schema_version from project")
    report = {"project": {"id": proj["id"], "name": proj["name"], "schema_version": proj["schema_version"],
                          "folder": str(project.folder)},
              "generated_at": now_iso(), "versions": []}
    rows = store.all("""
        select v.id, v.seq, v.file_name, v.format, v.imported_at, v.unit_factor, v.sha256, s.name as source_name, s.kind as source_kind
        from source_version v join source s on s.id = v.source_id order by s.name, v.seq""")
    for v in rows:
        clues = store.all("select id, seq, kind, layer_raw, geometry_json, text_raw, generated_from from clue "
                          "where source_version_id=? and parent_clue_id is null and kind <> 'BLOCK_DEF' order by seq", v["id"])
        block_defs = store.scalar("select count(*) from clue where source_version_id=? and kind='BLOCK_DEF'", v["id"])
        unread_ids = {r["id"] for r in store.all(UNREAD_SQL, v["id"]) if r["generated_from"] is None}
        counts: Counter = Counter()
        items = []
        generated = 0
        for c in clues:
            if c["generated_from"]:
                generated += 1
            else:
                counts[(c["layer_raw"] or "", c["kind"])] += 1
            items.append({"id": c["id"], "seq": c["seq"], "kind": c["kind"], "layer": c["layer_raw"] or "",
                          "summary": _summary(c["kind"], loads(c["geometry_json"])), "text": c["text_raw"] or "",
                          "generated": bool(c["generated_from"]), "unread": c["id"] in unread_ids})
        block_children = store.scalar("select count(*) from clue where source_version_id=? and parent_clue_id is not null", v["id"])
        attrs = {r["attribute"]: r["value"] for r in store.all(
            "select attribute, value from source_attribute where source_id=(select source_id from source_version where id=?) order by rowid",
            v["id"])}
        logs = [{"kind": r["kind"], "detail": loads(r["detail_json"])} for r in
                store.all("select kind, detail_json from intake_log where source_version_id=? order by rowid", v["id"])]
        report["versions"].append({
            "id": v["id"], "source_name": v["source_name"], "source_kind": v["source_kind"], "attributes": attrs,
            "seq": v["seq"], "file_name": v["file_name"], "format": v["format"], "imported_at": v["imported_at"],
            "unit_factor": v["unit_factor"], "sha256": v["sha256"], "counts": dict(counts),
            "clue_total": sum(counts.values()), "generated": generated, "block_defs": block_defs,
            "block_children": block_children,
            "unread": len(unread_ids), "clues": items, "intake_log": logs})
    return report


def render_text(report: dict) -> str:
    p = report["project"]
    out = [f"# {p['name']} — 手掛かりの一覧（器の版 {p['schema_version']}、{report['generated_at']}）", ""]
    if not report["versions"]:
        out.append("取り込んだ版はまだない。")
    for v in report["versions"]:
        attrs = "、".join(f"{k}={val}" for k, val in v["attributes"].items())
        out.append(f"## {v['source_name']}@{v['seq']}  {v['file_name']}  区分={v['source_kind'] or '（未指定）'}"
                   + (f"  {attrs}" if attrs else ""))
        out.append(f"   取り込み {v['imported_at']}  形式 {v['format']}  単位 ×{v['unit_factor']} mm  版の ID {v['id']}")
        out.append(f"   観測の手掛かり {v['clue_total']}  生成物として外した {v['generated']}  ブロックの定義 {v['block_defs']}"
                   f"（中の図形 {v['block_children']}）  読み残し {v['unread']}（まだどの解釈にも使われていない）")
        for (layer, kind), n in sorted(v["counts"].items()):
            out.append(f"     {layer:<24} {kind:<12} {n}")
        out.append("   手掛かり:")
        for c in v["clues"]:
            flag = "生成" if c["generated"] else ("未読" if c["unread"] else "既読")
            text = f"  「{c['text']}」" if c["text"] else ""
            out.append(f"     {c['seq']:>4} {flag} {c['kind']:<12} {c['layer']:<24} {c['summary']}{text}")
        for log in v["intake_log"]:
            out.append(f"   記録 {log['kind']}: {dumps(log['detail'])[:200]}")
        out.append("")
    return "\n".join(out)


def render_html(report: dict) -> str:
    p = report["project"]
    e = html.escape
    parts = ["<!DOCTYPE html>", "<html lang=\"ja\"><head><meta charset=\"utf-8\">",
             f"<title>{e(p['name'])} — 手掛かりの一覧</title>",
             "<style>body{font-family:sans-serif;font-size:14px}table{border-collapse:collapse}"
             "td,th{border:1px solid #ccc;padding:2px 6px}tr.gen{color:#888}tr.unread td.flag{color:#b00}</style>",
             "</head><body>", f"<h1>{e(p['name'])} — 手掛かりの一覧</h1>",
             f"<p>器の版 {p['schema_version']}、作成 {e(report['generated_at'])}</p>"]
    for v in report["versions"]:
        parts.append(f"<h2>{e(v['source_name'])}@{v['seq']} {e(v['file_name'])} （区分 {e(v['source_kind'] or '未指定')}）</h2>")
        parts.append(f"<p>観測の手掛かり {v['clue_total']}、生成物として外した {v['generated']}、ブロックの定義 {v['block_defs']}（中の図形 {v['block_children']}）、"
                     f"<b>読み残し {v['unread']}</b>（まだどの解釈にも使われていない）</p>")
        parts.append("<table><tr><th>#</th><th>状態</th><th>種類</th><th>レイヤ</th><th>形</th><th>文字</th></tr>")
        for c in v["clues"]:
            cls = "gen" if c["generated"] else ("unread" if c["unread"] else "read")
            flag = "生成" if c["generated"] else ("未読" if c["unread"] else "既読")
            parts.append(f"<tr class=\"{cls}\"><td>{c['seq']}</td><td class=\"flag\">{flag}</td><td>{e(c['kind'])}</td>"
                         f"<td>{e(c['layer'])}</td><td>{e(c['summary'])}</td><td>{e(c['text'])}</td></tr>")
        parts.append("</table>")
    parts.append("</body></html>")
    return "\n".join(parts)


def write_report(store: Store, project: ProjectFolder, out_path: Path, html_out: bool = False,
                 recorded_by: str = "レポートのコマンド", **kw) -> Path:
    if "html" in kw:                       # keyword used by the tests / CLI
        html_out = kw["html"]
    report = build_report(store, project)
    text = render_html(report) if html_out else render_text(report)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    store.insert("generation", recorded_by, kind="レポート", path=str(out_path), sha256=sha256_of(out_path),
                 as_of_json=dumps({"versions": [v["id"] for v in report["versions"]], "generated_at": report["generated_at"]}),
                 marker_json=dumps({"kind": "レポート", "format": "html" if html_out else "text"}))
    store.commit()
    return out_path
