"""The outputs (design H-1, H-2, H-3, M-1, M-2; CONCEPT H). Nothing here writes `review`; nothing is stored but the
records of what was output (`generation`, `writeback`).

  * tables (面積表・仕上表・数量表) computed from the effective values when asked (B-10), as CSV and HTML;
    quantities follow v2 Q17–Q20 and Q31 (3-5-2): H = ceiling height + board_height_extra_mm, wall area =
    perimeter × H − openings larger than opening_min_deduct_m2, boards = ceil(area / (board width × length)
    × (1 + board_loss_rate)) per room (Q19). A room without ceiling height is not counted; the reason is listed
    (Q20, no extra issue);
  * a generated drawing: the walls' faces from the effective centre line and thickness, on BT_GEN_ layers (H-2);
  * writing back: the drawing fixes a person approved (`choose` on an option with applies_drawing_fix) are written
    into a *new* DXF made from the person's original drawing, after checking that the original's sha256 is the one
    imported (H-3). The original is never written. The new drawing is 未確認 until `confirm-drawing` (a person).
Every file is recorded in `generation` with the time of the values it was made from (as_of_json), so that the
intake recognises it (M-1).
"""
from __future__ import annotations

import csv
import html
import json
import math
from pathlib import Path

from btruth import geometry
from btruth.common import dumps, loads, now_iso, sha256_of
from btruth.effective import (_kind_of, approved_elements_by_kind, effective_name, effective_value, relations_from, relations_to,
                              room_area_m2, room_perimeter_m, boundaries_of_room, types_of)
from btruth.project import ProjectFolder
from btruth.store import Store
from btruth.tables import effective_rules

GEN_PREFIX = "BT_GEN_"
FINISH_ATTRIBUTES = ("床", "幅木", "壁", "天井", "天井高")


class WritebackRefused(Exception):
    pass


def as_of(store: Store) -> dict:
    """The time of the effective values an output was made from (M-1)."""
    return {"at": now_iso(),
            "latest_review_id": store.scalar("select id from review order by rowid desc limit 1"),
            "latest_check_run_id": store.scalar("select id from check_run order by rowid desc limit 1"),
            "versions": [r["id"] for r in store.all("select id from source_version order by rowid")]}


def _record(store: Store, kind: str, path: Path, marker: dict, recorded_by: str, extra_as_of: dict | None = None) -> str:
    a = as_of(store)
    if extra_as_of:
        a.update(extra_as_of)
    gid = store.insert("generation", recorded_by, kind=kind, as_of_json=dumps(a), path=str(path), sha256=sha256_of(path),
                       marker_json=dumps(marker))
    store.commit()
    return gid


# ====================================================================== tables
def _rooms(store: Store, project: ProjectFolder) -> list[str]:
    return approved_elements_by_kind(store, project).get("部屋", [])


def area_table(store: Store, project: ProjectFolder) -> dict:
    rows, excluded = [], []
    for room in _rooms(store, project):
        num = effective_value(store, project, room, "室番号")
        name = effective_value(store, project, room, "室名")
        nm = effective_value(store, project, room, "名前")
        row = {"要素": room, "室番号": num.value if num.present else "", "室名": (name.value if name.present else "") or
               (nm.value if nm.present else ""), "面積_m2": room_area_m2(store, project, room),
               "周長_m": room_perimeter_m(store, project, room)}
        treat = effective_value(store, project, room, "部屋として扱う")
        (excluded if treat.present and treat.value is False else rows).append(row)
    total = sum(r["面積_m2"] or 0 for r in rows)
    return {"rows": rows, "部屋として扱わない": excluded, "合計_m2": total}


def finish_table(store: Store, project: ProjectFolder) -> dict:
    rows = []
    for room in _rooms(store, project):
        row = {"要素": room, "室名": effective_name(store, project, room) or ""}
        for a in FINISH_ATTRIBUTES:
            v = effective_value(store, project, room, a)
            row[a] = v.value if v.present else ""
        rows.append(row)
    return {"rows": rows}


def deducted(area_m2: float, rules: dict) -> bool:
    """v2 Q31: an opening of at most opening_min_deduct_m2 is not deducted."""
    return area_m2 > float(rules.get("opening_min_deduct_m2", "0.5"))


