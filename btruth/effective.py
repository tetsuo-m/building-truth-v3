"""Reading the vessel: item status, element status, and the effective value (有効値; design D-1 改訂 6).

The effective value is never stored (decision Q1). For a subject and an attribute it is, in order:
  1. the latest adopted claim (mode=採用, written by a person's review). A recheck mark does not remove
     it; the value is returned with `recheck=True` (決定 9);
  2. otherwise an observation (mode=観測) whose interpretation item is approved: per source the latest
     approved version's value; among sources the primary source of rules/authority.csv; if that does
     not decide and the values differ → 決まらない (決定 10);
  3. otherwise the rule reader's observation of the default structure (既定の構成) — the only
     observation that counts without approval (決定 11);
  4. type and instance (決定 9): instance adopted → type adopted → observations; conflicting
     observations between type and instance → 決まらない.
Nothing here writes to the vessel.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from btruth import geometry
from btruth.common import loads
from btruth.project import ProjectFolder
from btruth.store import Store
from btruth.tables import effective_rows, effective_rules

DEFAULT_SUMMARY = "既定の構成"
APPROVE_ACTIONS = {"承認", "まとめて承認", "移動をまとめて承認"}
STATUS_APPROVED = "承認済み"
STATUS_DEFAULT = "既定"
STATUS_REJECTED = "却下"
STATUS_HELD = "保留"
STATUS_PENDING = "提案中"
STATUS_RULE_REJECTED = "はじかれた"
STATUS_MERGED = "同じ要素に統合"        # a proposed element found to be an existing one by the identity between sources (B-13)
NAME_ATTRIBUTES = ("名前", "室名", "室番号")


@dataclass
class EffectiveValue:
    value: Any = None
    status: str = "なし"            # 採用 / 承認済みの観測 / 既定の構成 / なし / 決まらない
    claim_id: str | None = None
    review_id: str | None = None
    recheck: bool = False
    via_type: str | None = None
    note: str = ""
    candidates: list = field(default_factory=list)

    @property
    def present(self) -> bool:
        return self.status in ("採用", "承認済みの観測", "既定の構成")


# ---------------------------------------------------------------------- item and element status
def _is_default_interpretation(store: Store, interpretation_id: str) -> bool:
    row = store.one("select i.summary, a.kind from interpretation i join agent a on a.id=i.agent_id where i.id=?",
                    interpretation_id)
    return bool(row) and row["summary"] == DEFAULT_SUMMARY and row["kind"] == "規則の読み手"


def merged_into(store: Store, element_id: str | None) -> str | None:
    """The existing element a proposed one was found to be (identity between sources, verdict 一致), if any."""
    if not element_id:
        return None
    row = store.one("select l.element_id from identity_link l join identity_run r on r.id=l.run_id where r.kind='出どころの間' "
                    "and l.new_element_id=? and l.verdict='一致' order by l.rowid desc limit 1", element_id)
    return row["element_id"] if row else None


def item_status(store: Store, item_id: str) -> str:
    item = store.one("select rule_check_status, interpretation_id, kind, element_id, relation_id from interpretation_item where id=?", item_id)
    if item is None:
        return "不明"
    if item["rule_check_status"] == STATUS_RULE_REJECTED:
        return STATUS_RULE_REJECTED
    if item["kind"] == "要素を作る" and merged_into(store, item["element_id"]):
        return STATUS_MERGED
    if item["relation_id"]:
        r = store.one("select from_element_id, to_element_id from relation where id=?", item["relation_id"])
        if r and (merged_into(store, r["from_element_id"]) or merged_into(store, r["to_element_id"])):
            return STATUS_MERGED
    if _is_default_interpretation(store, item["interpretation_id"]):
        return STATUS_DEFAULT
    latest = None
    for r in store.all("select rowid, target_kind, action, choice_json from review where "
                       "(target_kind='interpretation_item' and target_id=?) or "
                       "(target_kind in ('interpretation','identity_run') and instr(coalesce(choice_json,''), ?) > 0) "
                       "order by rowid", item_id, item_id):
        if r["target_kind"] != "interpretation_item":
            ids = (loads(r["choice_json"]) or {}).get("item_ids") or []
            if item_id not in ids:
                continue
        latest = r["action"]
    if latest is None:
        return STATUS_PENDING
    if latest in APPROVE_ACTIONS:
        return STATUS_APPROVED
    if latest == "却下":
        return STATUS_REJECTED
    if latest == "保留":
        return STATUS_HELD
    return STATUS_PENDING


def element_item(store: Store, element_id: str):
    return store.one("select id, interpretation_id, confidence, reason from interpretation_item "
                     "where element_id=? and kind='要素を作る' order by rowid limit 1", element_id)


def element_status(store: Store, element_id: str) -> str:
    item = element_item(store, element_id)
    return item_status(store, item["id"]) if item else "不明"


def is_approved_element(store: Store, element_id: str) -> bool:
    return element_status(store, element_id) in (STATUS_APPROVED, STATUS_DEFAULT)


def claim_item_id(store: Store, claim_row) -> str | None:
    """The item whose approval carries this claim: its own 言い分 item, else the 要素を作る / つながりを作る
    item of its subject within the same interpretation."""
    row = store.one("select id from interpretation_item where claim_id=?", claim_row["id"])
    if row:
        return row["id"]
    col = "element_id" if claim_row["subject_kind"] == "element" else "relation_id"
    row = store.one(f"select id from interpretation_item where {col}=? and interpretation_id=? "
                    "and kind in ('要素を作る','つながりを作る','既存の要素と同じ') order by rowid limit 1",
                    claim_row["subject_id"], claim_row["interpretation_id"])
    return row["id"] if row else None


def claim_status(store: Store, claim_row) -> str:
    item = claim_item_id(store, claim_row)
    if item is None:
        if claim_row["interpretation_id"] and _is_default_interpretation(store, claim_row["interpretation_id"]):
            return STATUS_DEFAULT
        return STATUS_PENDING
    return item_status(store, item)


def relation_status(store: Store, relation_id: str) -> str:
    row = store.one("select id from interpretation_item where relation_id=? order by rowid limit 1", relation_id)
    if row is None:
        return "不明"
    return item_status(store, row["id"])


def relations_from(store: Store, element_id: str, kind: str | None = None, approved_only: bool = True,
                   include_pending: bool = False) -> list:
    """Relations whose from-end is the element, without an end row (relation_end). `approved_only`
    keeps approved / default ones; `include_pending` also keeps proposals that are not rejected."""
    sql = ("select r.* from relation r where r.from_element_id=? and not exists "
           "(select 1 from relation_end e where e.relation_id=r.id)")
    params: list = [element_id]
    if kind:
        sql += " and r.kind=?"
        params.append(kind)
    out = []
    for r in store.all(sql + " order by r.rowid", *params):
        st = relation_status(store, r["id"])
        if st in (STATUS_APPROVED, STATUS_DEFAULT) or (include_pending and st in (STATUS_PENDING, STATUS_HELD)) \
                or not approved_only:
            out.append(r)
    return out


def relations_to(store: Store, element_id: str, kind: str | None = None, approved_only: bool = True,
                 include_pending: bool = False) -> list:
    sql = ("select r.* from relation r where r.to_element_id=? and not exists "
           "(select 1 from relation_end e where e.relation_id=r.id)")
    params: list = [element_id]
    if kind:
        sql += " and r.kind=?"
        params.append(kind)
    out = []
    for r in store.all(sql + " order by r.rowid", *params):
        st = relation_status(store, r["id"])
        if st in (STATUS_APPROVED, STATUS_DEFAULT) or (include_pending and st in (STATUS_PENDING, STATUS_HELD)) \
                or not approved_only:
            out.append(r)
    return out


# ---------------------------------------------------------------------- the effective value
def _kind_of(store: Store, subject_id: str) -> str | None:
    """The element's kind without going through the authority table (種類 has no authority row)."""
    adopted = store.one("select value_json from claim where subject_id=? and attribute='種類' and mode='採用' order by rowid desc limit 1",
                        subject_id)
    if adopted:
        return loads(adopted["value_json"])
    for c in store.all("select * from claim where subject_id=? and attribute='種類' and mode='観測' order by rowid desc", subject_id):
        if claim_status(store, c) in (STATUS_APPROVED, STATUS_DEFAULT):
            return loads(c["value_json"])
    return None


