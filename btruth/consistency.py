"""The consistency check (design I, C-3, C-7, C-10, D-1, J-2, J-3, J-7; examples 3, 5, 8, 9, 11).

It reads only (C-8): it writes one `check_run`, the issues it finds with their options, recheck marks for judgements
whose premises changed (決定 Q27), and a run_summary. It never writes `review` and never adopts a value.

What it looks at, for the elements of its scope (approved elements; all of them unless a scope is given):
  * every attribute that has claims from more than one source: per source the latest approved observation
    (未決 has no rank and no value), then
      - a judgement (adopted) that differs from a decision of a higher-ranked document → 決定が未反映（人の判断と食い違う）(例8);
      - the highest-ranked document's value differs from the primary source's → 決定が未反映, with a fix for the
        lower document (例3, 例9; C-10: the higher one is shown as 正, the person confirms);
      - a secondary source differs from the primary → 言い分の食い違い（主と従）(例2);
      - a site drawing (compare_only) differs from the design documents → 設計図と施工図の食い違い, shown only (C-10);
      - 未決 minutes → 議事録の未決 (記録のみ; 「保留として残る」);
  * type and instance (決定 9): conflicting observations → 言い分の食い違い（型と実物）; an observed 層の例外 that is
    not adopted does not win over the wall type (例5);
  * the opening's width against its door type's width (C-2d; drawing against document: door_width_tol_mm);
  * the partners' intervals (C-2c, C-2e, 例11): 壁が境界の外に出ている, 壁が途中で終わる, 境界の相手がない壁;
    the facing boundaries' kinds per interval (決定 6, Q20); doors whose tag is not in a door schedule (決定 Q12);
    rooms without a name (B-12); a wall away from its boundaries while it should follow them (例1).
Documents are compared exactly; drawing measurements use the tolerances of rules.csv (決定 14). Intervals are
computed, never stored (決定 5).

Open issues are read in effective.open_issues: the latest check per scope replaces the earlier ones; held issues
and issues outside the scope stay open (決定 15). An issue the person already answered for the same claims is not
raised again.
"""
from __future__ import annotations

import json
import math

from btruth import geometry
from btruth.checks import _severity
from btruth.common import dumps, loads
from btruth.effective import (STATUS_APPROVED, _approved_observations, _kind_of, approved_elements_by_kind, claim_status,
                              effective_name, effective_value, item_status, open_issues, relations_from, relations_to,
                              types_of)
from btruth.project import ProjectFolder
from btruth.store import Store
from btruth.tables import TABLE_KINDS, effective_rows, effective_rules, latest_load_id, load_tables

FOLLOW_KIND = "壁芯は部屋割り線に従う"
SKIP_ATTRIBUTES = {"種類"}


# ====================================================================== small helpers
def _source(store: Store, version_id: str | None):
    if not version_id:
        return None
    return store.one("select v.id as vid, v.seq, v.format, v.document_date, s.id as sid, s.name, s.kind from source_version v "
                     "join source s on s.id=v.source_id where v.id=?", version_id)


def _source_key(store: Store, src) -> str:
    dt = store.one("select value from source_attribute where source_id=? and attribute='図面の種類' order by rowid desc limit 1", src["sid"])
    return f"{src['kind'] or ''}:{dt['value']}" if dt else (src["kind"] or "")


def _ranks(store: Store, project: ProjectFolder) -> dict:
    out = {}
    for r in effective_rows(store, project, "document_rank"):
        rank = (r.get("rank") or "").strip()
        out[(r.get("source_kind") or "").strip()] = {"rank": int(rank) if rank.isdigit() else None,
                                                    "compare_only": (r.get("compare_only") or "").strip() == "yes"}
    return out


def _primary(store: Store, project: ProjectFolder, kind: str | None, attribute: str) -> str | None:
    for r in effective_rows(store, project, "authority"):
        if r.get("element_kind") == kind and r.get("attribute") == attribute:
            return (r.get("primary_source_kind") or "").strip() or None
    return None


def _measured(src) -> bool:
    """A value measured on a drawing (its shape), as against a value written in a document (決定 14)."""
    return bool(src) and (src["format"] or "") in ("dxf", "jww")


def _same(a, b, tol: float) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= tol
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y, tol) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k], tol) for k in a)
    return a == b


def _tolerance(rules: dict, attribute: str, src_a, src_b) -> float:
    """Documents against documents: exact. Drawings: the measuring tolerances (rules.csv, use = 図面の計測)."""
    if not _measured(src_a) and not _measured(src_b):
        return 0.0
    if attribute == "幅" and (_measured(src_a) != _measured(src_b)):
        return float(rules.get("door_width_tol_mm", "100"))
    return float(rules.get("same_position_mm", "0.1"))