def _openings_of_room(store: Store, project: ProjectFolder, room: str) -> list[str]:
    """The openings in the walls that bound the room (on the room's boundaries), each once."""
    from btruth.propose import opening_segment
    rules = effective_rules(store, project)
    gap = float(rules.get("gap_tol_mm", "50"))
    out = []
    for b in boundaries_of_room(store, project, room):
        bv = effective_value(store, project, b, "線分")
        bseg = geometry.segment(bv.value) if bv.present else None
        if bseg is None:
            continue
        for r in relations_from(store, b, "境界の相手"):
            partner = r["to_element_id"]
            candidates = [partner] if _kind_of(store, partner) == "開口" else \
                [o["from_element_id"] for o in relations_to(store, partner, "くり抜く")]
            for o in candidates:
                seg = opening_segment(store, project, o)
                if seg and geometry.overlap_on(bseg, seg, gap) and o not in out:
                    out.append(o)
    return out


def quantity_table(store: Store, project: ProjectFolder) -> dict:
    rules = effective_rules(store, project)
    extra = float(rules.get("board_height_extra_mm", "100"))
    bw, bl = float(rules.get("board_width_mm", "910")), float(rules.get("board_length_mm", "1820"))
    loss = float(rules.get("board_loss_rate", "0.10"))
    rows, uncounted = [], []
    for room in _rooms(store, project):
        treat = effective_value(store, project, room, "部屋として扱う")
        if treat.present and treat.value is False:
            uncounted.append({"要素": room, "理由": "部屋として扱わない（決定 Q11）"})
            continue
        ch = effective_value(store, project, room, "天井高")
        per = room_perimeter_m(store, project, room)
        if not ch.present:
            uncounted.append({"要素": room, "室名": effective_name(store, project, room) or "",
                              "理由": "天井高がない（仕上表と結びつかない。推測で出さない。v2 Q20）"})
            continue
        if per is None:
            uncounted.append({"要素": room, "理由": "部屋の輪郭が求まらない"})
            continue
        H = float(ch.value) + extra
        gross = per * H / 1000.0
        openings, ded, kept = [], 0.0, []
        for o in _openings_of_room(store, project, room):
            w, h = effective_value(store, project, o, "幅"), effective_value(store, project, o, "高さ")
            if not (w.present and h.present):
                kept.append({"開口": o, "理由": "幅か高さがない（差し引かない）"})
                continue
            a = float(w.value) * float(h.value) / 1_000_000.0
            if deducted(a, rules):
                ded += a
                openings.append({"開口": o, "面積_m2": a})
            else:
                kept.append({"開口": o, "面積_m2": a, "理由": f"{rules.get('opening_min_deduct_m2', '0.5')} ㎡ 以下は差し引かない（v2 Q31）"})
        net = gross - ded
        boards = math.ceil(net * 1_000_000.0 / (bw * bl) * (1.0 + loss) - 1e-9)
        rows.append({"要素": room, "室名": effective_name(store, project, room) or "", "周長_m": per, "張り上げ高さ_mm": int(H) if H.is_integer() else H,
                     "壁の面積_m2": net, "差し引いた開口_m2": round(ded, 6) + 0.0, "ボードの枚数": boards,
                     "差し引いた開口": openings, "差し引かなかった開口": kept})
    return {"rows": rows, "数えられなかったもの": uncounted,
            "規則": {"board_height_extra_mm": extra, "board_width_mm": bw, "board_length_mm": bl, "board_loss_rate": loss,
                   "opening_min_deduct_m2": float(rules.get("opening_min_deduct_m2", "0.5"))}}


def _flat_rows(rows: list[dict]) -> tuple[list[str], list[list]]:
    cols = []
    for r in rows:
        for k, v in r.items():
            if not isinstance(v, (list, dict)) and k not in cols:
                cols.append(k)
    return cols, [[r.get(c, "") for c in cols] for r in rows]