def proposed_kind_of(store: Store, subject_id: str) -> str | None:
    """The kind as proposed (approved or not) — for listings and screens."""
    k = _kind_of(store, subject_id)
    if k is not None:
        return k
    row = store.one("select value_json from claim where subject_id=? and attribute='種類' order by rowid desc limit 1", subject_id)
    return loads(row["value_json"]) if row else None


def _source_of_version(store: Store, version_id: str | None):
    if not version_id:
        return None
    return store.one("select v.seq, s.id as source_id, s.kind, s.name from source_version v join source s on s.id=v.source_id where v.id=?",
                     version_id)


def _source_kind_key(store: Store, source_id: str, source_kind: str | None) -> str:
    """`設計図:建築平面図` — the document class plus the drawing type attribute (J-2)."""
    dt = store.one("select value from source_attribute where source_id=? and attribute='図面の種類' order by rowid desc limit 1",
                   source_id)
    return f"{source_kind or ''}:{dt['value']}" if dt else (source_kind or "")


def _primary_source_kind(store: Store, project: ProjectFolder, kind: str | None, attribute: str) -> str | None:
    if kind is None:
        return None
    for row in effective_rows(store, project, "authority"):
        if row.get("element_kind") == kind and row.get("attribute") == attribute:
            return (row.get("primary_source_kind") or "").strip() or None
    return None


