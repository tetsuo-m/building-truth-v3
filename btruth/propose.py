"""Registering a proposal (design E-2, E-3): the JSON an agent writes becomes rows of the vessel.

The flow (B-2, B-3, B-4): the agent (Claude Code, the rule reader, a future specialist) writes a JSON
file; `btruth propose` reads it, gives ids, runs the rule checks (E-3) and records every item — the
rejected ones too, with the reason (v2 Q52). Nothing here approves anything (G-1): every claim is an
observation (mode=観測) and every item waits for a person's review.

The JSON (see .claude/skills/read-drawing/SKILL.md for the agent's instructions):
  {
    "agent": {"name", "kind", "model", "version", "instructions_sha256"},
    "source_versions": ["平面図@1", ...],        # the versions that were read (name@seq or id)
    "summary": "...", "scope": {...},
    "assumptions": [{"ref", "level", "kind", "value", "confidence", "scope", "reason", "evidence": [..]}],
    "elements": [{"ref", "kind", "reason", "confidence", "evidence": [..], "claims": [{"attribute", "value",
                  "unit", "confidence", "statement_kind", "source", "evidence": [..]}]}],
    "relations": [{"ref", "kind", "from", "to", "role", "reason", "confidence", "evidence": [..]}],
    "claims": [{"subject", "attribute", "value", ...}],      # claims on existing elements
    "unreadable": [{"clue", "reason"}]                        # clues the agent could not explain (B-3)
  }
  Clue references: "平面図@1#13" (source name @ version seq # clue seq), or {"id": "<uuid>"}.
  Element references: "ref" within this proposal, {"id": "<uuid or prefix>"} for an existing element,
  {"find": {"kind": "階", "name": "1階"}} for an existing approved element by kind and name.
  Evidence: {"clue": <clue ref>, "role": "主の根拠|補助|凡例|...", "reason"} or {"element": <element ref>, "role": "凡例"}.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from btruth import geometry
from btruth.common import dumps, loads, new_id, sha256_of
from btruth.effective import (proposed_kind_of, STATUS_APPROVED, STATUS_DEFAULT, _kind_of, effective_value, find_element,
                              is_approved_element, relations_from, relations_to, element_status, STATUS_REJECTED,
                              STATUS_RULE_REJECTED)
from btruth.project import ProjectFolder
from btruth.store import Store
from btruth.tables import effective_rows, effective_rules, load_tables

PASSED = "通った"
REJECTED = "はじかれた"
EVIDENCE_ELEMENT_KINDS_OK = {"記号の定義"}       # an element may be evidence only as a legend (K)
ONE_PER_FROM = {"含む": "含む は要素ごとに一本（決定 10）", "くり抜く": "くり抜く は開口ごとに一本（決定 11）"}


class ProposalError(Exception):
    """The proposal as a whole cannot be registered (bad shape, unknown source version)."""


@dataclass
class RegisterResult:
    interpretation_id: str
    agent_id: str
    check_run_id: str | None = None
    element_ids: dict = field(default_factory=dict)
    relation_ids: dict = field(default_factory=dict)
    assumption_ids: dict = field(default_factory=dict)
    claim_ids: list = field(default_factory=list)
    items: list = field(default_factory=list)
    issues: list = field(default_factory=list)
    unknown_names: list = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for i in self.items if i["status"] == PASSED)

    @property
    def rejected(self) -> int:
        return sum(1 for i in self.items if i["status"] == REJECTED)


def load_proposal(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


# ---------------------------------------------------------------------- resolving references
def resolve_version(store: Store, project_id: str, ref) -> str | None:
    if isinstance(ref, dict):
        ref = ref.get("id")
    if not isinstance(ref, str):
        return None
    if "@" in ref:
        name, seq = ref.rsplit("@", 1)
        try:
            row = store.one("select v.id from source_version v join source s on s.id=v.source_id "
                            "where s.project_id=? and s.name=? and v.seq=?", project_id, name, int(seq))
        except ValueError:
            return None
        return row["id"] if row else None
    rows = store.all("select id from source_version where id like ?", ref + "%")
    return rows[0]["id"] if len(rows) == 1 else None


class _Resolver:
    def __init__(self, store: Store, project: ProjectFolder, project_id: str):
        self.store, self.project, self.project_id = store, project, project_id
        self._clues: dict = {}

    def clue(self, ref) -> str | None:
        if isinstance(ref, dict):
            if ref.get("id"):
                rows = self.store.all("select id from clue where id like ?", str(ref["id"]) + "%")
                return rows[0]["id"] if len(rows) == 1 else None
            version, seq = ref.get("version"), ref.get("seq")
        elif isinstance(ref, str) and "#" in ref:
            version, seq = ref.rsplit("#", 1)
        else:
            return None
        try:
            seq = int(seq)
        except (TypeError, ValueError):
            return None
        vid = resolve_version(self.store, self.project_id, version)
        if vid is None:
            return None
        key = (vid, seq)
        if key not in self._clues:
            row = self.store.one("select id from clue where source_version_id=? and seq=?", vid, seq)
            self._clues[key] = row["id"] if row else None
        return self._clues[key]

    def existing_element(self, ref: dict) -> str | None:
        if ref.get("id"):
            rows = self.store.all("select id from element where id like ?", str(ref["id"]) + "%")
            return rows[0]["id"] if len(rows) == 1 else None
        find = ref.get("find")
        if isinstance(find, dict) and find.get("kind"):
            keys = {k: v for k, v in find.items() if k not in ("kind", "name")}
            return find_element(self.store, self.project, find["kind"], find.get("name"), keys or None)
        return None


# ---------------------------------------------------------------------- registration
def register_proposal(store: Store, project: ProjectFolder, proposal: dict, recorded_by: str,
                      instructions_path: Path | None = None) -> RegisterResult:
    if not isinstance(proposal, dict) or "elements" not in proposal and "claims" not in proposal:
        raise ProposalError("提案の JSON に elements も claims もありません")
    load_tables(store, project, recorded_by=recorded_by)
    rules = effective_rules(store, project)
    tol = float(rules.get("same_position_mm", "0.1"))
    gap = float(rules.get("gap_tol_mm", "50"))
    project_id = store.project_id()
    res = _Resolver(store, project, project_id)

    # the versions that were read (E-2); unknown ones stop the whole proposal
    version_ids = []
    for ref in proposal.get("source_versions") or []:
        vid = resolve_version(store, project_id, ref)
        if vid is None:
            raise ProposalError(f"版が見つかりません: {ref}")
        version_ids.append(vid)

    # the agent (D-6); the fingerprint of the instructions it followed (E-1)
    a = dict(proposal.get("agent") or {})
    sha = sha256_of(Path(instructions_path)) if instructions_path else a.get("instructions_sha256")
    agent = store.one("select id from agent where name=? and coalesce(kind,'')=? and coalesce(version,'')=? "
                      "and coalesce(instructions_sha256,'')=?", a.get("name") or "（名前なし）", a.get("kind") or "",
                      a.get("version") or "", sha or "")
    agent_id = agent["id"] if agent else store.insert("agent", recorded_by, name=a.get("name") or "（名前なし）",
                                                      kind=a.get("kind"), model=a.get("model"), version=a.get("version"),
                                                      instructions_sha256=sha)

    # ids first (rows are appended only, so premise_json must be known before the interpretation row)
    elements = list(proposal.get("elements") or [])
    relations = list(proposal.get("relations") or [])
    assumptions = list(proposal.get("assumptions") or [])
    standalone = list(proposal.get("claims") or [])
    unreadable = list(proposal.get("unreadable") or [])
    el_ids = {e["ref"]: new_id() for e in elements if e.get("ref")}
    rel_ids = {r.get("ref") or f"relation-{i}": new_id() for i, r in enumerate(relations)}
    as_ids = {x.get("ref") or f"assumption-{i}": new_id() for i, x in enumerate(assumptions)}
    el_kind = {e["ref"]: e.get("kind") for e in elements if e.get("ref")}

    interp_id = store.insert("interpretation", recorded_by, source_version_ids_json=dumps(version_ids), agent_id=agent_id,
                             scope_json=dumps(proposal.get("scope") or {"kind": "全体"}),
                             premise_json=dumps(list(as_ids.values())), summary=proposal.get("summary"))
    result = RegisterResult(interpretation_id=interp_id, agent_id=agent_id, element_ids=el_ids, relation_ids=rel_ids,
                            assumption_ids=as_ids)
    known_kinds = {r["kind"] for r in effective_rows(store, project, "element_kinds")}
    known_attrs = {(r["attribute"], r["applies_to"]) for r in effective_rows(store, project, "attributes")}
    relation_kinds = {r["kind"]: r for r in effective_rows(store, project, "relation_kinds")}
    rejected_refs: set[str] = set()

    def element_ref(ref) -> tuple[str | None, str | None]:
        """(element id, element kind) for a reference; (None, None) if it cannot be resolved."""
        if isinstance(ref, str):
            if ref in el_ids:
                return el_ids[ref], el_kind.get(ref)
            return None, None
        if isinstance(ref, dict):
            eid = res.existing_element(ref)
            return (eid, _kind_of(store, eid) or proposed_kind_of(store, eid)) if eid else (None, None)
        return None, None

    def resolve_evidence(evs) -> tuple[list[dict], list[str]]:
        """[{clue_id|element_ref_id, role, reason}], [problems]"""
        out, problems = [], []
        for e in evs or []:
            if not isinstance(e, dict):
                problems.append(f"根拠の形が違う: {e!r}")
                continue
            if "clue" in e:
                cid = res.clue(e["clue"])
                if cid is None:
                    problems.append(f"参照した手掛かりがない: {e['clue']}")
                else:
                    out.append({"clue_id": cid, "element_ref_id": None, "role": e.get("role") or "主の根拠", "reason": e.get("reason")})
            elif "element" in e:
                eid, kind = element_ref(e["element"])
                if eid is None:
                    problems.append(f"参照した要素がない: {e['element']}")
                elif not (is_approved_element(store, eid) or kind in EVIDENCE_ELEMENT_KINDS_OK):
                    problems.append("根拠にできる要素は、承認済みの要素と凡例（記号の定義）だけ（根拠の循環を防ぐ。C-8）")
                else:
                    out.append({"clue_id": None, "element_ref_id": eid, "role": e.get("role") or "凡例", "reason": e.get("reason")})
            else:
                problems.append(f"根拠に clue も element もない: {e!r}")
        return out, problems

    def write_item(kind: str, status: str, reason: str | None, confidence, rule_reason: str | None, rules_checked: list,
                   evidence: list[dict], ref: str | None = None, **ids) -> str:
        item_id = store.insert("interpretation_item", recorded_by, interpretation_id=interp_id, kind=kind, reason=reason,
                               confidence=confidence, rule_check_status=status, rule_check_reason=rule_reason, **ids)
        for ev in evidence:
            store.insert("interpretation_evidence", recorded_by, item_id=item_id, clue_id=ev["clue_id"],
                         element_ref_id=ev["element_ref_id"], role=ev["role"], reason=ev["reason"])
        for rule, ok, detail in rules_checked:
            store.insert("rule_check", recorded_by, interpretation_item_id=item_id, rule=rule,
                         result=PASSED if ok else REJECTED, detail_json=dumps(detail) if detail is not None else None)
        result.items.append({"item_id": item_id, "ref": ref, "kind": kind, "status": status, "reason": rule_reason, **ids})
        return item_id

    def claim_source(claim: dict, evidence: list[dict]) -> str | None:
        if claim.get("source"):
            return resolve_version(store, project_id, claim["source"])
        for ev in evidence:
            if ev["clue_id"]:
                return store.scalar("select source_version_id from clue where id=?", ev["clue_id"])
        return version_ids[0] if version_ids else None

    def write_claim(subject_kind: str, subject_id: str, claim: dict, applies_kind: str | None) -> str | None:
        attribute = claim.get("attribute")
        if not attribute or "value" not in claim:
            return None
        if applies_kind and (attribute, "*") not in known_attrs and (attribute, applies_kind) not in known_attrs:
            result.unknown_names.append(("attribute", f"{attribute}（{applies_kind}）", subject_id))
        evidence, problems = resolve_evidence(claim.get("evidence"))
        cid = store.insert("claim", recorded_by, subject_kind=subject_kind, subject_id=subject_id, attribute=attribute,
                           value_json=dumps(claim["value"]), unit=claim.get("unit"), mode="観測",
                           statement_kind=claim.get("statement_kind") or "記述",
                           source_version_id=claim_source(claim, evidence), interpretation_id=interp_id,
                           review_id=None, agent_id=agent_id, confidence=claim.get("confidence"))
        for ev in evidence:
            if ev["clue_id"]:
                store.insert("claim_evidence", recorded_by, claim_id=cid, clue_id=ev["clue_id"], role=ev["role"], reason=ev["reason"])
        result.claim_ids.append(cid)
        return cid

    # --- assumptions (F-1)
    for i, x in enumerate(assumptions):
        ref = x.get("ref") or f"assumption-{i}"
        evidence, problems = resolve_evidence(x.get("evidence"))
        ok = not problems
        aid = as_ids[ref]
        store.insert("assumption", recorded_by, id=aid, level=x.get("level"), scope_json=dumps(x.get("scope")) if x.get("scope") is not None else None,
                     kind=x.get("kind"), value_json=dumps(x.get("value")), confidence=x.get("confidence"),
                     created_by_interpretation_id=interp_id, review_id=None)
        for ev in evidence:
            if ev["clue_id"]:
                store.insert("assumption_evidence", recorded_by, assumption_id=aid, clue_id=ev["clue_id"], role=ev["role"], reason=ev["reason"])
        write_item("前提", PASSED if ok else REJECTED, x.get("reason"), x.get("confidence"),
                   "；".join(problems) if problems else None,
                   [("参照した手掛かりが存在する", ok, {"problems": problems})], evidence, ref=ref, assumption_id=aid)

    # --- elements
    approved_signatures = _approved_signatures(store)
    seen_in_proposal: dict = {}
    bounds_target_of: dict = {}          # element ref -> the space it bounds (for the duplicate signature)
    for r in relations:
        if r.get("kind") == "区切る" and isinstance(r.get("from"), str):
            bounds_target_of[r["from"]] = element_ref(r.get("to"))[0]
    element_segments: dict = {}
    for e in elements:
        ref = e.get("ref")
        kind = e.get("kind")
        checks: list = []
        problems: list[str] = []
        if not ref or not kind:
            problems.append("ref と kind が要る")
        evidence, ev_problems = resolve_evidence(e.get("evidence"))
        problems += ev_problems
        checks.append(("参照した要素・手掛かり・凡例が存在する", not ev_problems, {"problems": ev_problems}))
        if kind and kind not in known_kinds:
            result.unknown_names.append(("kind", kind, el_ids.get(ref)))
        # duplicate of an approved element: same kind, same evidence clues, same bounded space (例6, B-5)
        clue_set = frozenset(ev["clue_id"] for ev in evidence if ev["clue_id"])
        sig = (kind, clue_set, bounds_target_of.get(ref))
        dup_ok = True
        if clue_set and sig in approved_signatures:
            dup_ok = False
            problems.append(f"承認済みの要素と根拠がまったく同じ要素を作り直している（{approved_signatures[sig][:8]}…）")
        checks.append(("承認済みの要素と根拠がまったく同じ要素を作り直していない", dup_ok, {"approved": approved_signatures.get(sig)}))
        # the same clues as another element of the same kind in this proposal, with the same claims
        claim_sig = dumps(sorted((c.get("attribute"), dumps(c.get("value"))) for c in e.get("claims") or [] if isinstance(c, dict)))
        twin_key = (kind, clue_set, claim_sig)
        twin_ok = True
        if clue_set and twin_key in seen_in_proposal:
            twin_ok = False
            problems.append(f"同じ手掛かりを同じ種類の要素で二重に数えている（{seen_in_proposal[twin_key]}）")
        else:
            seen_in_proposal[twin_key] = ref
        checks.append(("同じ手掛かりを同じ種類の要素で二重に数えない", twin_ok, None))
        # a room's boundaries must close (E-3: 輪郭が閉じる、面積がゼロでない)
        if kind == "部屋":
            segs = []
            for r in relations:
                if r.get("kind") == "区切る" and r.get("to") == ref and isinstance(r.get("from"), str):
                    b = next((x for x in elements if x.get("ref") == r["from"]), None)
                    if b:
                        s = next((geometry.segment(c.get("value")) for c in b.get("claims") or [] if c.get("attribute") == "線分"), None)
                        if s:
                            segs.append((loads(dumps(r.get("role") or {})).get("順") or 0, s))
            if segs:
                segs.sort(key=lambda x: x[0])
                ring = geometry.ring_from_ordered([s for _, s in segs], tol) or geometry.chain([s for _, s in segs], tol)
                closed = ring is not None and abs(geometry.polygon_area(ring)) > tol
                checks.append(("輪郭が閉じる・面積がゼロでない", closed, {"boundaries": len(segs)}))
                if not closed:
                    problems.append("部屋の境界が閉じた輪郭を作らない")
            else:
                checks.append(("輪郭が閉じる・面積がゼロでない", True, {"boundaries": 0, "note": "境界の提案なし"}))
        status = PASSED if not problems else REJECTED
        eid = el_ids.get(ref) or new_id()
        store.insert("element", recorded_by, id=eid, project_id=project_id, created_by_interpretation_id=interp_id)
        write_claim("element", eid, {"attribute": "種類", "value": kind, "confidence": e.get("confidence")}, None)
        for c in e.get("claims") or []:
            if isinstance(c, dict):
                write_claim("element", eid, c, kind)
                if c.get("attribute") in ("線分", "芯線"):
                    s = geometry.segment(c.get("value"))
                    if s:
                        element_segments[ref] = s
        write_item("要素を作る", status, e.get("reason"), e.get("confidence"), "；".join(problems) if problems else None,
                   checks, evidence, ref=ref, element_id=eid)
        if status == REJECTED:
            rejected_refs.add(ref)

    # --- relations
    taken: dict[tuple, str] = {}      # (kind, from element id) -> relation ref already holding the one allowed
    for i, r in enumerate(relations):
        ref = r.get("ref") or f"relation-{i}"
        kind = r.get("kind")
        checks, problems = [], []
        fid, fkind = element_ref(r.get("from"))
        tid, tkind = element_ref(r.get("to"))
        if fid is None:
            problems.append(f"つながりの元が見つからない: {r.get('from')!r}")
        if tid is None:
            problems.append(f"つながりの先が見つからない: {r.get('to')!r}")
        if isinstance(r.get("from"), str) and r.get("from") in rejected_refs:
            problems.append(f"つながりの元の提案がはじかれた: {r.get('from')}")
        if isinstance(r.get("to"), str) and r.get("to") in rejected_refs:
            problems.append(f"つながりの先の提案がはじかれた: {r.get('to')}")
        checks.append(("参照した要素が存在する", not problems, {"from": fid, "to": tid}))
        evidence, ev_problems = resolve_evidence(r.get("evidence"))
        problems += ev_problems
        rk = relation_kinds.get(kind)
        if rk is None:
            result.unknown_names.append(("relation_kind", kind, None))
        else:
            fk, tk = (rk.get("from_kinds") or "*").split("+"), (rk.get("to_kinds") or "*").split("+")
            if fkind and "*" not in fk and fkind not in fk:
                result.unknown_names.append(("relation_from", f"{kind} の元が {fkind}", fid))
            if tkind and "*" not in tk and tkind not in tk:
                result.unknown_names.append(("relation_to", f"{kind} の先が {tkind}", tid))
        if kind in ONE_PER_FROM and fid is not None:
            key = (kind, fid)
            already = key in taken or bool(relations_from(store, fid, kind, include_pending=True))
            checks.append((ONE_PER_FROM[kind], not already, {"existing": taken.get(key)}))
            if already:
                problems.append(ONE_PER_FROM[kind] + "。二本目ははじく")
        if kind == "境界の相手" and fid is not None and tid is not None:
            bseg = element_segments.get(r.get("from")) if isinstance(r.get("from"), str) else _segment_of(store, project, fid, "線分")
            ok, detail = _partner_touches_boundary(store, project, bseg, r.get("to"), tid, tkind, element_segments, gap, relations, elements)
            checks.append(("境界の相手の壁・開口が境界の線分に重なる位置にある", ok, detail))
            if not ok:
                problems.append("境界の相手が、境界の線分に重なる位置にない（区間は照らしで計算。C-2c）")
        if kind == "向かい合う" and fid is not None and tid is not None:
            a = element_segments.get(r.get("from")) if isinstance(r.get("from"), str) else _segment_of(store, project, fid, "線分")
            b = element_segments.get(r.get("to")) if isinstance(r.get("to"), str) else _segment_of(store, project, tid, "線分")
            ok = bool(a and b and geometry.overlap_on(a, b, gap))
            checks.append(("向かい合う境界は同じ線分の上にある", ok, None))
            if not ok:
                problems.append("向かい合う境界が同じ線分の上にない")
        status = PASSED if not problems else REJECTED
        rid = rel_ids[ref]
        store.insert("relation", recorded_by, id=rid, kind=kind, from_element_id=fid, to_element_id=tid,
                     role_json=dumps(r["role"]) if r.get("role") is not None else None, created_by_interpretation_id=interp_id)
        if status == PASSED and kind in ONE_PER_FROM and fid is not None:
            taken[(kind, fid)] = ref
        write_item("つながりを作る", status, r.get("reason"), r.get("confidence"), "；".join(problems) if problems else None,
                   checks, evidence, ref=ref, relation_id=rid)

    # --- claims on existing (or proposed) elements
    for i, c in enumerate(standalone):
        sid, skind = element_ref(c.get("subject"))
        problems = [] if sid else [f"言い分の主体が見つからない: {c.get('subject')!r}"]
        if sid:
            cid = write_claim("element", sid, c, skind)
            evidence, ev_problems = resolve_evidence(c.get("evidence"))
            problems += ev_problems
        else:
            cid, evidence = None, []
        status = PASSED if not problems else REJECTED
        write_item("言い分", status, c.get("reason"), c.get("confidence"), "；".join(problems) if problems else None,
                   [("参照した要素・手掛かりが存在する", status == PASSED, {"problems": problems})], evidence,
                   ref=c.get("ref"), claim_id=cid)

    # --- clues the agent could not explain (B-3): kept as 読めない items so the report can show them apart
    for u in unreadable:
        cid = res.clue(u.get("clue")) if isinstance(u, dict) else None
        ok = cid is not None
        write_item("読めない", PASSED if ok else REJECTED, (u or {}).get("reason") if isinstance(u, dict) else None, None,
                   None if ok else f"参照した手掛かりがない: {(u or {}).get('clue')!r}",
                   [("参照した手掛かりが存在する", ok, None)],
                   [{"clue_id": cid, "element_ref_id": None, "role": "読めない", "reason": (u or {}).get("reason")}] if ok else [])

    # the light check at registration (I-2; the full one is stage 5): hand doubtful proposals to the person
    from btruth.checks import check_proposal
    result.check_run_id, result.issues = check_proposal(store, project, interp_id, recorded_by, result.unknown_names)
    store.insert("run_summary", recorded_by, kind="提案の登録", counts_json=dumps({
        "interpretation_id": interp_id, "items": len(result.items), "passed": result.passed, "rejected": result.rejected,
        "elements": len(elements), "relations": len(relations), "claims": len(result.claim_ids),
        "assumptions": len(assumptions), "unreadable": len(unreadable), "issues": len(result.issues)}))
    store.commit()
    return result


# ---------------------------------------------------------------------- helpers
def _approved_signatures(store: Store) -> dict:
    """(kind, frozenset of evidence clue ids, bounded space) -> element id, for approved elements (例6)."""
    out = {}
    for item in store.all("select id, element_id from interpretation_item where kind='要素を作る' and element_id is not null"):
        eid = item["element_id"]
        if not is_approved_element(store, eid):
            continue
        clues = frozenset(r["clue_id"] for r in store.all("select clue_id from interpretation_evidence where item_id=? and clue_id is not null", item["id"]))
        if not clues:
            continue
        bounds = relations_from(store, eid, "区切る")
        target = bounds[0]["to_element_id"] if bounds else None
        out[(_kind_of(store, eid), clues, target)] = eid
    return out


def _segment_of(store: Store, project: ProjectFolder, element_id: str, attribute: str):
    from btruth.effective import proposed_value
    v = effective_value(store, project, element_id, attribute)
    return geometry.segment(v.value) if v.present else geometry.segment(proposed_value(store, element_id, attribute))


def opening_segment(store: Store, project: ProjectFolder, opening_id: str, segments: dict | None = None,
                    proposal_relations: list | None = None, proposal_elements: list | None = None,
                    opening_ref: str | None = None):
    """The absolute extent of an opening from its wall-based 位置 and 幅 (C-2d: never stored)."""
    from btruth.effective import proposed_value
    pos = width = None
    wall_seg = None
    if proposal_elements is not None and opening_ref is not None:
        e = next((x for x in proposal_elements if x.get("ref") == opening_ref), None)
        if e:
            for c in e.get("claims") or []:
                if c.get("attribute") == "位置":
                    pos = c.get("value")
                if c.get("attribute") == "幅":
                    width = c.get("value")
        for r in proposal_relations or []:
            if r.get("kind") == "くり抜く" and r.get("from") == opening_ref:
                if isinstance(r.get("to"), str):
                    wall_seg = (segments or {}).get(r["to"])
                else:
                    wid = _Resolver(store, project, store.project_id()).existing_element(r["to"]) if isinstance(r.get("to"), dict) else None
                    wall_seg = _segment_of(store, project, wid, "芯線") if wid else None
    if pos is None:
        pos = effective_value(store, project, opening_id, "位置").value
        if pos is None:
            pos = proposed_value(store, opening_id, "位置")
    if width is None:
        width = effective_value(store, project, opening_id, "幅").value
        if width is None:
            width = proposed_value(store, opening_id, "幅")
    if wall_seg is None:
        for r in relations_from(store, opening_id, "くり抜く", include_pending=True):
            wall_seg = _segment_of(store, project, r["to_element_id"], "芯線")
            break
    if isinstance(pos, dict):
        pos = pos.get("壁基準", pos.get("位置"))
    try:
        pos, width = float(pos), float(width)
    except (TypeError, ValueError):
        return None
    if wall_seg is None:
        return None
    u = geometry._unit(wall_seg)
    a = (wall_seg[0][0] + u[0] * pos, wall_seg[0][1] + u[1] * pos)
    b = (wall_seg[0][0] + u[0] * (pos + width), wall_seg[0][1] + u[1] * (pos + width))
    return (a, b)


def _partner_touches_boundary(store, project, bseg, to_ref, tid, tkind, segments, gap, relations, elements):
    if bseg is None:
        return False, {"note": "境界の線分がない"}
    if tkind == "開口" or (isinstance(to_ref, str) and next((e for e in elements if e.get("ref") == to_ref and e.get("kind") == "開口"), None)):
        pseg = opening_segment(store, project, tid, segments, relations, elements, to_ref if isinstance(to_ref, str) else None)
    else:
        pseg = segments.get(to_ref) if isinstance(to_ref, str) else _segment_of(store, project, tid, "芯線")
    if pseg is None:
        return False, {"note": "相手の芯線（または開口の位置・幅）がない"}
    ov = geometry.overlap_on(bseg, pseg, gap)
    return ov is not None, {"overlap_mm": ov}
