"""The light check at registration (design I-1, I-2, C-2e; the full consistency check is stage 5).

It reads the proposal's observed values and the effective values of what is already approved, writes
one `check_run` and the issues it finds, and changes nothing else (C-8: checking only reads). What it
hands to the person:
  * 名前がない空間        a room without 名前 / 室名 / 室番号 (B-12; options 名前を付ける / 部屋として扱わない)
  * 境界の相手がない壁    a wall that is nobody's 境界の相手 (C-2e, 決定 2: not rejected — 腰壁・袖壁・塀)
  * 壁が境界の外に出ている the wall's 芯線 reaches beyond the union of its partner boundaries' intervals
                          by more than gap_tol_mm (C-2e, 決定 8, 例10; F-1)
  * 壁が途中で終わる      a physical boundary with a part longer than gap_tol_mm that no wall or opening covers
                          (C-2c 例11 case 3, 決定 5)
  * 建具表にない符号      a door whose 符号 has no row in a door schedule (C-5, 決定 Q12; F-5)
  * 知らない名前          a kind / attribute / relation kind that is not in the CSV lists (J-5)
Severity: rules.csv `issue_severity.<kind>` if present, else 要確認 (D-8).
Intervals are computed, never stored (C-2c).
"""
from __future__ import annotations

from btruth import geometry
from btruth.common import dumps, loads
from btruth.effective import (effective_value, proposed_value, relations_from, relations_to, _kind_of,
                              proposed_kind_of, relation_status, NAME_ATTRIBUTES)
from btruth.project import ProjectFolder
from btruth.store import Store
from btruth.tables import effective_rules, latest_load_id

OPTIONS = {
    "名前がない空間": [("name", "名前を付ける", {"claim": {"attribute": "名前", "mode": "採用"}}),
                 ("exclude", "部屋として扱わない", {"claim": {"attribute": "部屋として扱う", "value": False, "mode": "採用"}})],
    "境界の相手がない壁": [("keep", "境界の相手を持たない壁として承認（腰壁・袖壁・塀など）", {}),
                   ("reject", "却下", {})],
    "壁が境界の外に出ている": [("shorten", "壁の範囲を境界の区間に合わせる（修正案）", {}), ("keep", "この範囲でよい（理由を書く）", {})],
    "壁が途中で終わる": [("virtual", "その区間を仮想にする", {"claim": {"attribute": "境界の種類", "value": "仮想", "mode": "採用"}}),
                 ("extend", "壁を延ばす（図面の修正案）", {}), ("opening", "開口として扱う（建具表に足す）", {})],
    "建具表にない符号": [("add", "建具表に足す", {}), ("fix", "図面の符号を直す（修正案）", {})],
    "知らない名前": [("add_row", "一覧の CSV に行を足す", {}), ("fix", "提案の名前を直す", {})],
    "壁と境界のずれ": [("follow", "境界線に合わせる", {"claim": {"attribute": "芯線", "mode": "採用"},
                                              "proposal": "図面の修正案：壁芯線を境界線へ"}),
                  ("unfollow", "追従を外す", {"assumption": {"level": 3, "kind": "壁芯は部屋割り線に従う", "value": "従わない"}})],
}


def _severity(rules: dict, kind: str) -> str:
    return rules.get(f"issue_severity.{kind}") or "要確認"


def _value(store, project, element_id, attribute, interpretation_id):
    v = effective_value(store, project, element_id, attribute)
    if v.present:
        return v.value
    return proposed_value(store, element_id, attribute, interpretation_id) if interpretation_id else proposed_value(store, element_id, attribute)


def _segment(store, project, element_id, attribute, interpretation_id):
    return geometry.segment(_value(store, project, element_id, attribute, interpretation_id))


def _relations(store, element_id, kind, direction, interpretation_id):
    """Approved relations plus the pending ones of this interpretation."""
    fn = relations_from if direction == "from" else relations_to
    rels = fn(store, element_id, kind, include_pending=True)
    return [r for r in rels if r["created_by_interpretation_id"] == interpretation_id
            or relation_status(store, r["id"]) in ("承認済み", "既定")]