def _approved_observations(store: Store, subject_id: str, attribute: str) -> list[dict]:
    out = []
    for c in store.all("select * from claim where subject_id=? and attribute=? and mode='観測' order by rowid", subject_id, attribute):
        if c["statement_kind"] == "未決":          # 「〜を検討する」「次回確認」: no rank, no value (C-10)
            continue
        st = claim_status(store, c)
        if st != STATUS_APPROVED:
            continue
        src = _source_of_version(store, c["source_version_id"])
        out.append({"claim": c, "source_id": src["source_id"] if src else None, "seq": src["seq"] if src else 0,
                    "source_kind": src["kind"] if src else None, "value": loads(c["value_json"])})
    return out


def _pick_observation(store: Store, project: ProjectFolder, subject_id: str, attribute: str,
                      kind: str | None) -> EffectiveValue | None:
    """Step 2 of D-1: one approved observation per source (latest version), then the primary source."""
    obs = _approved_observations(store, subject_id, attribute)
    if not obs:
        return None
    per_source: dict = {}
    for o in obs:
        key = o["source_id"]
        cur = per_source.get(key)
        if cur is None or (o["seq"], o["claim"]["rowid"] if "rowid" in o["claim"].keys() else 0) >= \
                (cur["seq"], cur["claim"]["rowid"] if "rowid" in cur["claim"].keys() else 0):
            per_source[key] = o
    candidates = list(per_source.values())
    if len(candidates) == 1:
        c = candidates[0]
        return EffectiveValue(c["value"], "承認済みの観測", c["claim"]["id"])
    primary = _primary_source_kind(store, project, kind, attribute)
    if primary:
        for c in candidates:
            if c["source_id"] and _source_kind_key(store, c["source_id"], c["source_kind"]) == primary:
                return EffectiveValue(c["value"], "承認済みの観測", c["claim"]["id"], note="主の出どころ")
    values = {json.dumps(c["value"], sort_keys=True, ensure_ascii=False) for c in candidates}
    if len(values) == 1:
        c = candidates[0]
        return EffectiveValue(c["value"], "承認済みの観測", c["claim"]["id"], note="複数の出どころが一致")
    return EffectiveValue(None, "決まらない", note="複数の出どころの承認済みの観測が食い違い、主の出どころが決まらない",
                          candidates=[c["claim"]["id"] for c in candidates])


def _default_observation(store: Store, subject_id: str, attribute: str) -> EffectiveValue | None:
    for c in store.all("select * from claim where subject_id=? and attribute=? and mode='観測' order by rowid desc", subject_id, attribute):
        if c["interpretation_id"] and _is_default_interpretation(store, c["interpretation_id"]):
            return EffectiveValue(loads(c["value_json"]), "既定の構成", c["id"])
    return None


def _adopted(store: Store, subject_id: str, attribute: str) -> EffectiveValue | None:
    """The latest adopted claim. A recheck mark keeps it (recheck=True, 決定 9). When the person resolves a mark
    on it with 取り消す, the adoption ends (G-2) and nothing older is revived."""
    c = store.one("select * from claim where subject_id=? and attribute=? and mode='採用' order by rowid desc limit 1",
                  subject_id, attribute)
    if c is None:
        return None
    recheck = False
    if c["review_id"]:
        for m in store.all("select id from recheck_mark where review_id=?", c["review_id"]):
            resolved = store.one("select action from review where target_kind='recheck_mark' and target_id=? order by rowid desc limit 1",
                                 m["id"])
            if not resolved:
                recheck = True
            elif resolved["action"] == "取り消す":
                return None
    return EffectiveValue(loads(c["value_json"]), "採用", c["id"], c["review_id"], recheck)


def types_of(store: Store, element_id: str) -> list[str]:
    return [r["to_element_id"] for r in relations_from(store, element_id, "型である")]