def _write(path: Path, title: str, table: dict, html_out: bool) -> None:
    rows = table["rows"]
    cols, data = _flat_rows(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not html_out:
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for d in data:
                w.writerow(["" if x is None else (f"{x:.3f}" if isinstance(x, float) else x) for x in d])
        return
    e = html.escape
    body = "".join("<tr>" + "".join(f"<td>{e('' if x is None else (f'{x:.3f}' if isinstance(x, float) else str(x)))}</td>" for x in d)
                   + "</tr>" for d in data)
    extra = []
    for k, v in table.items():
        if k == "rows":
            continue
        extra.append(f"<h2>{e(k)}</h2><pre>{e(json.dumps(v, ensure_ascii=False, indent=1))}</pre>")
    path.write_text(f"<!DOCTYPE html><html lang='ja'><head><meta charset='utf-8'><title>{e(title)}</title>"
                    "<style>body{font-family:sans-serif;margin:1.5rem}td,th{border:1px solid #ccc;padding:.2rem .5rem}"
                    "table{border-collapse:collapse}</style></head><body>"
                    f"<h1>{e(title)}</h1><p>正本の有効値から計算した（保存しない。B-10）。</p><table><tr>"
                    + "".join(f"<th>{e(c)}</th>" for c in cols) + f"</tr>{body}</table>{''.join(extra)}</body></html>",
                    encoding="utf-8")


def write_tables(store: Store, project: ProjectFolder, out_dir: Path, recorded_by: str = "表の出口") -> list[Path]:
    out_dir = Path(out_dir)
    paths = []
    for name, title, fn in (("area", "面積表", area_table), ("finishes", "仕上表", finish_table), ("quantities", "数量表", quantity_table)):
        table = fn(store, project)
        for html_out in (False, True):
            path = out_dir / f"{name}.{'html' if html_out else 'csv'}"
            _write(path, title, table, html_out)
            _record(store, "表", path, {"table": title, "format": "html" if html_out else "csv", "file_marker": "生成物（正本の出口）"},
                    recorded_by)
            paths.append(path)
    return paths


# ====================================================================== the generated drawing (H-2)
def write_drawing(store: Store, project: ProjectFolder, out: Path, recorded_by: str = "図面の出口") -> Path:
    import ezdxf
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4
    for layer in (f"{GEN_PREFIX}WALL_FACE", f"{GEN_PREFIX}ROOM_NAME"):
        doc.layers.add(layer)
    msp = doc.modelspace()
    for wall in approved_elements_by_kind(store, project).get("壁", []):
        v = effective_value(store, project, wall, "芯線")
        seg = geometry.segment(v.value) if v.present else None
        if seg is None:
            continue
        t = effective_value(store, project, wall, "厚さ")
        half = float(t.value) / 2.0 if t.present else 50.0
        ux, uy = geometry._unit(seg)
        nx, ny = -uy, ux
        for sgn in (1, -1):
            a = (seg[0][0] + nx * half * sgn, seg[0][1] + ny * half * sgn)
            b = (seg[1][0] + nx * half * sgn, seg[1][1] + ny * half * sgn)
            msp.add_line(a, b, dxfattribs={"layer": f"{GEN_PREFIX}WALL_FACE"})
    from btruth.effective import room_ring
    for room in _rooms(store, project):
        ring = room_ring(store, project, room)
        if not ring:
            continue
        cx, cy = sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring)
        label = f"{effective_name(store, project, room) or '（名前なし）'} {room_area_m2(store, project, room):.2f}㎡"
        msp.add_text(label, dxfattribs={"layer": f"{GEN_PREFIX}ROOM_NAME", "height": 250}).set_placement((cx, cy))
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(out)
    _record(store, "図面", out, {"layer_prefix": GEN_PREFIX, "content": "壁の両面の線（有効値の芯線と厚さ）、室名と面積"}, recorded_by)
    return out


# ====================================================================== writing back (H-3, M-2)
def approved_drawing_fixes(store: Store, version_id: str) -> list[dict]:
    """The drawing fixes a person approved: a review on an issue whose chosen option applies the issue's drawing_fix."""
    out = []
    for r in store.all("select * from review where target_kind='issue' order by rowid"):
        choice = loads(r["choice_json"]) or {}
        if not (choice.get("effect") or {}).get("applies_drawing_fix"):
            continue
        issue = store.one("select proposal_json from issue where id=?", r["target_id"])
        fix = (loads(issue["proposal_json"]) or {}).get("drawing_fix") if issue else None
        if fix and fix.get("source_version_id") == version_id:
            out.append({"review_id": r["id"], **fix})
    return out