def partner_intervals(store: Store, project: ProjectFolder, boundary_id: str, interpretation_id: str | None, gap: float) -> dict:
    """Intervals of the boundary (distances from its start) covered by its partner walls and openings."""
    from btruth.propose import opening_segment
    bseg = _segment(store, project, boundary_id, "線分", interpretation_id)
    out = {"segment": bseg, "walls": [], "openings": [], "partners": []}
    if bseg is None:
        return out
    for r in _relations(store, boundary_id, "境界の相手", "from", interpretation_id):
        pid = r["to_element_id"]
        pkind = _kind_of(store, pid) or proposed_kind_of(store, pid)
        out["partners"].append(pid)
        if pkind == "開口":
            pseg = opening_segment(store, project, pid)
        else:
            pseg = _segment(store, project, pid, "芯線", interpretation_id)
        if pseg is None:
            continue
        ov = geometry.overlap_on(bseg, pseg, gap)
        if ov:
            (out["openings"] if pkind == "開口" else out["walls"]).append((pid, ov))
    return out


def wall_range_facts(store: Store, project: ProjectFolder, wall_id: str, interpretation_id: str | None = None) -> dict:
    """How far the wall's 芯線 reaches beyond the union of the intervals of the boundaries it partners (C-2e).
    The boundaries' intervals are projected onto the wall's own line; the opening intervals that void this wall
    count as covered too (開口では壁は切れない)."""
    rules = effective_rules(store, project)
    gap = float(rules.get("gap_tol_mm", "50"))
    wseg = _segment(store, project, wall_id, "芯線", interpretation_id)
    facts = {"wall_id": wall_id, "partners": 0, "covered_mm": [], "outside_intervals_mm": [], "outside_mm": 0.0}
    if wseg is None:
        facts["note"] = "芯線がない"
        return facts
    covered = []
    for r in _relations(store, wall_id, "境界の相手", "to", interpretation_id):
        bseg = _segment(store, project, r["from_element_id"], "線分", interpretation_id)
        if bseg is None:
            continue
        facts["partners"] += 1
        ov = geometry.overlap_on(wseg, bseg, gap)
        if ov:
            covered.append(ov)
    for r in _relations(store, wall_id, "くり抜く", "to", interpretation_id):
        from btruth.propose import opening_segment
        oseg = opening_segment(store, project, r["from_element_id"])
        if oseg:
            ov = geometry.overlap_on(wseg, oseg, gap)
            if ov:
                covered.append(ov)
    merged = geometry.merge_intervals(covered, gap)
    facts["covered_mm"] = [[a, b] for a, b in merged]
    if facts["partners"] == 0:
        return facts
    outside = geometry.gaps((0.0, geometry.length(wseg)), merged, gap)
    facts["outside_intervals_mm"] = [[a, b] for a, b in outside]
    facts["outside_mm"] = sum(b - a for a, b in outside)
    # also report the gaps in drawing coordinates along the wall, for the person
    u = geometry._unit(wseg)
    facts["outside_points"] = [[[wseg[0][0] + u[0] * a, wseg[0][1] + u[1] * a], [wseg[0][0] + u[0] * b, wseg[0][1] + u[1] * b]]
                               for a, b in outside]
    return facts