def primary_discipline(store: Store, project: ProjectFolder, element_id: str) -> str | None:
    """The element's primary discipline, from its kind's core rows of authority.csv (C-7, E-3): the 分野 of the
    sources whose class matches the primary source of a core attribute. Computed, not stored."""
    kind = _kind_of(store, element_id)
    keys = [(r.get("primary_source_kind") or "").strip() for r in effective_rows(store, project, "authority")
            if r.get("element_kind") == kind and (r.get("core") or "").strip() == "yes"]
    for s in store.all("select id, kind from source order by rowid"):
        src = {"sid": s["id"], "kind": s["kind"]}
        if _source_key(store, src) in keys:
            d = store.one("select value from source_attribute where source_id=? and attribute='分野' order by rowid desc limit 1", s["id"])
            if d:
                return d["value"]
    return None


# ====================================================================== intervals (C-2c, 例11) and materials (C-3, 例5)
def _round(x: float) -> float:
    return round(x, 6) + 0.0


def boundary_intervals(store: Store, project: ProjectFolder, boundary_id: str) -> dict:
    """The intervals of a boundary (distances from its start) its partners cover, computed from effective values:
    a wall covers where it touches directly (the openings that void it are cut out); an opening covers its own part."""
    from btruth.propose import opening_segment
    rules = effective_rules(store, project)
    gap = float(rules.get("gap_tol_mm", "50"))
    v = effective_value(store, project, boundary_id, "線分")
    bseg = geometry.segment(v.value) if v.present else None
    out = {"segment": bseg, "walls": [], "openings": [], "partners": []}
    if bseg is None:
        return out
    for r in relations_from(store, boundary_id, "境界の相手"):
        pid = r["to_element_id"]
        out["partners"].append(pid)
        kind = _kind_of(store, pid)
        if kind == "開口":
            oseg = opening_segment(store, project, pid)
            ov = geometry.overlap_on(bseg, oseg, gap) if oseg else None
            if ov:
                out["openings"].append([pid, [_round(ov[0]), _round(ov[1])]])
            continue
        w = effective_value(store, project, pid, "芯線")
        wseg = geometry.segment(w.value) if w.present else None
        ov = geometry.overlap_on(bseg, wseg, gap) if wseg else None
        if not ov:
            continue
        cuts = []
        for o in relations_to(store, pid, "くり抜く"):
            oseg = opening_segment(store, project, o["from_element_id"])
            oo = geometry.overlap_on(bseg, oseg, gap) if oseg else None
            if oo:
                cuts.append(oo)
        pieces = geometry.gaps(ov, cuts, gap) if cuts else [ov]
        for a, b in pieces:
            out["walls"].append([pid, [_round(a), _round(b)]])
    return out


def kinds_along(store: Store, project: ProjectFolder, boundary_id: str, length: float) -> list[tuple[float, float, str]]:
    """境界の種類 along the boundary: one value for the whole length, or per interval (決定 Q20)."""
    v = effective_value(store, project, boundary_id, "境界の種類")
    if not v.present:
        return []
    if isinstance(v.value, list):
        out = []
        for x in v.value:
            if isinstance(x, dict) and isinstance(x.get("区間"), list):
                out.append((float(x["区間"][0]), float(x["区間"][1]), x.get("値")))
        return sorted(out)
    return [(0.0, length, v.value)]


def layers_of(store: Store, project: ProjectFolder, wall_id: str) -> list[dict]:
    """The wall's layers: its assembly (`使う`, else its type's `組み立てを持つ`), with the *adopted* 層の例外 applied.
    An observed exception that is not adopted does not change the layers (決定 9: the note does not win silently)."""
    asm = next((r["to_element_id"] for r in relations_from(store, wall_id, "使う")), None)
    if asm is None:
        for t in types_of(store, wall_id):
            asm = next((r["to_element_id"] for r in relations_from(store, t, "組み立てを持つ")), None)
            if asm:
                break
    if asm is None:
        return []
    layers = []
    for r in relations_from(store, asm, "層である"):
        role = loads(r["role_json"]) or {}
        name = effective_value(store, project, r["to_element_id"], "名称").value
        layers.append({"順": role.get("順"), "面": role.get("面"), "材料": name, "厚さ": role.get("厚さ"), "枚数": role.get("枚数")})
    layers.sort(key=lambda x: (x["順"] is None, x["順"] or 0))
    adopted = store.one("select value_json from claim where subject_id=? and attribute='層の例外' and mode='採用' order by rowid desc limit 1",
                        wall_id)
    if adopted:
        exc = loads(adopted["value_json"])
        for e in exc if isinstance(exc, list) else [exc]:
            faces = ("A", "B") if e.get("面") == "両" else (e.get("面"),)
            for layer in layers:
                if layer["面"] in faces:
                    if e.get("枚数") is not None:
                        layer["枚数"] = e["枚数"]
                    if e.get("材料"):
                        layer["材料"] = e["材料"]
    return layers


