"""Measuring an AI's reading against a fixed interpretation (design 3-5-1 (2), N-2; CONCEPT D-9).

Elements are matched by kind and a key computed from their claims (the grid label, the wall's centre
line, the boundary's directed segment, the room's name or its ring of boundaries, a type's tag). The
numbers — matched / missing / extra per kind, agreeing claims, relations found, what was handed to the
person (issues, rule-rejected items) — go to `run_summary`. No pass / fail line is drawn (D-9: the
confidence figures are the AI's own estimate until measured).
"""
from __future__ import annotations

import json

from btruth.common import dumps, loads
from btruth.project import ProjectFolder
from btruth.store import Store

KEY_ATTRIBUTES = {"通り芯": ("符号",), "壁種": ("符号",), "建具の型": ("符号",), "柱の型": ("符号",), "建具": ("符号",),
                  "柱": ("符号",), "壁": ("芯線",), "空間の境界": ("線分",), "部屋": ("室番号", "室名", "名前")}


def _round_seg(value, directed: bool):
    try:
        (a, b) = value
        pa, pb = (round(float(a[0])), round(float(a[1]))), (round(float(b[0])), round(float(b[1])))
    except (TypeError, ValueError, IndexError):
        return json.dumps(value, sort_keys=True)
    return (pa, pb) if directed else tuple(sorted((pa, pb)))


def _claims(store: Store, interpretation_id: str, element_id: str) -> dict:
    out = {}
    for c in store.all("select attribute, value_json from claim where subject_id=? and interpretation_id=? order by rowid",
                       element_id, interpretation_id):
        out[c["attribute"]] = loads(c["value_json"])
    return out


def _elements(store: Store, interpretation_id: str) -> dict[str, dict]:
    out = {}
    for i in store.all("select element_id, rule_check_status from interpretation_item where interpretation_id=? and kind='要素を作る'",
                       interpretation_id):
        eid = i["element_id"]
        claims = _claims(store, interpretation_id, eid)
        out[eid] = {"kind": claims.get("種類"), "claims": claims, "rejected": i["rule_check_status"] == "はじかれた"}
    return out


def _bounded_room(store: Store, interpretation_id: str, boundary_id: str) -> str | None:
    r = store.one("select to_element_id from relation where from_element_id=? and kind='区切る' and created_by_interpretation_id=?",
                  boundary_id, interpretation_id)
    return r["to_element_id"] if r else None


def signature(store: Store, interpretation_id: str, element_id: str, info: dict, elements: dict) -> tuple:
    kind, claims = info["kind"], info["claims"]
    if kind in ("壁",) and "芯線" in claims:
        return (kind, _round_seg(claims["芯線"], directed=False))
    if kind == "空間の境界" and "線分" in claims:
        room = _bounded_room(store, interpretation_id, element_id)
        room_sig = signature(store, interpretation_id, room, elements[room], elements)[1] if room in elements else ("existing", room)
        return (kind, _round_seg(claims["線分"], directed=True), room_sig)
    for a in KEY_ATTRIBUTES.get(kind, ()):
        if claims.get(a) not in (None, ""):
            return (kind, a, json.dumps(claims[a], sort_keys=True, ensure_ascii=False))
    if kind == "部屋":
        ring = sorted(_round_seg(elements[b]["claims"].get("線分"), True) for b in
                      [r["from_element_id"] for r in store.all(
                          "select from_element_id from relation where to_element_id=? and kind='区切る' and created_by_interpretation_id=?",
                          element_id, interpretation_id)] if b in elements)
        return (kind, "ring", json.dumps(ring, sort_keys=True))
    return (kind, "claims", json.dumps({k: v for k, v in claims.items() if k != "種類"}, sort_keys=True, ensure_ascii=False))