OPENING_FROM_DOOR_TYPE = ("幅", "高さ")      # C-2d, authority.csv: 開口の幅・高さの主＝建具表（ふさぐ建具の型の値）


def filling_types(store: Store, opening_id: str) -> list[str]:
    """The types of the doors that fill an opening: 開口 ←ふさぐ 建具 →型である 建具の型 (C-2d)."""
    out = []
    for r in relations_to(store, opening_id, "ふさぐ"):
        for t in types_of(store, r["from_element_id"]):
            if t not in out:
                out.append(t)
    return out


def _opening_value(store: Store, project: ProjectFolder, subject_id: str, attribute: str) -> EffectiveValue | None:
    """The opening's own adoption is handled before this. Then: the door type's adoption, the door type's
    observation (the primary source: the door schedule), the opening's own observation (the drawing: secondary)."""
    types = filling_types(store, subject_id)
    if not types:
        return None
    for t in types:
        ta = _adopted(store, t, attribute)
        if ta:
            ta.via_type = t
            ta.note = "ふさぐ建具の型の採用"
            return ta
    for t in types:
        o = _pick_observation(store, project, t, attribute, _kind_of(store, t))
        if o is not None and o.present:
            o.via_type = t
            o.note = "主の出どころ（ふさぐ建具の型の値。C-2d）"
            return o
    return None


def effective_value(store: Store, project: ProjectFolder, subject_id: str, attribute: str,
                    through_type: bool = True) -> EffectiveValue:
    adopted = _adopted(store, subject_id, attribute)
    if adopted:
        return adopted
    if through_type and attribute in OPENING_FROM_DOOR_TYPE and _kind_of(store, subject_id) == "開口":
        via = _opening_value(store, project, subject_id, attribute)
        if via is not None:
            return via
    types = types_of(store, subject_id) if through_type else []
    for t in types:
        ta = _adopted(store, t, attribute)
        if ta:
            ta.via_type = t
            return ta
    kind = _kind_of(store, subject_id)
    own = _pick_observation(store, project, subject_id, attribute, kind)
    type_obs = []
    for t in types:
        o = _pick_observation(store, project, t, attribute, _kind_of(store, t))
        if o is not None:
            o.via_type = t
            type_obs.append(o)
    if own is not None and own.status == "決まらない":
        return own
    if own is not None and type_obs:
        for o in type_obs:
            if o.present and json.dumps(o.value, sort_keys=True) != json.dumps(own.value, sort_keys=True):
                return EffectiveValue(None, "決まらない", note="型と実物の観測が食い違う（決定 9）",
                                      candidates=[own.claim_id, o.claim_id])
        return own
    if own is not None:
        return own
    if type_obs:
        return type_obs[0]
    default = _default_observation(store, subject_id, attribute)
    if default:
        return default
    return EffectiveValue()


def effective_name(store: Store, project: ProjectFolder, element_id: str) -> str | None:
    for attribute in NAME_ATTRIBUTES:
        v = effective_value(store, project, element_id, attribute)
        if v.present and v.value not in (None, ""):
            return str(v.value)
    return None


def proposed_value(store: Store, element_id: str, attribute: str, interpretation_id: str | None = None):
    """The latest observation as proposed (approved or not), optionally within one interpretation."""
    if interpretation_id:
        row = store.one("select value_json from claim where subject_id=? and attribute=? and interpretation_id=? order by rowid desc limit 1",
                        element_id, attribute, interpretation_id)
    else:
        row = store.one("select value_json from claim where subject_id=? and attribute=? order by rowid desc limit 1",
                        element_id, attribute)
    return loads(row["value_json"]) if row else None


# ---------------------------------------------------------------------- collections
def approved_elements_by_kind(store: Store, project: ProjectFolder) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for e in store.all("select id from element order by rowid"):
        if is_approved_element(store, e["id"]):
            k = _kind_of(store, e["id"]) or "（種類なし）"
            out.setdefault(k, []).append(e["id"])
    return out


def find_element(store: Store, project: ProjectFolder, kind: str, name: str | None = None, keys: dict | None = None) -> str | None:
    """An approved or default element of the kind (and name, and key attributes such as 符号 = AD-1; B-11)."""
    for e in store.all("select id from element order by rowid"):
        if not is_approved_element(store, e["id"]) or _kind_of(store, e["id"]) != kind:
            continue
        if name is not None and effective_name(store, project, e["id"]) != name:
            continue
        if keys and any(effective_value(store, project, e["id"], a, through_type=False).value != v for a, v in keys.items()):
            continue
        return e["id"]
    return None