def schedule_tags(store: Store) -> set:
    tags = set()
    for r in store.all("select c.text_raw from clue c join source_version v on v.id=c.source_version_id join source_attribute a "
                       "on a.source_id=v.source_id where a.attribute='図面の種類' and a.value='建具表' and c.kind='ROW'"):
        from btruth.identity import _row_key
        k = _row_key(r["text_raw"])
        if k:
            tags.add(k)
    return tags


def counted_doors(store: Store, project: ProjectFolder) -> list[str]:
    """Doors that count (決定 Q12): approved, and their tag is in a door schedule or their 建具の種類 is adopted."""
    tags = schedule_tags(store)
    out = []
    for d in approved_elements_by_kind(store, project).get("建具", []):
        tag = effective_value(store, project, d, "符号", through_type=False).value
        kind = effective_value(store, project, d, "建具の種類")
        if (tag is not None and str(tag) in tags) or kind.status == "採用":
            out.append(d)
    return out


# ====================================================================== the premises of judgements (決定 Q27 の足し)
def mark_changed_premises(store: Store, recorded_by: str) -> int:
    from btruth.identity import add_mark
    n = 0
    reviews = {r["review_id"] for r in store.all("select distinct review_id from claim where mode='採用' and review_id is not null")}
    for rid in reviews:
        for p in store.all("select kind, ref_id from review_premise where review_id=?", rid):
            if p["kind"] == "table_load":
                load = store.one("select kind, scope, sha256 from table_load where id=?", p["ref_id"])
                if not load:
                    continue
                latest = latest_load_id(store, load["kind"], load["scope"])
                if latest and latest != p["ref_id"] and store.scalar("select sha256 from table_load where id=?", latest) != load["sha256"]:
                    if add_mark(store, recorded_by, rid, "table_load", latest, "判断の前提のルールの表が変わった",
                                {"table": load["kind"], "scope": load["scope"], "was": p["ref_id"]}):
                        n += 1
            elif p["kind"] == "assumption":
                item = store.one("select id from interpretation_item where assumption_id=?", p["ref_id"])
                if item and item_status(store, item["id"]) in ("却下", "はじかれた"):
                    if add_mark(store, recorded_by, rid, "assumption", p["ref_id"], "判断の前提が却下された", {}):
                        n += 1
    return n