def check_proposal(store: Store, project: ProjectFolder, interpretation_id: str, recorded_by: str,
                   unknown_names: list | None = None) -> tuple[str, list[str]]:
    rules = effective_rules(store, project)
    gap = float(rules.get("gap_tol_mm", "50"))
    items = store.all("select id, kind, element_id, rule_check_status from interpretation_item where interpretation_id=? "
                      "and kind='要素を作る' and rule_check_status='通った'", interpretation_id)
    elements = [i["element_id"] for i in items]
    kinds = {eid: proposed_kind_of(store, eid) for eid in elements}
    run_id = store.insert("check_run", recorded_by, trigger="提案の登録", scope_json=dumps({"interpretation_id": interpretation_id,
                          "elements": elements}), authority_table_load_id=latest_load_id(store, "authority", "物件"),
                          rank_table_load_id=latest_load_id(store, "document_rank", "物件"),
                          rules_table_load_id=latest_load_id(store, "rules", "物件"), counts_json=None)
    issues: list[str] = []

    def issue(kind: str, subjects: list[str], facts: dict, basis: dict | None = None, proposal: dict | None = None):
        iid = store.insert("issue", recorded_by, check_run_id=run_id, identity_run_id=None, condition_check_id=None, kind=kind,
                           severity=_severity(rules, kind), subject_ids_json=dumps(subjects), basis_json=dumps(basis or {}),
                           facts_json=dumps(facts), proposal_json=dumps(proposal) if proposal else None)
        for code, label, effect in OPTIONS.get(kind, []):
            store.insert("issue_option", recorded_by, issue_id=iid, code=code, label=label, effect_json=dumps(effect))
        issues.append(iid)
        return iid

    # 名前がない空間 (B-12)
    for eid in elements:
        if kinds[eid] != "部屋":
            continue
        if not any(_value(store, project, eid, a, interpretation_id) not in (None, "") for a in NAME_ATTRIBUTES):
            issue("名前がない空間", [eid], {"note": "閉じた空間に名前の言い分がない。黙って名前を付けない（決定 Q42）"})

    # walls: partners and extent (C-2e)
    for eid in elements:
        if kinds[eid] != "壁":
            continue
        facts = wall_range_facts(store, project, eid, interpretation_id)
        if facts["partners"] == 0:
            issue("境界の相手がない壁", [eid], {"note": "どの空間の境界の相手にもなっていない（腰壁・袖壁・塀かもしれない。決定 2）"})
        elif facts["outside_mm"] > gap:
            issue("壁が境界の外に出ている", [eid], facts, proposal={"kind": "図面の修正案", "text": "壁の範囲を境界の区間の合併に合わせる"})

    # physical boundaries: uncovered parts (例11 case 3)
    for eid in elements:
        if kinds[eid] != "空間の境界":
            continue
        if _value(store, project, eid, "境界の種類", interpretation_id) != "物理的":
            continue
        pi = partner_intervals(store, project, eid, interpretation_id, gap)
        if pi["segment"] is None:
            continue
        total = (0.0, geometry.length(pi["segment"]))
        uncovered = geometry.gaps(total, [ov for _, ov in pi["walls"] + pi["openings"]], gap)
        if uncovered:
            issue("壁が途中で終わる", [eid] + pi["partners"],
                  {"uncovered_intervals_mm": [[a, b] for a, b in uncovered], "boundary_length_mm": total[1],
                   "walls": [[p, list(ov)] for p, ov in pi["walls"]], "openings": [[p, list(ov)] for p, ov in pi["openings"]]})

    # doors: the tag must be in a door schedule (C-5)
    schedules = [r["id"] for r in store.all(
        "select distinct v.id from source_version v join source s on s.id=v.source_id join source_attribute a on a.source_id=s.id "
        "where a.attribute='図面の種類' and a.value='建具表'")]
    for eid in elements:
        if kinds[eid] != "建具":
            continue
        tag = _value(store, project, eid, "符号", interpretation_id)
        if tag in (None, ""):
            continue
        found = False
        for vid in schedules:
            if store.one("select 1 from clue where source_version_id=? and kind='ROW' and instr(coalesce(text_raw,''), ?) > 0", vid, str(tag)):
                found = True
                break
        if not found:
            issue("建具表にない符号", [eid], {"符号": tag, "note": "建具表に行がない。建具の種類は AI の提案のまま、承認まで数えない（決定 Q12）",
                                        "建具表の版": schedules})

    # names not in the CSV lists (J-5)
    for what, name, subject in unknown_names or []:
        issue("知らない名前", [s for s in [subject] if s], {"what": what, "name": name})

    store.insert("run_summary", recorded_by, kind="提案の照らし", counts_json=dumps({"check_run_id": run_id, "issues": len(issues)}))
    return run_id, issues


# ---------------------------------------------------------------------- stage 4: after the batch approval of moves (例1)
FOLLOW_KIND = "壁芯は部屋割り線に従う"