def boundaries_of_room(store: Store, project: ProjectFolder, room_id: str, include_pending: bool = False) -> list[str]:
    rels = relations_to(store, room_id, "区切る", include_pending=include_pending)
    def order(r):
        role = loads(r["role_json"]) or {}
        return (role.get("順") is None, role.get("順") or 0, r["rowid"] if "rowid" in r.keys() else 0)
    rels = sorted(rels, key=order)
    return [r["from_element_id"] for r in rels]


def room_ring(store: Store, project: ProjectFolder, room_id: str, tol: float | None = None) -> list | None:
    rules = effective_rules(store, project)
    tol = float(rules.get("same_position_mm", "0.1")) if tol is None else tol
    segs = []
    for b in boundaries_of_room(store, project, room_id):
        v = effective_value(store, project, b, "線分")
        s = geometry.segment(v.value) if v.present else None
        if s is None:
            return None
        segs.append(s)
    if not segs:
        return None
    return geometry.ring_from_ordered(segs, tol) or geometry.chain(segs, tol)


def room_area_m2(store: Store, project: ProjectFolder, room_id: str) -> float | None:
    ring = room_ring(store, project, room_id)
    if ring is None:
        return None
    return abs(geometry.polygon_area(ring)) / 1_000_000.0


def room_perimeter_m(store: Store, project: ProjectFolder, room_id: str) -> float | None:
    ring = room_ring(store, project, room_id)
    if ring is None:
        return None
    n = len(ring)
    return sum(geometry.length((ring[i], ring[(i + 1) % n])) for i in range(n)) / 1000.0


def _issue_condition_gone(store: Store, project: ProjectFolder, issue_row, subjects: list[str]) -> bool:
    """An issue whose condition no longer holds in the effective state is not open any more (決定 15: the
    issue is a record of its time; what is open is read against the current state). Stage 3 knows this
    for 名前がない空間: the room has an effective name, or is excluded (部屋として扱う = false)."""
    if issue_row["kind"] == "移動の承認待ち":
        ids = (loads(issue_row["facts_json"]) or {}).get("item_ids") or []
        return all(item_status(store, i) in (STATUS_APPROVED, STATUS_REJECTED) for i in ids)   # 保留 keeps it open (決定 15)
    if issue_row["kind"] == "名前がない空間":
        for s in subjects:
            if effective_name(store, project, s):
                return True
            v = effective_value(store, project, s, "部屋として扱う")
            if v.present and v.value is False:
                return True
    return False


CONSISTENCY_TRIGGERS = ("人の求め", "承認の後", "移動の承認の後", "取り込みの後")


def _later_check_scopes(store: Store) -> list[tuple[int, set]]:
    out = []
    for r in store.all("select rowid as rn, trigger, scope_json from check_run order by rowid"):
        if r["trigger"] in CONSISTENCY_TRIGGERS:
            out.append((r["rn"], set((loads(r["scope_json"]) or {}).get("elements") or [])))
    return out


def open_issues(store: Store, project: ProjectFolder) -> list[dict]:
    """Issues without a closing review (any review on the issue other than 保留 closes it; 決定 15), whose condition
    still holds, and not replaced by a later consistency check whose scope holds all their subjects (I-2, 決定 15:
    the latest check per scope; held issues and issues outside the scope stay open)."""
    out = []
    scopes = _later_check_scopes(store)
    for i in store.all("select rowid as rn, * from issue order by rowid"):
        reviews = store.all("select action from review where target_kind='issue' and target_id=? order by rowid", i["id"])
        if any(r["action"] != "保留" for r in reviews):
            continue
        subjects = loads(i["subject_ids_json"]) or []
        if not reviews and i["check_run_id"]:
            own = store.one("select rowid as rn from check_run where id=?", i["check_run_id"])
            if own and any(rn > own["rn"] and subjects and set(subjects) <= sc for rn, sc in scopes):
                continue
        if _issue_condition_gone(store, project, i, subjects):
            continue
        d = dict(i)
        d["subject_ids"] = subjects
        d["facts"] = loads(i["facts_json"]) or {}
        d["basis"] = loads(i["basis_json"]) or {}
        d["proposal"] = loads(i["proposal_json"])
        d["options"] = [dict(o) for o in store.all("select code, label, effect_json from issue_option where issue_id=? order by rowid", i["id"])]
        d["held"] = bool(reviews)
        out.append(d)
    return out