# ====================================================================== the check
def check(store: Store, project: ProjectFolder, recorded_by: str, scope: list[str] | None = None, trigger: str = "人の求め",
          identity_run_id: str | None = None) -> tuple[str, list[str]]:
    load_tables(store, project, recorded_by=recorded_by)
    marks = mark_changed_premises(store, recorded_by)
    rules = effective_rules(store, project)
    gap = float(rules.get("gap_tol_mm", "50"))
    tol_pos = float(rules.get("same_position_mm", "0.1"))
    tol_deg = float(rules.get("same_angle_deg", "0.01"))
    ranks = _ranks(store, project)
    by_kind = approved_elements_by_kind(store, project)
    approved = [e for es in by_kind.values() for e in es]
    in_scope = list(dict.fromkeys(scope)) if scope is not None else approved
    in_scope = [e for e in in_scope if e in set(approved)]
    kinds = {e: _kind_of(store, e) for e in approved}
    run = store.insert("check_run", recorded_by, trigger=trigger,
                       scope_json=dumps({"elements": in_scope, "identity_run_id": identity_run_id}),
                       authority_table_load_id=latest_load_id(store, "authority", "物件"),
                       rank_table_load_id=latest_load_id(store, "document_rank", "物件"),
                       rules_table_load_id=latest_load_id(store, "rules", "物件"), counts_json=None)

    # what the person has already answered, and what is held: not raised again (決定 15)
    def signature(kind, subjects, attribute, claim_ids):
        return (kind, frozenset(subjects), attribute or "", frozenset(claim_ids or []))
    answered, held = set(), set()
    for i in store.all("select * from issue"):
        b = loads(i["basis_json"]) or {}
        sig = signature(i["kind"], loads(i["subject_ids_json"]) or [], b.get("属性"), b.get("claim_ids"))
        acts = [r["action"] for r in store.all("select action from review where target_kind='issue' and target_id=?", i["id"])]
        if any(a != "保留" for a in acts):
            answered.add(sig)
        elif acts:
            held.add(sig)
    issues: list[str] = []

    def issue(kind, subjects, facts, options, attribute=None, claim_ids=None, basis=None, proposal=None, severity=None):
        sig = signature(kind, subjects, attribute, claim_ids)
        if sig in answered or sig in held:
            return None
        b = dict(basis or {})
        b.update({"属性": attribute, "claim_ids": sorted(claim_ids or [])})
        iid = store.insert("issue", recorded_by, check_run_id=run, identity_run_id=identity_run_id, condition_check_id=None, kind=kind,
                           severity=severity or _severity(rules, kind), subject_ids_json=dumps(subjects), basis_json=dumps(b),
                           facts_json=dumps(facts), proposal_json=dumps(proposal) if proposal else None)
        for code, label, effect in options:
            store.insert("issue_option", recorded_by, issue_id=iid, code=code, label=label, effect_json=dumps(effect))
        issues.append(iid)
        answered.add(sig)          # once per run
        return iid

    def claims_effect(*claims, basis_version=None, note=None):
        d = {"claims": [c for c in claims]}
        if basis_version:
            d["basis_source_version_id"] = basis_version
        if note:
            d["note"] = note
        return d

    # ---------------------------------------------------------------- per element, per attribute: all sources (C-3, C-7, C-10)
    for eid in in_scope:
        kind = kinds.get(eid)
        attrs = [r["attribute"] for r in store.all("select distinct attribute from claim where subject_id=?", eid)
                 if r["attribute"] not in SKIP_ATTRIBUTES]
        for attr in attrs:
            undecided = [c for c in store.all("select * from claim where subject_id=? and attribute=? and mode='観測' and statement_kind='未決'",
                                              eid, attr) if claim_status(store, c) == STATUS_APPROVED]
            for c in undecided:
                src = _source(store, c["source_version_id"])
                issue("議事録の未決", [eid], {"属性": attr, "文": loads(c["value_json"]), "出どころ": src["name"] if src else None,
                                         "note": "「〜を検討する」「次回確認」は格を持たない。保留として残す（C-10）"},
                      [("confirm", "確認した（記録のみ）", {})], attribute=attr, claim_ids=[c["id"]], severity="記録のみ")
            obs = _approved_observations(store, eid, attr)
            per_source: dict = {}
            for o in obs:                                   # rows come in order: the later of the newest version wins
                cur = per_source.get(o["source_id"])
                if cur is None or o["seq"] >= cur["seq"]:
                    per_source[o["source_id"]] = o
            entries = []
            for o in per_source.values():
                src = _source(store, o["claim"]["source_version_id"])
                if src is None:
                    continue
                rk = ranks.get(src["kind"] or "", {"rank": None, "compare_only": False})
                rank = rk["rank"]
                if src["kind"] == "議事録" and o["claim"]["statement_kind"] != "決定":
                    rank = None
                entries.append({"claim": o["claim"], "value": o["value"], "src": src, "key": _source_key(store, src),
                                "rank": rank, "compare_only": rk["compare_only"]})
            adopted = store.one("select * from claim where subject_id=? and attribute=? and mode='採用' order by rowid desc limit 1", eid, attr)
            design = [x for x in entries if not x["compare_only"] and x["rank"] is not None]
            site = [x for x in entries if x["compare_only"]]
            if adopted:
                # 例8: a judgement against a higher-ranked decision
                rev = store.one("select * from review where id=?", adopted["review_id"]) if adopted["review_id"] else None
                bsrc = _source(store, rev["basis_source_version_id"]) if rev and rev["basis_source_version_id"] else None
                jrank = (ranks.get(bsrc["kind"] or "", {}).get("rank") if bsrc else None) or 5
                aval = loads(adopted["value_json"])
                for x in design:
                    if x["rank"] < jrank and not _same(aval, x["value"], 0.0):
                        issue("決定が未反映（人の判断と食い違う）", [eid],
                              {"属性": attr, "判断": aval, "判断の格": jrank, "議事録": x["value"], "議事録の格": x["rank"],
                               "出どころ": x["src"]["name"],
                               "note": "議事録の決定が上位（C-10）。ただし採用は人の判断なので黙って上書きしない（例8）"},
                              [("follow_minutes", "議事録に合わせる（新しい判断）",
                                claims_effect({"subject": eid, "attribute": attr, "value": x["value"], "unit": x["claim"]["unit"]},
                                              basis_version=x["src"]["vid"])),
                               ("keep_judgement", "判断を保つ（理由を書く。食い違いは記録に残る）", {})],
                              attribute=attr, claim_ids=[x["claim"]["id"], adopted["id"]],
                              basis={"review_id": adopted["review_id"], "adopted_claim_id": adopted["id"]})
                continue
            if len(entries) < 2:
                continue
            primary_key = _primary(store, project, kind, attr)
            prim = next((x for x in design if x["key"] == primary_key), None)
            best = min((x["rank"] for x in design), default=None)
            top = [x for x in design if x["rank"] == best]
            if len(top) > 1:
                values = {json.dumps(x["value"], sort_keys=True, ensure_ascii=False) for x in top}
                if len(values) > 1:
                    dated = [x for x in top if x["src"]["document_date"]]
                    if len(dated) == len(top):
                        top = sorted(top, key=lambda x: x["src"]["document_date"])[-1:]
                    elif prim not in top:
                        issue("新旧が決まらない", [eid], {"属性": attr, "出どころ": [x["src"]["name"] for x in top],
                                                    "note": "同じ格の書類の新旧を、書類の日付で決められない（J-3）"},
                              [("pick", "人が選ぶ", {})], attribute=attr, claim_ids=[x["claim"]["id"] for x in top])
                        continue
            higher = top[0] if top else None
            base = prim or higher
            if base is None:
                continue
            if higher and prim and higher is not prim and higher["rank"] < prim["rank"] and \
                    not _same(higher["value"], prim["value"], _tolerance(rules, attr, higher["src"], prim["src"])):
                options = [("adopt_higher", f"承認（{higher['src']['name']}どおり → 採用）",
                            claims_effect({"subject": eid, "attribute": attr, "value": higher["value"], "unit": higher["claim"]["unit"]},
                                          basis_version=higher["src"]["vid"])),
                           ("keep_lower", f"却下（{prim['src']['name']}のまま。理由を書く）", {})]
                if kind == "建具の型" and attr == "幅":
                    options = _door_width_options(store, project, eid, higher)
                tag = effective_value(store, project, eid, "符号").value
                issue("決定が未反映", [eid],
                      {"属性": attr, "正とみなす": {"出どころ": higher["src"]["name"], "値": higher["value"], "格": higher["rank"]},
                       "従": {"出どころ": prim["src"]["name"], "値": prim["value"], "格": prim["rank"]},
                       "note": "格の高い書類の決定が、主の出どころにまだ反映されていない（C-10）。確定は人"},
                      options, attribute=attr, claim_ids=[higher["claim"]["id"], prim["claim"]["id"]],
                      proposal={"kind": "書類の修正案", "対象": prim["src"]["name"],
                                "text": f"{prim['src']['name']} の {tag or ''} の {attr} を {dumps(higher['value'])} に直す"})
                base = higher
            elif prim:
                for x in design:
                    if x is prim or _same(x["value"], prim["value"], _tolerance(rules, attr, x["src"], prim["src"])):
                        continue
                    issue("言い分の食い違い（主と従）", [eid],
                          {"属性": attr, "基準": f"{prim['src']['name']}（{prim['key']}）", "主の値": prim["value"],
                           "従": x["src"]["name"], "従の値": x["value"]},
                          [("fix_secondary", f"主に合わせる（{x['src']['name']}の修正案）", {}),
                           ("adopt_secondary", f"{x['src']['name']}の値を採る（採用）",
                            claims_effect({"subject": eid, "attribute": attr, "value": x["value"], "unit": x["claim"]["unit"]},
                                          basis_version=x["src"]["vid"]))],
                          attribute=attr, claim_ids=[prim["claim"]["id"], x["claim"]["id"]],
                          proposal={"kind": "図面・書類の修正案", "対象": x["src"]["name"],
                                    "text": f"{x['src']['name']} の {attr} を {dumps(prim['value'])} に（基準 {prim['src']['name']}）"})
            for x in site:
                if all(_same(x["value"], d["value"], _tolerance(rules, attr, x["src"], d["src"])) for d in design):
                    continue
                issue("設計図と施工図の食い違い", [eid],
                      {"属性": attr, "設計図": [{"出どころ": d["src"]["name"], "値": d["value"]} for d in design],
                       "施工図": {"出どころ": x["src"]["name"], "値": x["value"]},
                       "note": "どちらが正かは決めない。修正案も出さない（C-10）"},
                      [("confirm", "確認した（記録のみ）", {})], attribute=attr,
                      claim_ids=[x["claim"]["id"]] + [d["claim"]["id"] for d in design])

    # ---------------------------------------------------------------- type and instance (決定 9, 例5)
    for eid in in_scope:
        types = types_of(store, eid)
        if not types:
            continue
        for attr in [r["attribute"] for r in store.all("select distinct attribute from claim where subject_id=? and mode='観測'", eid)]:
            if attr in SKIP_ATTRIBUTES:
                continue
            v = effective_value(store, project, eid, attr)
            if v.status == "決まらない" and "型と実物" in v.note:
                issue("言い分の食い違い（型と実物）", [eid] + types, {"属性": attr, "候補": v.candidates,
                                                          "note": "型と実物の観測が食い違う。実物を黙って勝たせない（決定 9）"},
                      [("this_wall", "この実物だけの値にする（採用）", {}), ("follow_type", "型どおり（実物の書類の修正案）", {}),
                       ("change_type", "型を変える（型の判断）", {})], attribute=attr, claim_ids=v.candidates)
        exc = [c for c in store.all("select * from claim where subject_id=? and attribute='層の例外' and mode='観測' order by rowid desc", eid)
               if claim_status(store, c) == STATUS_APPROVED]
        if exc and not store.one("select 1 from claim where subject_id=? and attribute='層の例外' and mode='採用'", eid):
            c = exc[0]
            composition = None
            for t in types:
                composition = effective_value(store, project, t, "構成").value or composition
            issue("言い分の食い違い（型と実物）", [eid] + types,
                  {"属性": "層の例外", "実物の注記": loads(c["value_json"]), "型": composition,
                   "note": "注記の層の例外を、型（壁種表）に黙って勝たせない（例5、決定 9）"},
                  [("this_wall", "この壁だけ（採用 層の例外）",
                    claims_effect({"subject": eid, "attribute": "層の例外", "value": loads(c["value_json"]), "unit": None})),
                   ("follow_type", "壁種表どおり（注記の修正案）", {}), ("change_type", "型を変える（壁種の判断）", {})],
                  attribute="層の例外", claim_ids=[c["id"]])

    # ---------------------------------------------------------------- openings against their door type (C-2d)
    for eid in in_scope:
        if kinds.get(eid) != "開口":
            continue
        ow = effective_value(store, project, eid, "幅")
        for f in relations_to(store, eid, "ふさぐ"):
            for t in types_of(store, f["from_element_id"]):
                tw = effective_value(store, project, t, "幅")
                if not (ow.present and tw.present):
                    continue
                oc = store.one("select source_version_id from claim where id=?", ow.claim_id) if ow.claim_id else None
                tc = store.one("select source_version_id from claim where id=?", tw.claim_id) if tw.claim_id else None
                tol = _tolerance(rules, "幅", _source(store, oc["source_version_id"]) if oc else None,
                                 _source(store, tc["source_version_id"]) if tc else None)
                if not _same(ow.value, tw.value, tol):
                    issue("言い分の食い違い（主と従）", [eid, t], {"属性": "幅", "基準": "建具表（型の呼び幅）", "主の値": tw.value,
                                                           "従": "図面の開口", "従の値": ow.value, "許容差_mm": tol},
                          [("fix_secondary", "建具表に合わせる（図面の修正案）", {}),
                           ("adopt_secondary", "この開口の幅を採る（採用）",
                            claims_effect({"subject": eid, "attribute": "幅", "value": ow.value, "unit": "mm"}))],
                          attribute="幅", claim_ids=[x for x in (ow.claim_id, tw.claim_id) if x])

    offset_elements: set = set()
    # ---------------------------------------------------------------- a wall away from its boundaries while following them (例1)
    if _follow_in_force(store):
        for wall in [e for e in in_scope if kinds.get(e) == "壁"]:
            w = effective_value(store, project, wall, "芯線")
            ws = geometry.segment(w.value) if w.present else None
            if ws is None:
                continue
            off = []
            for r in relations_to(store, wall, "境界の相手"):
                b = effective_value(store, project, r["from_element_id"], "線分")
                bs = geometry.segment(b.value) if b.present else None
                if bs is None:
                    continue
                ang = lambda s: math.degrees(math.atan2(s[1][1] - s[0][1], s[1][0] - s[0][0])) % 180.0
                if abs((ang(ws) - ang(bs) + 90.0) % 180.0 - 90.0) > tol_deg:
                    continue
                d0, d1 = geometry.distance_to_line(ws, bs[0]), geometry.distance_to_line(ws, bs[1])
                if min(d0, d1) > tol_pos:
                    off.append((r["from_element_id"], max(d0, d1), bs))
            if not off:
                continue
            bs = off[0][2]
            u = geometry._unit(bs)
            def onto(p):
                t = geometry.along(bs, p)
                return [bs[0][0] + u[0] * t, bs[0][1] + u[1] * t]
            follow = [onto(ws[0]), onto(ws[1])]
            subjects = [wall] + [b for b, _, _ in off]
            offset_elements.update(subjects)            # one issue, not scattered ones (expected_diff.md)
            issue("壁と境界のずれ", subjects,
                  {"ずれ_mm": max(d for _, d, _ in off), "境界ごと": [[b, d] for b, d, _ in off],
                   "note": "期待の位置は保存しない（B-9、B-10）。壁の採用は書かない"},
                  [("follow", "境界線に合わせる", claims_effect({"subject": wall, "attribute": "芯線", "value": follow, "unit": "mm"},
                                                          note="図面の修正案：壁芯線を境界線へ")),
                   ("unfollow", "追従を外す", {"assumption": {"level": 3, "kind": FOLLOW_KIND, "value": "従わない",
                                                          "scope": subjects}})],
                  claim_ids=[w.claim_id] if w.claim_id else None,
                  basis={"前提": FOLLOW_KIND, "壁の芯線": w.value},
                  proposal={"kind": "図面の修正案", "text": "壁芯線を境界線の位置へ（「境界線に合わせる」を選んだとき）"})

    # ---------------------------------------------------------------- the registration kinds, on effective values (I-2)
    from btruth.checks import OPTIONS, wall_range_facts
    tags = schedule_tags(store)
    has_schedule = bool(store.one("select 1 from source_attribute where attribute='図面の種類' and value='建具表'"))
    for eid in in_scope:
        kind = kinds.get(eid)
        if kind == "部屋":
            ex = effective_value(store, project, eid, "部屋として扱う")
            if not effective_name(store, project, eid) and not (ex.present and ex.value is False):
                issue("名前がない空間", [eid], {"note": "閉じた空間に名前がない。黙って名前を付けない（B-12）"}, OPTIONS["名前がない空間"])
        elif kind == "壁" and eid not in offset_elements:
            facts = wall_range_facts(store, project, eid, None)
            if facts["partners"] == 0:
                issue("境界の相手がない壁", [eid], {"note": "どの空間の境界の相手にもなっていない（腰壁・袖壁・塀かもしれない。決定 2）"},
                      OPTIONS["境界の相手がない壁"])
            elif facts["outside_mm"] > gap:
                issue("壁が境界の外に出ている", [eid], facts, OPTIONS["壁が境界の外に出ている"],
                      proposal={"kind": "図面の修正案", "text": "壁の範囲を境界の区間の合併に合わせる"})
        elif kind == "空間の境界" and eid not in offset_elements:
            iv = boundary_intervals(store, project, eid)
            if iv["segment"] is None:
                continue
            L = geometry.length(iv["segment"])
            physical = [(a, b) for a, b, k in kinds_along(store, project, eid, L) if k == "物理的"]
            covered = [tuple(x[1]) for x in iv["walls"] + iv["openings"]]
            uncovered = []
            for a, b in physical:
                uncovered += geometry.gaps((a, b), [(max(a, c), min(b, d)) for c, d in covered if d > a and c < b], gap)
            if uncovered:
                issue("壁が途中で終わる", [eid] + iv["partners"], {"uncovered_intervals_mm": [list(x) for x in uncovered],
                                                               "boundary_length_mm": L, "walls": iv["walls"], "openings": iv["openings"]},
                      OPTIONS["壁が途中で終わる"])
        elif kind == "建具" and has_schedule:
            tag = effective_value(store, project, eid, "符号", through_type=False).value
            if tag not in (None, "") and str(tag) not in tags:
                issue("建具表にない符号", [eid], {"符号": tag, "note": "建具表に行がない。建具の種類は AI の提案のまま、承認まで数えない（決定 Q12）"},
                      OPTIONS["建具表にない符号"])

    # ---------------------------------------------------------------- facing boundaries (決定 6, Q20)
    seen_pairs = set()
    for eid in in_scope:
        if kinds.get(eid) != "空間の境界":
            continue
        for r in relations_from(store, eid, "向かい合う") + relations_to(store, eid, "向かい合う"):
            other = r["to_element_id"] if r["from_element_id"] == eid else r["from_element_id"]
            pair = frozenset((eid, other))
            if pair in seen_pairs or other not in kinds:
                continue
            seen_pairs.add(pair)
            mismatch = _facing_mismatch(store, project, eid, other, gap)
            if mismatch:
                issue("向かい合う境界の種類の食い違い", sorted(pair), {"区間": mismatch,
                                                            "note": "同じ線の両側で、物理的／仮想が食い違う（決定 6）"},
                      [("fix", "片側に合わせる（判断）", {}), ("keep", "このままでよい（理由を書く）", {})])

    store.insert("run_summary", recorded_by, kind="整合の照らし",
                 counts_json=dumps({"check_run_id": run, "trigger": trigger, "scope": len(in_scope), "issues": len(issues),
                                    "再確認の印": marks}))
    store.commit()
    return run, issues