def _relation_sigs(store: Store, interpretation_id: str, sigs: dict) -> set:
    out = set()
    for r in store.all("select kind, from_element_id, to_element_id from relation where created_by_interpretation_id=?", interpretation_id):
        f = sigs.get(r["from_element_id"], ("existing", r["from_element_id"]))
        t = sigs.get(r["to_element_id"], ("existing", r["to_element_id"]))
        out.add((r["kind"], json.dumps(f, ensure_ascii=False), json.dumps(t, ensure_ascii=False)))
    return out


def measure(store: Store, project: ProjectFolder, ai_interpretation_id: str, fixed_interpretation_id: str,
            recorded_by: str = "測定") -> dict:
    ai_els, fx_els = _elements(store, ai_interpretation_id), _elements(store, fixed_interpretation_id)
    ai_sigs = {eid: signature(store, ai_interpretation_id, eid, info, ai_els) for eid, info in ai_els.items() if not info["rejected"]}
    fx_sigs = {eid: signature(store, fixed_interpretation_id, eid, info, fx_els) for eid, info in fx_els.items()}
    fx_by_sig = {}
    for eid, s in fx_sigs.items():
        fx_by_sig.setdefault(json.dumps(s, ensure_ascii=False), []).append(eid)
    matched_pairs = []
    used = set()
    for eid, s in ai_sigs.items():
        key = json.dumps(s, ensure_ascii=False)
        for cand in fx_by_sig.get(key, []):
            if cand not in used:
                used.add(cand)
                matched_pairs.append((eid, cand))
                break
    by_kind: dict[str, dict] = {}
    for eid, info in fx_els.items():
        by_kind.setdefault(info["kind"] or "?", {"fixed": 0, "ai": 0, "matched": 0})["fixed"] += 1
    for eid, info in ai_els.items():
        if not info["rejected"]:
            by_kind.setdefault(info["kind"] or "?", {"fixed": 0, "ai": 0, "matched": 0})["ai"] += 1
    for ai_id, fx_id in matched_pairs:
        by_kind[fx_els[fx_id]["kind"] or "?"]["matched"] += 1
    claims_total = claims_agree = 0
    for ai_id, fx_id in matched_pairs:
        for a, v in fx_els[fx_id]["claims"].items():
            if a == "種類":
                continue
            claims_total += 1
            if json.dumps(ai_els[ai_id]["claims"].get(a), sort_keys=True) == json.dumps(v, sort_keys=True):
                claims_agree += 1
    ai_rels, fx_rels = _relation_sigs(store, ai_interpretation_id, ai_sigs), _relation_sigs(store, fixed_interpretation_id, fx_sigs)
    issues = store.all("select i.kind from issue i join check_run c on c.id=i.check_run_id where c.scope_json like ?",
                       f'%{ai_interpretation_id}%')
    issue_kinds: dict[str, int] = {}
    for i in issues:
        issue_kinds[i["kind"]] = issue_kinds.get(i["kind"], 0) + 1
    rejected = store.scalar("select count(*) from interpretation_item where interpretation_id=? and rule_check_status='はじかれた'",
                            ai_interpretation_id)
    unread = store.scalar("select count(*) from interpretation_item where interpretation_id=? and kind='読めない'", ai_interpretation_id)
    result = {
        "ai_interpretation_id": ai_interpretation_id, "fixed_interpretation_id": fixed_interpretation_id,
        "elements": {"fixed": len(fx_els), "ai": len(ai_sigs), "matched": len(matched_pairs),
                     "missing": len(fx_els) - len(matched_pairs), "extra": len(ai_sigs) - len(matched_pairs)},
        "by_kind": by_kind,
        "claims_on_matched": {"total": claims_total, "agree": claims_agree},
        "relations": {"fixed": len(fx_rels), "ai": len(ai_rels), "matched": len(ai_rels & fx_rels)},
        "handed_to_person": {"issues": len(issues), "issues_by_kind": issue_kinds, "rejected_items": rejected,
                             "unreadable_items": unread},
        "note": "合格・不合格の線は引かない（D-9）。数字を見る",
    }
    store.insert("run_summary", recorded_by, kind="AI の解釈の正しさの測定", counts_json=dumps(result))
    store.commit()
    return result