def _match_entity(msp, clue_row, tol: float):
    """The entity of the person's drawing that is this clue: kind + layer + geometry (handles of Jw_cad exports may
    repeat, so they only break ties)."""
    g = loads(clue_row["geometry_json"]) or {}
    kind, layer = clue_row["kind"], clue_row["layer_raw"]
    handle = (loads(clue_row["format_extra_json"]) or {}).get("handle")
    found = []
    for e in msp:
        if e.dxftype() != kind or e.dxf.get("layer", "0") != layer:
            continue
        if kind == "INSERT":
            p = e.dxf.insert
            if math.dist((p.x, p.y), tuple(g["insert"][:2])) <= tol:
                found.append(e)
        elif kind == "LINE":
            s, t = e.dxf.start, e.dxf.end
            a, b = tuple(g["start"][:2]), tuple(g["end"][:2])
            if (math.dist((s.x, s.y), a) <= tol and math.dist((t.x, t.y), b) <= tol) or \
                    (math.dist((s.x, s.y), b) <= tol and math.dist((t.x, t.y), a) <= tol):
                found.append(e)
    if len(found) > 1 and handle:
        found = [e for e in found if e.dxf.get("handle") == handle] or found
    return found[0] if found else None


def write_back(store: Store, project: ProjectFolder, source_name: str, original: Path, out: Path,
               recorded_by: str = "書き戻し") -> str:
    """Writes the approved drawing fixes of the latest version of `source_name` into a new DXF `out`, made from the
    person's `original` drawing. Returns the writeback id. Refuses (writes nothing) if the original's sha256 is not
    the imported one, or if `out` is the original."""
    from ezdxf import recover
    original, out = Path(original), Path(out)
    v = store.one("select v.* from source_version v join source s on s.id=v.source_id where s.name=? order by v.seq desc limit 1",
                  source_name)
    if v is None:
        raise WritebackRefused(f"出どころがありません: {source_name}")
    if out.resolve() == original.resolve():
        raise WritebackRefused("元の図面には書かない（新しいファイルに書く。H-3）")
    fixes = approved_drawing_fixes(store, v["id"])
    verified = original.exists() and sha256_of(original) == v["sha256"]
    if not verified:
        wid = store.insert("writeback", recorded_by, generation_id=None, base_source_version_id=v["id"], base_sha256_verified=0,
                           review_ids_json=dumps([f["review_id"] for f in fixes]), new_path=None, sha256=None, status="書かなかった")
        store.commit()
        raise WritebackRefused(f"元の図面が、取り込んだ版（{source_name}@{v['seq']}）と違うので書かない（sha256 が一致しない。H-3）。"
                               f"記録 {wid}")
    if not fixes:
        raise WritebackRefused("承認された図面の修正案がない（`btruth choose` で図面の修正案の選択肢を選ぶ）")
    rules = effective_rules(store, project)
    tol = float(rules.get("same_position_mm", "0.1"))
    doc, _ = recover.readfile(original)
    msp = doc.modelspace()
    done = []
    for f in fixes:
        for cid in f.get("clue_ids") or []:
            c = store.one("select * from clue where id=?", cid)
            if c is None or c["kind"] not in ("INSERT", "LINE"):
                continue
            e = _match_entity(msp, c, tol)
            if e is None:
                continue
            if c["kind"] == "INSERT" and f["attribute"] in ("幅", "高さ") and f.get("was"):
                ratio = float(f["value"]) / float(f["was"])
                e.dxf.xscale = e.dxf.get("xscale", 1.0) * ratio
                e.dxf.yscale = e.dxf.get("yscale", 1.0) * ratio
                done.append({"review_id": f["review_id"], "clue_id": cid, "how": f"尺度 × {ratio:g}"})
            elif c["kind"] == "LINE" and f["attribute"] in ("芯線", "線分"):
                seg = geometry.segment(f["value"])
                if seg:
                    e.dxf.start, e.dxf.end = seg[0], seg[1]
                    done.append({"review_id": f["review_id"], "clue_id": cid, "how": "線の端点を採用の値へ"})
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(out)
    gid = _record(store, "書き戻し", out, {"writeback": True, "base_version": v["id"], "changes": done}, recorded_by,
                  {"base_version": v["id"]})
    wid = store.insert("writeback", recorded_by, generation_id=gid, base_source_version_id=v["id"], base_sha256_verified=1,
                       review_ids_json=dumps(sorted({d["review_id"] for d in done})), new_path=str(out), sha256=sha256_of(out),
                       status="未確認")
    store.commit()
    return wid


def writeback_status(store: Store, writeback_id: str) -> str:
    """未確認 until a person reviewed the written-back drawing in CAD (`confirm-drawing`; M-2)."""
    w = store.one("select * from writeback where id=?", writeback_id)
    if w is None:
        return "不明"
    if not w["generation_id"]:
        return w["status"]
    r = store.one("select action from review where target_kind='generation' and target_id=? order by rowid desc limit 1", w["generation_id"])
    return r["action"] if r else w["status"]