def _door_width_options(store: Store, project: ProjectFolder, type_id: str, higher: dict) -> list:
    """決定 13: where the value goes (the type AD-1 as a whole, or this door only) and which width (the door's nominal
    width, or the opening's width)."""
    value, unit, vid = higher["value"], higher["claim"]["unit"] or "mm", higher["src"]["vid"]
    tag = effective_value(store, project, type_id, "符号").value or ""
    def eff(subject, attribute):
        return {"claims": [{"subject": subject, "attribute": attribute, "value": value, "unit": unit}], "basis_source_version_id": vid}
    options = [("type_width", f"型（{tag} 全体）の呼び幅を {value} に（建具表の修正案）", eff(type_id, "幅"))]
    doors = [r["from_element_id"] for r in relations_to(store, type_id, "型である")]
    for n, d in enumerate(doors):
        suffix = "" if len(doors) == 1 else f"_{n + 1}"
        options.append((f"door_width{suffix}", f"この建具だけ（{d[:8]}）の呼び幅を {value} に", eff(d, "幅")))
        for k, o in enumerate(relations_from(store, d, "ふさぐ")):
            osfx = suffix + ("" if k == 0 else f"_{k + 1}")
            options.append((f"opening_width{osfx}", f"この開口（{o['to_element_id'][:8]}）の幅を {value} に（開口の幅。穴・境界の区間・数量が同じ値を使う）",
                            eff(o["to_element_id"], "幅")))
    options.append(("keep_lower", "却下（建具表のまま。理由を書く）", {}))
    return options


