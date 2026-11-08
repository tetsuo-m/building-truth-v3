"""Checking the conditions (design L-1, L-2): IDS specifications against the effective values only (B-9).

Applicability and requirements are read through the CSV lists: the entity through element_kinds.csv's ifc_class (a
建具 is IfcDoor or IfcWindow by its 建具の種類), a property through attributes.csv's ifc_pset / ifc_property, the
attributes Name and Tag through the name and the 符号. Results go to condition_check (with the check run or the
generation of the IFC it guards); what is not met (or cannot be judged) becomes an issue 条件を満たさない.
"""
from __future__ import annotations

import re

from btruth.common import dumps, loads
from btruth.effective import _kind_of, approved_elements_by_kind, effective_name, effective_value
from btruth.project import ProjectFolder
from btruth.store import Store
from btruth.tables import effective_rows


def ifc_class_of(store: Store, project: ProjectFolder, element_id: str) -> str | None:
    kind = _kind_of(store, element_id)
    if kind == "建具":
        k = effective_value(store, project, element_id, "建具の種類").value or ""
        return "IfcWindow" if "窓" in str(k) else "IfcDoor"
    for r in effective_rows(store, project, "element_kinds"):
        if r.get("kind") == kind:
            return (r.get("ifc_class") or "").strip() or None
    return None


def property_value(store: Store, project: ProjectFolder, element_id: str, pset: str, name: str):
    kind = _kind_of(store, element_id)
    for r in effective_rows(store, project, "attributes"):
        if r.get("ifc_pset") == pset and r.get("ifc_property") == name and r.get("applies_to") in (kind, "*"):
            v = effective_value(store, project, element_id, r["attribute"])
            if v.present:
                return v.value
    return None


def attribute_value(store: Store, project: ProjectFolder, element_id: str, name: str):
    if name == "Name":
        return effective_name(store, project, element_id)
    if name in ("Tag", "AxisTag"):
        v = effective_value(store, project, element_id, "符号", through_type=False)
        return v.value if v.present else None
    return None


def _matches(value, expected) -> bool:
    if expected is None:
        return True
    if value is None:
        return False
    if isinstance(expected, dict):
        if "enum" in expected:
            return str(value) in [str(x) for x in expected["enum"]]
        if "pattern" in expected:
            return re.fullmatch(expected["pattern"], str(value)) is not None
        if "range" in expected:
            try:
                x = float(value)
            except (TypeError, ValueError):
                return False
            r = expected["range"]
            return all((k != "minInclusive" or x >= float(v)) and (k != "maxInclusive" or x <= float(v)) and
                       (k != "minExclusive" or x > float(v)) and (k != "maxExclusive" or x < float(v)) for k, v in r.items())
    return str(value) == str(expected)


def _facet_value(store, project, eid, f):
    if f["facet"] == "property":
        return property_value(store, project, eid, f.get("propertySet"), f.get("baseName"))
    if f["facet"] == "attribute":
        return attribute_value(store, project, eid, f.get("name"))
    return None


def applies(store: Store, project: ProjectFolder, eid: str, app: dict) -> bool:
    ents = [str(e).upper() for e in app.get("entity") or [] if e]
    if ents and (ifc_class_of(store, project, eid) or "").upper() not in ents:
        return False
    for key in ("property", "attribute"):
        for f in app.get(key) or []:
            v = _facet_value(store, project, eid, dict(f, facet=key))
            if v is None or not _matches(v, f.get("value")):
                return False
    return True


def evaluate(store: Store, project: ProjectFolder, eid: str, requirements: list) -> tuple[str, list]:
    facts, result = [], "満たす"
    for f in requirements:
        if f["facet"] not in ("property", "attribute"):
            facts.append({"facet": f["facet"], "結果": "判定できない（この段では見ない切り口）"})
            result = "判定できない" if result == "満たす" else result
            continue
        v = _facet_value(store, project, eid, f)
        card = f.get("cardinality", "required")
        ok = (v is None) if card == "prohibited" else (v is not None and _matches(v, f.get("value"))) if card == "required" \
            else (v is None or _matches(v, f.get("value")))
        facts.append({"facet": f["facet"], "名前": f.get("baseName") or f.get("name"), "組": f.get("propertySet"),
                      "cardinality": card, "有効値": v, "結果": "満たす" if ok else "満たさない"})
        if not ok:
            result = "満たさない"
    return result, facts


def latest_conditions(store: Store, category: str | None = None) -> list:
    out = []
    for c in store.all("select c.*, v.seq, v.source_id from condition c join source_version v on v.id=c.source_version_id order by c.rowid"):
        latest = store.scalar("select max(seq) from source_version where source_id=?", c["source_id"])
        if c["seq"] == latest and (category is None or c["category"] == category):
            out.append(c)
    return out


def check_conditions(store: Store, project: ProjectFolder, recorded_by: str, category: str | None = None,
                     generation_id: str | None = None, check_run_id: str | None = None) -> list[dict]:
    """Every condition (of the latest version of its source) on the approved elements it applies to."""
    approved = [e for es in approved_elements_by_kind(store, project).values() for e in es]
    results = []
    for c in latest_conditions(store, category):
        if c["form"] != "ids":
            continue
        d = loads(c["ids_json"]) or {}
        for eid in approved:
            if not applies(store, project, eid, d.get("applicability") or {}):
                continue
            result, facts = evaluate(store, project, eid, d.get("requirements") or [])
            ccid = store.insert("condition_check", recorded_by, condition_id=c["id"], check_run_id=check_run_id,
                                generation_id=generation_id, subject_ids_json=dumps([eid]), result=result,
                                facts_json=dumps(facts), agent_id=None)
            results.append({"condition_id": c["id"], "element_id": eid, "result": result, "condition_check_id": ccid,
                            "name": d.get("name")})
            if result != "満たす":
                iid = store.insert("issue", recorded_by, check_run_id=check_run_id, identity_run_id=None, condition_check_id=ccid,
                                   kind="条件を満たさない", severity=c["severity"] or "要確認", subject_ids_json=dumps([eid]),
                                   basis_json=dumps({"condition_id": c["id"], "category": c["category"], "条件": d.get("name")}),
                                   facts_json=dumps({"条件": d.get("name"), "区分": c["category"], "結果": result, "切り口": facts}),
                                   proposal_json=None)
                for code, label in (("fix", "要素の値を直す（判断）"), ("allow", "このまま（受け渡しなら `btruth allow-ifc`）")):
                    store.insert("issue_option", recorded_by, issue_id=iid, code=code, label=label, effect_json="{}")
    store.commit()
    return results