def _follow_in_force(store: Store) -> bool:
    """An approved assumption 壁芯は部屋割り線に従う = 従う, not overridden by a later approved 従わない (level 3).
    (The scope of a level-3 exception is read in stage 5; here any approved 従わない on the wall stops the check.)"""
    from btruth.effective import item_status
    found = False
    for a in store.all("select a.id, a.value_json from assumption a where a.kind=? order by a.rowid", FOLLOW_KIND):
        item = store.one("select id from interpretation_item where assumption_id=?", a["id"])
        if item and item_status(store, item["id"]) == "承認済み":
            found = loads(a["value_json"]) == "従う"
    return found


def check_after_moves(store: Store, project: ProjectFolder, run_id: str | None, recorded_by: str) -> tuple[str, list[str]]:
    """The check that runs after moves are approved (design 例1, C-8: reads only, writes a check_run and issues).
    For each approved wall whose partner boundaries lie on a parallel line at another place, one issue
    壁と境界のずれ (one per wall, not one per boundary: expected_diff.md), with the two options. The expected
    position is not stored (B-9, B-10); only the offset goes to facts."""
    from btruth.effective import approved_elements_by_kind, effective_value, open_issues, relations_to
    rules = effective_rules(store, project)
    tol = float(rules.get("same_position_mm", "0.1"))
    tol_deg = float(rules.get("same_angle_deg", "0.01"))
    run = store.insert("check_run", recorded_by, trigger="移動の承認の後", scope_json=dumps({"identity_run_id": run_id}),
                       authority_table_load_id=latest_load_id(store, "authority", "物件"),
                       rank_table_load_id=latest_load_id(store, "document_rank", "物件"),
                       rules_table_load_id=latest_load_id(store, "rules", "物件"), counts_json=None)
    issues: list[str] = []
    if not _follow_in_force(store):
        store.insert("run_summary", recorded_by, kind="移動の承認の後の照らし",
                     counts_json=dumps({"check_run_id": run, "issues": 0, "note": "壁芯は部屋割り線に従う、の前提が承認されていない"}))
        store.commit()
        return run, issues
    already = {(i["kind"], frozenset(i["subject_ids"])) for i in open_issues(store, project)}
    import math
    for wall in approved_elements_by_kind(store, project).get("壁", []):
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
            d_ang = abs((ang(ws) - ang(bs) + 90.0) % 180.0 - 90.0)
            if d_ang > tol_deg:
                continue
            d0, d1 = geometry.distance_to_line(ws, bs[0]), geometry.distance_to_line(ws, bs[1])
            if min(d0, d1) > tol:
                off.append((r["from_element_id"], max(d0, d1)))
        if not off:
            continue
        subjects = [wall] + [b for b, _ in off]
        if ("壁と境界のずれ", frozenset(subjects)) in already:
            continue
        iid = store.insert("issue", recorded_by, check_run_id=run, identity_run_id=run_id, condition_check_id=None,
                           kind="壁と境界のずれ", severity=_severity(rules, "壁と境界のずれ"), subject_ids_json=dumps(subjects),
                           basis_json=dumps({"前提": FOLLOW_KIND, "壁の芯線": w.value, "claim_id": w.claim_id}),
                           facts_json=dumps({"ずれ_mm": max(d for _, d in off), "境界ごと": [[b, d] for b, d in off],
                                             "note": "期待の位置は保存しない（B-9、B-10）。壁の採用は書かない"}),
                           proposal_json=dumps({"kind": "図面の修正案", "text": "壁芯線を境界線の位置へ（「境界線に合わせる」を選んだとき）"}))
        for code, label, effect in OPTIONS["壁と境界のずれ"]:
            store.insert("issue_option", recorded_by, issue_id=iid, code=code, label=label, effect_json=dumps(effect))
        issues.append(iid)
    store.insert("run_summary", recorded_by, kind="移動の承認の後の照らし", counts_json=dumps({"check_run_id": run, "issues": len(issues)}))
    store.commit()
    return run, issues