def _facing_mismatch(store: Store, project: ProjectFolder, a: str, b: str, gap: float):
    va, vb = effective_value(store, project, a, "線分"), effective_value(store, project, b, "線分")
    sa = geometry.segment(va.value) if va.present else None
    sb = geometry.segment(vb.value) if vb.present else None
    if sa is None or sb is None:
        return None
    La, Lb = geometry.length(sa), geometry.length(sb)
    ka, kb = kinds_along(store, project, a, La), kinds_along(store, project, b, Lb)
    if not ka or not kb:
        return None
    u = geometry._unit(sa)

    def at_a(t):
        return (sa[0][0] + u[0] * t, sa[0][1] + u[1] * t)

    def kind_a(t):
        return next((k for x, y, k in ka if x - 1e-9 <= t <= y + 1e-9), None)

    def kind_b(p):
        t = geometry.along(sb, p)
        return next((k for x, y, k in kb if x - 1e-9 <= t <= y + 1e-9), None)

    cuts = {0.0, La}
    for x, y, _ in ka:
        cuts |= {x, y}
    for x, y, _ in kb:
        for t in (x, y):
            ub = geometry._unit(sb)
            p = (sb[0][0] + ub[0] * t, sb[0][1] + ub[1] * t)
            ta = geometry.along(sa, p)
            if 0.0 <= ta <= La:
                cuts.add(ta)
    cuts = sorted(cuts)
    bad = []
    for x, y in zip(cuts, cuts[1:]):
        if y - x <= gap:
            continue
        m = (x + y) / 2.0
        kb_m = kind_b(at_a(m))
        if kb_m is None:
            continue
        if kind_a(m) != kb_m:
            bad.append((x, y))
    if not bad:
        return None
    merged = geometry.merge_intervals(bad, gap)
    out = []
    for x, y in merged:
        p, q = at_a(x), at_a(y)
        out.append(sorted([[_round(p[0]), _round(p[1])], [_round(q[0]), _round(q[1])]]))
    return out[0] if len(out) == 1 else out


def _follow_in_force(store: Store) -> bool:
    found = False
    for a in store.all("select id, value_json from assumption where kind=? order by rowid", FOLLOW_KIND):
        item = store.one("select id from interpretation_item where assumption_id=?", a["id"])
        if item and item_status(store, item["id"]) == STATUS_APPROVED:
            found = loads(a["value_json"]) == "従う"
        elif a["value_json"] and loads(a["value_json"]) == "従わない" and store.one(
                "select 1 from assumption where id=? and review_id is not null", a["id"]):
            found = False
    return found
