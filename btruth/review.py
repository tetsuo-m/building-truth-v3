"""The review commands — the only code that writes `review` and `review_premise` (design G-1, CONCEPT D-3).

Rules enforced here, not promised:
  * terminal only (G-1 (b), (c)): `require_terminal` must pass before anything is written. The judgement
    needs stdin, stdout *and* stderr to be terminals and no AI-agent environment (CLAUDECODE,
    CLAUDE_CODE_ENTRYPOINT, AI_AGENT). Failure F-11: on Windows, a command run by Claude Code has a
    stdin that reports itself as a terminal, so a stdin-only check let the AI through.
  * the test override (environment variable BTRUTH_TEST_TERMINAL=ok) works only for a database under
    the system's temporary folder (pytest's tmp_path). A project database elsewhere ignores it
    (BRIEF step3 §3-4: the override must not be a way into the real database).
  * y/N after the listing (G-1 (c)): the caller passes `confirm(listing) -> bool`; the CLI prompts.
  * the check before approval (G-1, 決定 12): whatever an approved item points at (the opening a door
    fills, the wall an opening voids, the room a boundary bounds, the partner, the type, the storey) must
    be approved already or approved in the same review; otherwise ApprovalBlocked and nothing is written.
  * a decision that fixes a value writes the adopted claim (mode=採用) in the same transaction (D-1).
  * `reason` is the person's text; this module never invents one (F-3).
  * `review` rows are appended; the triggers of schema.py stop UPDATE / DELETE (G-1 (d)).
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Callable

from btruth.common import dumps, loads, new_id, now_iso
from btruth.effective import (STATUS_APPROVED, STATUS_DEFAULT, STATUS_PENDING, STATUS_REJECTED, STATUS_RULE_REJECTED,
                              effective_value, element_status, item_status, proposed_kind_of, effective_name, proposed_value,
                              relation_status)
from btruth.project import ProjectFolder
from btruth.store import Store
from btruth.tables import TABLE_KINDS, latest_load_id

AGENT_ENV = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "AI_AGENT")
OVERRIDE_ENV = "BTRUTH_TEST_TERMINAL"
# relations whose *target* must be approved before (or with) the source element (決定 12)
POINTING = {"ふさぐ", "くり抜く", "区切る", "境界の相手", "型である", "集める", "含む", "組み立てを持つ", "使う",
            "部品である", "属する", "載る", "貫通する", "参照する", "定義する", "層である"}
MOVE_ITEM_KIND = "既存の要素と同じ"           # an identity run's new position of an existing element (H-2)
RECHECK_CHOICES = ("保つ", "変える", "取り消す")   # G-2
TERMINAL_MESSAGE = ("承認・判断のコマンドは、人が打つ端末からだけ動きます（G-1 (b)）。この呼び出しは端末ではない"
                    "（stdin・stdout・stderr のどれかが端末でない、または AI エージェントの環境）ので、何も書きません。")


class NotATerminal(PermissionError):
    pass


class ApprovalBlocked(Exception):
    pass


# ---------------------------------------------------------------------- the terminal judgement
def _real_terminal() -> bool:
    if any(os.environ.get(k) for k in AGENT_ENV):
        return False
    try:
        return all(s is not None and hasattr(s, "isatty") and s.isatty() for s in (sys.stdin, sys.stdout, sys.stderr))
    except Exception:
        return False


def _under_tempdir(db_path: Path) -> bool:
    try:
        tmp = Path(tempfile.gettempdir()).resolve()
        Path(db_path).resolve().relative_to(tmp)
        return True
    except (ValueError, OSError):
        return False


def _override_active(db_path: Path) -> bool:
    return os.environ.get(OVERRIDE_ENV) == "ok" and _under_tempdir(db_path)


def is_terminal_for(db_path: Path) -> bool:
    """True when the confirmation commands may write to this database from here."""
    if _override_active(db_path):
        return True
    return _real_terminal()


def require_terminal(db_path: Path) -> None:
    if not is_terminal_for(db_path):
        raise NotATerminal(TERMINAL_MESSAGE)


def _confirm_default(db_path: Path) -> Callable[[str], bool]:
    if _override_active(db_path):
        return lambda listing: True
    return prompt_confirm


def prompt_confirm(listing: str) -> bool:
    print(listing)
    answer = input("確定しますか？ (y/N) ").strip().lower()
    return answer in ("y", "yes")


# ---------------------------------------------------------------------- writing review rows
def _write_review(store: Store, target_kind: str, target_id: str, action: str, choice: dict | None, reason: str | None,
                  reviewed_by: str, basis_source_version_id: str | None = None) -> str:
    rid = new_id()
    store.conn.execute(
        "insert into review (id, recorded_at, recorded_by, target_kind, target_id, action, choice_json, reason, "
        "basis_source_version_id, reviewed_by, signature, signer_key_id) values (?,?,?,?,?,?,?,?,?,?,NULL,NULL)",
        (rid, now_iso(), reviewed_by, target_kind, target_id, action, dumps(choice) if choice is not None else None,
         reason, basis_source_version_id, reviewed_by))
    return rid


def _write_premises(store: Store, review_id: str, premises: set[tuple[str, str]], reviewed_by: str) -> None:
    for kind, ref in sorted(premises):
        store.conn.execute("insert into review_premise (id, recorded_at, recorded_by, review_id, kind, ref_id) values (?,?,?,?,?,?)",
                           (new_id(), now_iso(), reviewed_by, review_id, kind, ref))


def _table_premises(store: Store) -> set[tuple[str, str]]:
    out = set()
    for kind in TABLE_KINDS:
        for scope in ("事務所", "物件"):
            lid = latest_load_id(store, kind, scope)
            if lid:
                out.add(("table_load", lid))
    return out


def _item_premises(store: Store, item) -> set[tuple[str, str]]:
    """The basis of one item at the time of approval (B-14): its clues, assumptions, referenced elements."""
    out: set[tuple[str, str]] = set()
    for e in store.all("select clue_id, element_ref_id from interpretation_evidence where item_id=?", item["id"]):
        if e["clue_id"]:
            out.add(("clue", e["clue_id"]))
        if e["element_ref_id"]:
            out.add(("element", e["element_ref_id"]))
    subject = item["element_id"] or item["relation_id"]
    if subject:
        for c in store.all("select id from claim where subject_id=? and interpretation_id=?", subject, item["interpretation_id"]):
            out.add(("claim", c["id"]))
            for ce in store.all("select clue_id from claim_evidence where claim_id=?", c["id"]):
                out.add(("clue", ce["clue_id"]))
    if item["claim_id"]:
        out.add(("claim", item["claim_id"]))
        for ce in store.all("select clue_id from claim_evidence where claim_id=?", item["claim_id"]):
            out.add(("clue", ce["clue_id"]))
    if item["assumption_id"]:
        out.add(("assumption", item["assumption_id"]))
    if item["relation_id"]:
        r = store.one("select from_element_id, to_element_id from relation where id=?", item["relation_id"])
        if r:
            out.add(("element", r["from_element_id"]))
            out.add(("element", r["to_element_id"]))
    interp = store.one("select premise_json from interpretation where id=?", item["interpretation_id"])
    for aid in (loads(interp["premise_json"]) if interp and interp["premise_json"] else []) or []:
        out.add(("assumption", aid))
    return out


# ---------------------------------------------------------------------- the check before approval (決定 12)
def check_before_approval(store: Store, item_ids: list[str]) -> list[str]:
    """Problems that stop the approval; empty when it may proceed."""
    items = {i: store.one("select * from interpretation_item where id=?", i) for i in item_ids}
    missing = [i for i, row in items.items() if row is None]
    if missing:
        return [f"item が見つかりません: {m}" for m in missing]
    rule_rejected = [i for i, row in items.items() if row["rule_check_status"] == STATUS_RULE_REJECTED]
    if rule_rejected:
        return [f"規則ではじかれた item は承認できません: {i}（{items[i]['rule_check_reason']}）" for i in rule_rejected]
    elements_in_set = {row["element_id"] for row in items.values() if row["element_id"] and row["kind"] == "要素を作る"}
    relations_in_set = {row["relation_id"] for row in items.values() if row["relation_id"]}

    def ok(element_id: str | None) -> bool:
        if element_id is None:
            return False
        return element_id in elements_in_set or element_status(store, element_id) in (STATUS_APPROVED, STATUS_DEFAULT)

    def describe(eid: str) -> str:
        from btruth.project import ProjectFolder  # noqa: F401  (name only for the message)
        return f"{proposed_kind_of(store, eid) or '要素'} {eid[:8]}…（{element_status(store, eid)}）"

    problems: list[str] = []
    for iid, row in items.items():
        if row["kind"] == MOVE_ITEM_KIND:
            # a new position of an existing element (H-2): the element itself must be approved first
            if not ok(row["element_id"]):
                problems.append(f"移動した要素がまだ承認されていない: {describe(row['element_id'])}（先に元の解釈を承認する。決定 12）")
            continue
        if row["relation_id"]:
            r = store.one("select * from relation where id=?", row["relation_id"])
            for end in ("from_element_id", "to_element_id"):
                if not ok(r[end]):
                    problems.append(f"つながり {r['kind']} の{'元' if end.startswith('from') else '先'}が承認されていない: {describe(r[end])}")
        elif row["element_id"]:
            eid = row["element_id"]
            for r in store.all("select r.* from relation r where r.from_element_id=? and not exists "
                               "(select 1 from relation_end e where e.relation_id=r.id) order by r.rowid", eid):
                if r["kind"] not in POINTING:
                    continue
                st = relation_status(store, r["id"])
                if st in (STATUS_REJECTED, STATUS_RULE_REJECTED):
                    continue
                if not ok(r["to_element_id"]):
                    problems.append(f"{describe(eid)} が {r['kind']} で指す先が承認されていない: {describe(r['to_element_id'])}"
                                    f"（決定 12：指す先を先に、または同じ承認で承認する）")
        elif row["claim_id"]:
            c = store.one("select subject_id from claim where id=?", row["claim_id"])
            if c and not ok(c["subject_id"]):
                problems.append(f"言い分の主体が承認されていない: {describe(c['subject_id'])}")
    return problems


# ---------------------------------------------------------------------- listings
def _move_line(store: Store, project: ProjectFolder, item, status: str, basis: str) -> str:
    eid = item["element_id"]
    kind = proposed_kind_of(store, eid) or "？"
    name = effective_name(store, project, eid) or _proposed_name(store, eid) or ""
    c = store.one("select attribute, value_json from claim where id=?", item["claim_id"])
    now = effective_value(store, project, eid, c["attribute"], through_type=False)
    return (f"[{status}] 移動 {eid}  {kind} {name}  {c['attribute']}: {dumps(now.value)} → {c['value_json']}  "
            f"{item['reason'] or ''}{basis}").rstrip()


def describe_item(store: Store, project: ProjectFolder, item) -> str:
    status = item_status(store, item["id"])
    conf = f" 確かさ {item['confidence']:.2f}" if item["confidence"] is not None else ""
    versions = set()
    for e in store.all("select c.source_version_id from interpretation_evidence ie join clue c on c.id=ie.clue_id where ie.item_id=?", item["id"]):
        versions.add(e["source_version_id"])
    vnames = []
    for v in versions:
        row = store.one("select s.name, v.seq from source_version v join source s on s.id=v.source_id where v.id=?", v)
        if row:
            vnames.append(f"{row['name']}@{row['seq']}")
    basis = f" 根拠の版 {', '.join(sorted(vnames))}" if vnames else ""
    if item["kind"] == MOVE_ITEM_KIND and item["claim_id"]:
        return _move_line(store, project, item, status, basis)
    if item["element_id"]:
        eid = item["element_id"]
        kind = proposed_kind_of(store, eid) or "？"
        name = effective_name(store, project, eid) or _proposed_name(store, eid) or ""
        return f"[{status}] 要素 {eid}  {kind} {name}{conf}{basis}  {item['reason'] or ''}".rstrip()
    if item["relation_id"]:
        r = store.one("select kind, from_element_id, to_element_id from relation where id=?", item["relation_id"])
        return (f"[{status}] つながり {item['relation_id']}  {r['kind']}  {proposed_kind_of(store, r['from_element_id']) or '?'} "
                f"{(r['from_element_id'] or '')[:8]} → {proposed_kind_of(store, r['to_element_id']) or '?'} {(r['to_element_id'] or '')[:8]}{conf}")
    if item["claim_id"]:
        c = store.one("select subject_id, attribute, value_json from claim where id=?", item["claim_id"])
        return f"[{status}] 言い分 {item['claim_id']}  {proposed_kind_of(store, c['subject_id']) or '?'} {c['subject_id'][:8]} {c['attribute']}={c['value_json']}{conf}{basis}"
    if item["assumption_id"]:
        a = store.one("select level, kind, value_json from assumption where id=?", item["assumption_id"])
        return f"[{status}] 前提 {item['assumption_id']}  段 {a['level']} {a['kind']}={a['value_json']}{conf}{basis}"
    return f"[{status}] {item['kind']} {item['id']}  {item['reason'] or ''}"


def _proposed_name(store: Store, eid: str) -> str | None:
    for a in ("名前", "室名", "室番号", "符号"):
        v = proposed_value(store, eid, a)
        if v not in (None, ""):
            return str(v)
    return None


def listing(store: Store, project: ProjectFolder, items, title: str) -> str:
    lines = [title, f"（{len(items)} 件。一覧を確かめてから y/N を答えてください）"]
    lines += ["  " + describe_item(store, project, i) for i in items]
    return "\n".join(lines)


# ---------------------------------------------------------------------- actions
def _load_items(store: Store, item_ids: list[str]) -> list:
    out = []
    for i in item_ids:
        rows = store.all("select * from interpretation_item where id like ?", i + "%")
        if len(rows) != 1:
            raise ValueError(f"item が一つに決まりません: {i}（{len(rows)} 件）")
        out.append(rows[0])
    return out


def approve_items(store: Store, project: ProjectFolder, item_ids: list[str], reason: str | None, reviewed_by: str,
                  confirm: Callable[[str], bool] | None = None, action: str | None = None) -> str | None:
    """Approve one or several items. One item → review(target=interpretation_item, 承認). Several → one
    review per interpretation with action まとめて承認 and the item ids in choice_json (G-1)."""
    require_terminal(project.db_path)
    items = _load_items(store, item_ids)
    problems = check_before_approval(store, [i["id"] for i in items])
    if problems:
        raise ApprovalBlocked("承認を止めました：\n  " + "\n  ".join(problems))
    confirm = confirm or _confirm_default(project.db_path)
    if not confirm(listing(store, project, items, "承認する item の一覧")):
        return None
    by_interp: dict[str, list] = {}
    for i in items:
        by_interp.setdefault(i["interpretation_id"], []).append(i)
    last = None
    try:
        for interp_id, group in by_interp.items():
            if len(group) == 1 and len(items) == 1:
                rid = _write_review(store, "interpretation_item", group[0]["id"], action or "承認", None, reason, reviewed_by)
            else:
                rid = _write_review(store, "interpretation", interp_id, action or "まとめて承認",
                                    {"item_ids": [g["id"] for g in group]}, reason, reviewed_by)
            premises = _table_premises(store)
            for g in group:
                premises |= _item_premises(store, g)
            _write_premises(store, rid, premises, reviewed_by)
            last = rid
        store.commit()
    except Exception:
        store.conn.rollback()
        raise
    return last


def approve_interpretation(store: Store, project: ProjectFolder, interpretation_id: str, reason: str | None, reviewed_by: str,
                           exclude: list[str] = (), confirm: Callable[[str], bool] | None = None) -> str | None:
    """まとめての承認 of every item of an interpretation that the rules let through, minus `exclude`."""
    require_terminal(project.db_path)
    rows = store.all("select id from interpretation where id like ?", interpretation_id + "%")
    if len(rows) != 1:
        raise ValueError(f"解釈が一つに決まりません: {interpretation_id}（{len(rows)} 件）")
    interp_id = rows[0]["id"]
    excluded = set()
    for x in exclude:
        excluded |= {r["id"] for r in store.all("select id from interpretation_item where id like ?", x + "%")}
    items = [i for i in store.all("select * from interpretation_item where interpretation_id=? order by rowid", interp_id)
             if i["rule_check_status"] != STATUS_RULE_REJECTED and i["kind"] != "読めない" and i["id"] not in excluded]
    if not items:
        raise ValueError("承認できる item がありません")
    problems = check_before_approval(store, [i["id"] for i in items])
    if problems:
        raise ApprovalBlocked("承認を止めました：\n  " + "\n  ".join(problems))
    confirm = confirm or _confirm_default(project.db_path)
    if not confirm(listing(store, project, items, f"解釈 {interp_id} の item をまとめて承認する一覧")):
        return None
    try:
        rid = _write_review(store, "interpretation", interp_id, "まとめて承認", {"item_ids": [i["id"] for i in items]}, reason, reviewed_by)
        premises = _table_premises(store)
        for i in items:
            premises |= _item_premises(store, i)
        _write_premises(store, rid, premises, reviewed_by)
        store.commit()
    except Exception:
        store.conn.rollback()
        raise
    return rid


def _simple_item_action(store, project, item_ids, action, reason, reviewed_by, confirm, require_reason: bool):
    require_terminal(project.db_path)
    if require_reason and not (reason or "").strip():
        raise ValueError(f"{action}には理由が要ります（人が書く）")
    items = _load_items(store, item_ids)
    confirm = confirm or _confirm_default(project.db_path)
    if not confirm(listing(store, project, items, f"{action}する item の一覧")):
        return None
    ids = []
    try:
        for i in items:
            rid = _write_review(store, "interpretation_item", i["id"], action, None, reason, reviewed_by)
            _write_premises(store, rid, _item_premises(store, i), reviewed_by)
            ids.append(rid)
        store.commit()
    except Exception:
        store.conn.rollback()
        raise
    return ids[-1] if ids else None


def reject_items(store, project, item_ids, reason, reviewed_by, confirm=None):
    return _simple_item_action(store, project, item_ids, "却下", reason, reviewed_by, confirm, require_reason=True)


def hold_items(store, project, item_ids, reason, reviewed_by, confirm=None):
    return _simple_item_action(store, project, item_ids, "保留", reason, reviewed_by, confirm, require_reason=False)


def _resolve_element(store: Store, element_id: str) -> str:
    rows = store.all("select id from element where id like ?", element_id + "%")
    if len(rows) != 1:
        raise ValueError(f"要素が一つに決まりません: {element_id}（{len(rows)} 件）")
    return rows[0]["id"]


def _decision(store: Store, project: ProjectFolder, element_id: str, action: str, attribute: str, value, unit: str | None,
              reason: str | None, reviewed_by: str, confirm, basis_source_version_id: str | None, issue_id: str | None,
              statement_kind: str = "決定") -> str | None:
    """A review that fixes a value: review(target=element, action) + claim(mode=採用) in one transaction (D-1, G-1)."""
    require_terminal(project.db_path)
    eid = _resolve_element(store, element_id)
    kind = proposed_kind_of(store, eid) or "要素"
    name = effective_name(store, project, eid) or _proposed_name(store, eid) or ""
    observed = store.all("select id, mode, value_json, source_version_id from claim where subject_id=? and attribute=? order by rowid", eid, attribute)
    text = [f"{action}：{kind} {eid} {name}", f"  属性 {attribute} ← {dumps(value)}{(' ' + unit) if unit else ''}",
            f"  理由 {reason or '（なし）'}"]
    if observed:
        text.append("  今ある言い分: " + "；".join(f"{o['mode']} {o['value_json']}" for o in observed))
    confirm = confirm or _confirm_default(project.db_path)
    if not confirm("\n".join(text)):
        return None
    try:
        rid = _write_review(store, "element", eid, action, {"attribute": attribute, "value": value, "unit": unit}, reason,
                            reviewed_by, basis_source_version_id)
        store.insert("claim", reviewed_by, subject_kind="element", subject_id=eid, attribute=attribute, value_json=dumps(value),
                     unit=unit, mode="採用", statement_kind=statement_kind, source_version_id=None, interpretation_id=None,
                     review_id=rid, agent_id=None, confidence=None)
        premises: set[tuple[str, str]] = {("element", eid)} | _table_premises(store)
        for o in observed:
            premises.add(("claim", o["id"]))
        item = store.one("select id from interpretation_item where element_id=? and kind='要素を作る' order by rowid limit 1", eid)
        if item:
            for e in store.all("select clue_id from interpretation_evidence where item_id=? and clue_id is not null", item["id"]):
                premises.add(("clue", e["clue_id"]))
        _write_premises(store, rid, premises, reviewed_by)
        if issue_id:
            iid = _resolve_issue(store, issue_id)
            irid = _write_review(store, "issue", iid, action, {"review_id": rid, "attribute": attribute, "value": value}, reason, reviewed_by)
            _write_premises(store, irid, {("element", eid)}, reviewed_by)
        store.commit()
    except Exception:
        store.conn.rollback()
        raise
    return rid


def _resolve_issue(store: Store, issue_id: str) -> str:
    rows = store.all("select id from issue where id like ?", issue_id + "%")
    if len(rows) != 1:
        raise ValueError(f"要確認が一つに決まりません: {issue_id}（{len(rows)} 件）")
    return rows[0]["id"]


def decide(store, project, element_id, attribute, value, reason, reviewed_by, unit=None, basis_source_version_id=None,
           confirm=None, issue_id=None):
    return _decision(store, project, element_id, "判断", attribute, value, unit, reason, reviewed_by, confirm,
                     basis_source_version_id, issue_id)


def name_element(store, project, element_id, name, reason, reviewed_by, confirm=None, issue_id=None, attribute="名前"):
    return _decision(store, project, element_id, "名前を付ける", attribute, name, None, reason, reviewed_by, confirm, None, issue_id)


def exclude_room(store, project, element_id, reason, reviewed_by, confirm=None, issue_id=None):
    return _decision(store, project, element_id, "部屋として扱わない", "部屋として扱う", False, None, reason, reviewed_by, confirm,
                     None, issue_id)


def hold_issue(store, project, issue_id, reason, reviewed_by, confirm=None):
    require_terminal(project.db_path)
    iid = _resolve_issue(store, issue_id)
    confirm = confirm or _confirm_default(project.db_path)
    if not confirm(f"要確認 {iid} を保留にする  理由 {reason or '（なし）'}"):
        return None
    rid = _write_review(store, "issue", iid, "保留", None, reason, reviewed_by)
    store.commit()
    return rid


# ---------------------------------------------------------------------- stage 4: the batch approval of moves (G-1, 決定 Q1・Q15)
def _resolve_run(store: Store, run_id: str) -> str:
    rows = store.all("select id from identity_run where id like ?", run_id + "%")
    if len(rows) != 1:
        raise ValueError(f"同定の実行が一つに決まりません: {run_id}（{len(rows)} 件）")
    return rows[0]["id"]


def _has_adopted(store: Store, element_id: str, attribute: str) -> bool:
    return bool(store.one("select 1 from claim where subject_id=? and attribute=? and mode='採用'", element_id, attribute))


def moves_listing_items(store: Store, project: ProjectFolder, run_id: str) -> list:
    """The items the batch approval lists by default: the run's moves (意味の変更なし) still waiting, minus the
    elements that carry a judgement on the moved attribute (those get a recheck mark and are looked at one by one)."""
    run = store.one("select interpretation_id from identity_run where id=?", run_id)
    out = []
    for i in store.all("select * from interpretation_item where interpretation_id=? and kind=? order by rowid",
                       run["interpretation_id"], MOVE_ITEM_KIND):
        if item_status(store, i["id"]) != STATUS_PENDING:
            continue
        link = store.one("select verdict from identity_link where run_id=? and element_id=?", run_id, i["element_id"])
        if not link or link["verdict"] != "移動":
            continue
        attribute = store.scalar("select attribute from claim where id=?", i["claim_id"])
        if _has_adopted(store, i["element_id"], attribute):
            continue
        out.append(i)
    return out


def approve_moves(store: Store, project: ProjectFolder, run_id: str, reason: str | None, reviewed_by: str,
                  exclude: list[str] = (), confirm: Callable[[str], bool] | None = None) -> str | None:
    """review(target_kind=identity_run, action=移動をまとめて承認, choice_json={item_ids}) — one row (G-1)."""
    require_terminal(project.db_path)
    rid_run = _resolve_run(store, run_id)
    excluded = set()
    for x in exclude:
        excluded |= {r["id"] for r in store.all("select id from interpretation_item where id like ?", x + "%")}
    listed = moves_listing_items(store, project, rid_run)
    items = [i for i in listed if i["id"] not in excluded]
    if not items:
        raise ValueError("まとめて承認できる移動がありません")
    problems = check_before_approval(store, [i["id"] for i in items])
    if problems:
        raise ApprovalBlocked("承認を止めました：\n  " + "\n  ".join(problems))
    run = store.one("select interpretation_id from identity_run where id=?", rid_run)
    chosen = {x["id"] for x in items}
    outside = [i for i in store.all("select * from interpretation_item where interpretation_id=? and kind=? order by rowid",
                                    run["interpretation_id"], MOVE_ITEM_KIND)
               if i["id"] not in chosen and item_status(store, i["id"]) == STATUS_PENDING]
    text = listing(store, project, items, f"同定 {rid_run} の移動（意味の変更なし）をまとめて承認する一覧")
    if outside:
        text += "\n一覧に入れなかったもの（判断が付いている、または外した。一つずつ見る）：\n" + "\n".join(
            "  " + describe_item(store, project, i) for i in outside)
    confirm = confirm or _confirm_default(project.db_path)
    if not confirm(text):
        return None
    try:
        rid = _write_review(store, "identity_run", rid_run, "移動をまとめて承認", {"item_ids": [i["id"] for i in items]},
                            reason, reviewed_by)
        premises = _table_premises(store)
        for i in items:
            premises |= _item_premises(store, i)
        _write_premises(store, rid, premises, reviewed_by)
        store.commit()
    except Exception:
        store.conn.rollback()
        raise
    return rid


# ---------------------------------------------------------------------- stage 4: resolving a recheck mark (G-2)
def resolve_recheck(store: Store, project: ProjectFolder, mark_id: str, choice: str, reason: str | None, reviewed_by: str,
                    value=None, unit: str | None = None, confirm: Callable[[str], bool] | None = None) -> str | None:
    """保つ（keep the adopted value）、変える（a new adopted value）、取り消す（the adoption ends; the effective value
    falls back to the approved observations）. The review targets the recheck mark (G-2)."""
    require_terminal(project.db_path)
    if choice not in RECHECK_CHOICES:
        raise ValueError(f"選べるのは {'、'.join(RECHECK_CHOICES)}: {choice}")
    if choice == "変える" and value is None:
        raise ValueError("「変える」には新しい値が要ります（--value）")
    rows = store.all("select * from recheck_mark where id like ?", mark_id + "%")
    if len(rows) != 1:
        raise ValueError(f"再確認の印が一つに決まりません: {mark_id}（{len(rows)} 件）")
    mark = rows[0]
    adopted = store.all("select * from claim where review_id=? and mode='採用' order by rowid", mark["review_id"])
    if not adopted:
        raise ValueError("この印の判断には採用の言い分がありません")
    c = adopted[-1]
    eid = c["subject_id"]
    kind = proposed_kind_of(store, eid) or "要素"
    name = effective_name(store, project, eid) or _proposed_name(store, eid) or ""
    text = [f"再確認の印 {mark['id']}：{kind} {eid} {name}", f"  {c['attribute']} 採用 {c['value_json']}",
            (f"  印の理由 {mark['reason']}  {mark['detail_json'] or ''}")[:400],
            f"  選ぶ {choice}" + (f" → {dumps(value)}{(' ' + unit) if unit else ''}" if choice == "変える" else ""),
            f"  理由 {reason or '（なし）'}"]
    confirm = confirm or _confirm_default(project.db_path)
    if not confirm("\n".join(text)):
        return None
    try:
        choice_json = {"value": value, "unit": unit, "attribute": c["attribute"]} if choice == "変える" else {"claim_id": c["id"]}
        rid = _write_review(store, "recheck_mark", mark["id"], choice, choice_json, reason, reviewed_by)
        premises: set[tuple[str, str]] = {("element", eid), ("claim", c["id"])} | _table_premises(store)
        if choice == "変える":
            store.insert("claim", reviewed_by, subject_kind=c["subject_kind"], subject_id=eid, attribute=c["attribute"],
                         value_json=dumps(value), unit=unit or c["unit"], mode="採用", statement_kind="決定", source_version_id=None,
                         interpretation_id=None, review_id=rid, agent_id=None, confidence=None)
        _write_premises(store, rid, premises, reviewed_by)
        store.commit()
    except Exception:
        store.conn.rollback()
        raise
    return rid
