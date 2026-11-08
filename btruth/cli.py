"""The btruth command.

Stage 2: init / import / versions / compare / report. Stage 3: propose / items / issues / clues / show /
measure, and the confirmation commands approve / reject / hold / decide / name / exclude-room. Stage 4: identify /
diff / rechecks / kit, and the confirmation commands approve-moves / resolve-recheck.

Every subcommand takes the project folder; the database path comes from settings/project.csv
(G-1 (a): no database file name on the command line, so the hook that stops direct database writes
does not stop btruth). The confirmation commands run from a terminal only, print the listing, then ask
"確定しますか？ (y/N)" (G-1 (b), (c)); Claude Code is stopped before them by .claude/hooks/guard_confirm.py.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

TERMINAL_HELP = "（端末からだけ動く。一覧を出してから y/N で確かめる。Claude Code は実行しない）"


def _who(args) -> str:
    return args.by or os.environ.get("BTRUTH_USER") or getpass.getuser()


def _resolve_version(store, ref: str) -> str:
    """A version is named `<source name>@<seq>` or by the start of its id."""
    if "@" in ref:
        name, seq = ref.rsplit("@", 1)
        row = store.one("select v.id from source_version v join source s on s.id=v.source_id where s.name=? and v.seq=?",
                        name, int(seq))
        if not row:
            raise SystemExit(f"版が見つかりません: {ref}")
        return row["id"]
    rows = store.all("select id from source_version where id like ?", ref + "%")
    if len(rows) != 1:
        raise SystemExit(f"版が一つに決まりません: {ref}（{len(rows)} 件）")
    return rows[0]["id"]


def _open(args):
    from btruth.project import ProjectFolder, open_store
    project = ProjectFolder.load(Path(args.folder))
    return project, open_store(project)


# ---------------------------------------------------------------------- stage 2
def cmd_init(args) -> int:
    from btruth.project import init_project
    project = init_project(Path(args.folder), name=args.name, office_dir=Path(args.office) if args.office else None,
                           recorded_by=_who(args))
    print(f"器を作りました: {project.folder}（物件 {args.name}）。正本の場所は settings/project.csv の db_path。")
    return 0


def cmd_import(args) -> int:
    from btruth.intake import SourceExists, SourceNotFound, UnsupportedFormat, import_file
    project, store = _open(args)
    mode = "new" if args.new else ("next" if args.next else "auto")
    with store:
        try:
            r = import_file(store, project, Path(args.file), source_name=args.source, kind=args.kind,
                            drawing_type=args.drawing_type, discipline=args.discipline,
                            document_date=args.document_date, mode=mode, recorded_by=_who(args))
        except (UnsupportedFormat, SourceExists, SourceNotFound) as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if r.skipped:
        print(f"{r.file_name}: 同じ中身の版がすでにあります（{r.existing_version_id}）。取り込みません。記録だけ残しました。")
        return 0
    total = sum(r.counts.values())
    how = "新しい出どころ" if r.source_created else f"既存の出どころの次の版（版 {r.seq}）"
    print(f"{r.file_name}: 取り込みました（{how}）。版 {r.source_version_id}、観測の手掛かり {total}、生成物として外した {r.generated_count}。")
    for (layer, kind), n in sorted(r.counts.items()):
        print(f"  {layer:<24} {kind:<12} {n}")
    for kind, detail in r.notes:
        print(f"  記録 {kind}: {detail}")
    return 0


def cmd_versions(args) -> int:
    project, store = _open(args)
    with store:
        rows = store.all("select s.name, s.kind, v.seq, v.file_name, v.imported_at, v.id from source_version v "
                         "join source s on s.id=v.source_id order by s.name, v.seq")
        for r in rows:
            print(f"{r['name']}@{r['seq']}  {r['file_name']}  区分={r['kind'] or '（未指定）'}  {r['imported_at']}  {r['id']}")
        if not rows:
            print("取り込んだ版はまだありません。")
    return 0


def cmd_compare(args) -> int:
    from btruth.compare import compare_versions
    project, store = _open(args)
    with store:
        a, b = _resolve_version(store, args.version_a), _resolve_version(store, args.version_b)
        r = compare_versions(store, project, a, b, recorded_by=_who(args))
        f = r.frame
        print("座標の枠: " + ("揃えた" if f["aligned"] else "揃えていない") + f"  {f['note']}")
        if f["aligned"]:
            print(f"  符号 {f['labels']}  ずれ {f['delta_mm']} mm")
        print(f"一致 {len(r.matched)}  前の版だけ {len(r.only_a)}  追加の候補 {len(r.only_b)}"
              f"（幅 {f['same_position_mm']} mm / {f['same_angle_deg']} 度）")
        for cid in r.only_a:
            row = store.one("select kind, layer_raw, text_raw from clue where id=?", cid)
            print(f"  前の版だけ: {row['kind']} {row['layer_raw']} {row['text_raw'] or ''}")
        for cid in r.only_b:
            row = store.one("select kind, layer_raw, text_raw from clue where id=?", cid)
            print(f"  追加の候補: {row['kind']} {row['layer_raw']} {row['text_raw'] or ''}")
    return 0


def cmd_report(args) -> int:
    from btruth.report import build_report, render_text, write_report
    project, store = _open(args)
    with store:
        if args.out:
            out = write_report(store, project, Path(args.out), html=args.html, recorded_by=_who(args))
            print(f"レポートを書きました: {out}")
        else:
            print(render_text(build_report(store, project)))
    return 0


# ---------------------------------------------------------------------- stage 3: reading and proposing
def cmd_clues(args) -> int:
    """The observed clues of one version as JSON — what the agent reads (B-1). Layers are also given as roles."""
    from btruth.common import loads
    from btruth.compare import roles_for
    from btruth.tables import effective_rows
    project, store = _open(args)
    with store:
        vid = _resolve_version(store, args.version)
        v = store.one("select v.*, s.name as source_name, s.kind as source_kind from source_version v join source s on s.id=v.source_id where v.id=?", vid)
        layer_rows = effective_rows(store, project, "layer_roles")
        clues = []
        for c in store.all("select id, seq, kind, layer_raw, geometry_json, text_raw, style_json, format_extra_json from clue "
                           "where source_version_id=? and generated_from is null and kind <> 'BLOCK_DEF' "
                           "and (parent_clue_id is null or ? <> 'dxf') order by seq", vid, v["format"]):
            clues.append({"ref": f"{v['source_name']}@{v['seq']}#{c['seq']}", "id": c["id"], "seq": c["seq"], "kind": c["kind"],
                          "layer": c["layer_raw"], "roles": list(roles_for(c["layer_raw"], c["kind"], layer_rows)),
                          "geometry": loads(c["geometry_json"]), "text": c["text_raw"], "style": loads(c["style_json"]),
                          "extra": loads(c["format_extra_json"])})
        attrs = {r["attribute"]: r["value"] for r in store.all(
            "select attribute, value from source_attribute where source_id=? order by rowid", v["source_id"])}
        print(json.dumps({"version": {"id": vid, "source_name": v["source_name"], "seq": v["seq"], "file_name": v["file_name"],
                                      "source_kind": v["source_kind"], "attributes": attrs, "unit_factor": v["unit_factor"]},
                          "clues": clues}, ensure_ascii=False, indent=1))
    return 0


def cmd_propose(args) -> int:
    from btruth.propose import ProposalError, load_proposal, register_proposal
    project, store = _open(args)
    with store:
        try:
            r = register_proposal(store, project, load_proposal(Path(args.file)), recorded_by=_who(args),
                                  instructions_path=Path(args.instructions) if args.instructions else None)
        except ProposalError as exc:
            print(f"登録できません: {exc}", file=sys.stderr)
            return 2
        print(f"提案を登録しました。解釈の ID {r.interpretation_id}")
        print(f"  item {len(r.items)}  通った {r.passed}  はじかれた {r.rejected}  要確認 {len(r.issues)}")
        for i in r.items:
            if i["status"] == "はじかれた":
                print(f"  はじかれた: {i['kind']} {i.get('ref') or ''}  {i['reason']}")
        for iid in r.issues:
            row = store.one("select kind, severity, subject_ids_json from issue where id=?", iid)
            print(f"  要確認 [{row['severity']}] {row['kind']}  {row['subject_ids_json']}")
        print("次は `btruth show` で画面を出し、人が端末で `btruth approve` を打つ。")
    return 0


def cmd_items(args) -> int:
    from btruth.effective import item_status, proposed_kind_of
    from btruth.review import describe_item
    project, store = _open(args)
    with store:
        interps = store.all("select i.id, i.summary, i.recorded_at, a.name as agent from interpretation i join agent a on a.id=i.agent_id order by i.rowid desc")
        shown_items: list = []
        for p in interps:
            if args.interpretation and not p["id"].startswith(args.interpretation):
                continue
            items = store.all("select * from interpretation_item where interpretation_id=? order by rowid", p["id"])
            if args.kind:
                items = [i for i in items if i["element_id"] and proposed_kind_of(store, i["element_id"]) == args.kind]
            if not items:
                continue
            print(f"解釈 {p['id']}  {p['agent']}  {p['summary'] or ''}  {p['recorded_at']}")
            for i in items:
                print("  " + describe_item(store, project, i))
            shown_items.extend(items)
        if shown_items:
            from btruth.review import items_frame_note
            print(items_frame_note(store, shown_items))
    return 0


def cmd_issues(args) -> int:
    from btruth.effective import effective_name, open_issues, proposed_kind_of
    project, store = _open(args)
    with store:
        issues = open_issues(store, project)
        if not issues:
            print("開いている要確認はありません。")
            return 0
        from btruth.display import issue_lines
        for line in issue_lines(store, project, issues):
            print(line)
    return 0


def cmd_show(args) -> int:
    from btruth.show import write_show
    project, store = _open(args)
    with store:
        out = Path(args.out) if args.out else project.out_dir / "show.html"
        write_show(store, project, out, recorded_by=_who(args))
        print(f"理解の確認の画面を書きました: {out}")
    return 0


def cmd_measure(args) -> int:
    from btruth.measure import mark_measurement, measure
    project, store = _open(args)
    with store:
        if args.list:
            for r in store.all("select id, kind, recorded_at, counts_json from run_summary where kind in "
                               "('AI の解釈の正しさの測定', '測定の印') order by rowid"):
                d = json.loads(r["counts_json"] or "{}")
                what = (f"要素 {d['elements']['fixed']}/{d['elements']['ai']}/{d['elements']['matched']}  条件 {d.get('condition', '記録なし')}"
                        if r["kind"] != "測定の印" else f"印 → {d.get('marks')}  {d.get('condition')}")
                print(f"{r['id']}  {r['kind']}  {r['recorded_at']}  {what}")
            return 0
        if args.mark:
            rid = mark_measurement(store, args.mark, args.note, recorded_by=_who(args))
            print(f"測定の数字に印を付けました（run_summary {rid}）。")
            return 0
        if not (args.interpretation and args.against):
            raise SystemExit("--interpretation と --against が要ります（または --mark）")
        def interp(prefix):
            rows = store.all("select id from interpretation where id like ?", prefix + "%")
            if len(rows) != 1:
                raise SystemExit(f"解釈が一つに決まりません: {prefix}（{len(rows)} 件）")
            return rows[0]["id"]
        r = measure(store, project, interp(args.interpretation), interp(args.against), recorded_by=_who(args),
                    condition=args.condition)
        print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0


# ---------------------------------------------------------------------- stage 4: identity, difference, kit
def cmd_identify(args) -> int:
    from btruth.identity import IdentityError, identify
    project, store = _open(args)
    with store:
        a, b = _resolve_version(store, args.base), _resolve_version(store, args.new)
        try:
            r = identify(store, project, a, b, recorded_by=_who(args))
        except IdentityError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        c = r.counts
        print(f"同定しました。同定の ID {r.run_id}")
        print("  " + "  ".join(f"{k} {c.get(k, 0)}" for k in ("一致", "移動", "追加", "消えた", "判断できない", "意味が変わった", "分割", "統合")))
        marks = store.scalar("select count(*) from recheck_mark where caused_by_id=?", r.run_id)
        print(f"  自動で処理した数 {c['自動で処理した数']}  人に渡した数 {c['人に渡した数']}  再確認の印 {marks}  要確認 {len(r.issues)}")
        m = r.mesh
        print(f"  節点の網の目: 節点 {m['nodes_base']}→{m['nodes_new']}  辺 {m['edges_base']}→{m['edges_new']}  足場 {len(m['anchors'])}")
        if r.move_items:
            print(f"  移動の承認待ち {len(r.move_items)} 件。人が端末で `btruth approve-moves {args.folder} --run {r.run_id[:8]}` を打つ。")
        print("  差分は `btruth diff` で見る。")
    return 0


def cmd_diff(args) -> int:
    from btruth.diff import build_diff, render_text, write_diff
    from btruth.identity import IdentityError, resolve_run
    project, store = _open(args)
    with store:
        try:
            run_id = resolve_run(store, args.run)
        except IdentityError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        if args.out:
            out = write_diff(store, project, run_id, Path(args.out), html=args.html, recorded_by=_who(args))
            print(f"差分のレポートを書きました: {out}")
        else:
            print(render_text(build_diff(store, project, run_id)))
    return 0


def cmd_rechecks(args) -> int:
    from btruth.effective import effective_name, proposed_kind_of
    project, store = _open(args)
    with store:
        rows = [m for m in store.all("select * from recheck_mark order by rowid")
                if not store.one("select 1 from review where target_kind='recheck_mark' and target_id=?", m["id"])]
        if not rows:
            print("開いている再確認の印はありません。")
            return 0
        print(f"再確認の印 {len(rows)} 件（人が端末で `btruth resolve-recheck` を打ち、保つ／変える／取り消す を選ぶ）")
        for m in rows:
            c = store.one("select subject_id, attribute, value_json from claim where review_id=? and mode='採用' order by rowid desc limit 1",
                          m["review_id"])
            what = ""
            if c:
                what = f"{proposed_kind_of(store, c['subject_id']) or '要素'} {c['subject_id']} {effective_name(store, project, c['subject_id']) or ''} " \
                       f"{c['attribute']}={c['value_json']}"
            print(f"印 {m['id']}  {m['reason']}  {what}")
    return 0


def _judgement_basis(store, review_id) -> str:
    """決定 Q8: a judgement with a basis document has that document's rank; without one, the rank of 設計図 (5)."""
    rev = store.one("select basis_source_version_id from review where id=?", review_id) if review_id else None
    vid = rev["basis_source_version_id"] if rev else None
    if not vid:
        return "人の判断（根拠の書類なし、設計図と同格 5）"
    src = store.one("select s.name, s.kind, v.seq from source_version v join source s on s.id=v.source_id where v.id=?", vid)
    rank = store.scalar("select rank from document_rank_loaded where source_kind=? order by rowid desc limit 1", src["kind"])
    return f"人の判断（根拠 {src['name']}@{src['seq']}、{src['kind']}、格 {rank or '？'}）"


def cmd_values(args) -> int:
    """Read-only: an element's attributes with their effective value (D-1), where it came from, and every claim."""
    from btruth.common import loads
    from btruth.consistency import primary_discipline
    from btruth.display import claim_text, frame_note, frame_of_version
    from btruth.effective import effective_name, effective_value, proposed_kind_of
    project, store = _open(args)
    with store:
        rows = store.all("select id from element where id like ?", args.element + "%")
        if len(rows) != 1:
            raise SystemExit(f"要素が一つに決まりません: {args.element}（{len(rows)} 件）")
        eid = rows[0]["id"]
        print(f"{proposed_kind_of(store, eid) or '要素'} {eid} {effective_name(store, project, eid) or ''}".rstrip()
              + f"  主の分野 {primary_discipline(store, project, eid) or '（決まらない）'}")
        frames = []
        for a in [r["attribute"] for r in store.all("select distinct attribute from claim where subject_id=? order by rowid", eid)]:
            if a == "種類":
                continue
            v = effective_value(store, project, eid, a)
            src = store.one("select source_version_id from claim where id=?", v.claim_id) if v.claim_id else None
            vid = src["source_version_id"] if src else None
            frames.append(frame_of_version(store, vid))
            shown = claim_text(store, json.dumps(v.value, ensure_ascii=False), vid) if v.present else "（なし）"
            extra = (" 要再確認" if v.recheck else "") + (f" 型から {v.via_type[:8]}" if v.via_type else "") + (f" {v.note}" if v.note else "")
            print(f"  {a}: {shown}  [{v.status}]{extra}")
            subjects = [(eid, "")]
            if v.via_type:
                label = "ふさぐ建具の型" if (proposed_kind_of(store, eid) == "開口") else "型"
                subjects.append((v.via_type, f"（{label} {v.via_type[:8]}）"))
            for sid, label in subjects:
              for c in store.all("select c.*, s.name as src, v.seq from claim c left join source_version v on v.id=c.source_version_id "
                                 "left join source s on s.id=v.source_id where c.subject_id=? and c.attribute=? order by c.rowid", sid, a):
                where = f"{c['src']}@{c['seq']}" if c["src"] else _judgement_basis(store, c["review_id"])
                where = label + where
                kind = f" {c['statement_kind']}" if c["statement_kind"] and c["statement_kind"] != "記述" else ""
                print(f"      {c['mode']}{kind}  {where}  {claim_text(store, c['value_json'], c['source_version_id'])}")
                frames.append(frame_of_version(store, c["source_version_id"]))
        print(frame_note(frames))
    return 0


def cmd_check(args) -> int:
    from btruth.consistency import check
    project, store = _open(args)
    with store:
        scope = None
        if args.element:
            scope = []
            for e in args.element:
                rows = store.all("select id from element where id like ?", e + "%")
                if len(rows) != 1:
                    raise SystemExit(f"要素が一つに決まりません: {e}（{len(rows)} 件）")
                scope.append(rows[0]["id"])
        run, issues = check(store, project, _who(args), scope=scope, trigger="人の求め")
        marks = store.scalar("select counts_json from run_summary where kind='整合の照らし' order by rowid desc limit 1")
        print(f"照らしました（check_run {run}）。新しい要確認 {len(issues)} 件。{json.loads(marks).get('再確認の印', 0)} 件の再確認の印を足した。")
        for iid in issues:
            row = store.one("select kind, severity from issue where id=?", iid)
            print(f"  {row['kind']} [{row['severity']}]  {iid}")
        print("開いている要確認は `btruth issues` で見る。")
    return 0


def cmd_identify_sources(args) -> int:
    from btruth.identity import IdentityError, identify_sources
    project, store = _open(args)
    with store:
        rows = store.all("select id from interpretation where id like ?", args.interpretation + "%")
        if len(rows) != 1:
            raise SystemExit(f"解釈が一つに決まりません: {args.interpretation}（{len(rows)} 件）")
        try:
            r = identify_sources(store, project, rows[0]["id"], recorded_by=_who(args))
        except IdentityError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        c = r.counts
        print(f"出どころの間の同定をしました。同定の ID {r.run_id}、言い分を足す解釈 {r.interpretation_id}")
        print(f"  一致 {c['一致']}  追加 {c['追加']}  判断できない {c['判断できない']}  足す言い分の item {len(r.move_items)}")
        if r.move_items:
            print(f"  人が端末で `btruth approve {args.folder} --interpretation {r.interpretation_id[:8]}` を打つ。")
    return 0


def cmd_kit(args) -> int:
    from btruth.kit import write_kit
    project, store = _open(args)
    with store:
        dest = write_kit(store, project, args.versions, Path(args.dest))
    print(f"測定の場所を作りました: {dest}（手掛かりと手順書と守りだけ。答えは入れていない）。docs/MEASURE.md の手順で、"
          "そのフォルダで新しい Claude Code を起動する。")
    return 0


# ---------------------------------------------------------------------- stage 3: confirmation (terminal only)
def _confirm_wrapper(args):
    from btruth.review import prompt_confirm
    return prompt_confirm


def _run_review(args, fn) -> int:
    from btruth.review import ApprovalBlocked, NotATerminal
    project, store = _open(args)
    with store:
        try:
            result = fn(project, store)
        except NotATerminal as exc:
            print(str(exc), file=sys.stderr)
            return 3
        except ApprovalBlocked as exc:
            print(str(exc), file=sys.stderr)
            return 4
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if result is None:
        print("記録しません。")
    return 0


def cmd_approve(args) -> int:
    from btruth.review import approve_interpretation, approve_items

    def go(project, store):
        if args.interpretation:
            rid = approve_interpretation(store, project, args.interpretation, reason=args.reason, reviewed_by=_who(args),
                                         exclude=args.exclude or [], confirm=_confirm_wrapper(args))
        else:
            rid = approve_items(store, project, args.item, reason=args.reason, reviewed_by=_who(args), confirm=_confirm_wrapper(args))
        if rid:
            print(f"承認を記録しました（review {rid}）。")
            _check_after(project, store, args, rid, "承認の後")
        return rid
    return _run_review(args, go)


def _check_after(project, store, args, review_id: str, trigger: str) -> None:
    """The consistency check after an approval: the approved elements and their neighbours (C-8: what changed)."""
    from btruth.common import loads
    from btruth.consistency import check
    from btruth.effective import relations_from, relations_to
    rev = store.one("select target_kind, target_id, choice_json from review where id=?", review_id)
    ids = (loads(rev["choice_json"]) or {}).get("item_ids") or ([rev["target_id"]] if rev["target_kind"] == "interpretation_item" else [])
    scope = set()
    for i in ids:
        row = store.one("select element_id, relation_id, claim_id from interpretation_item where id=?", i)
        if not row:
            continue
        if row["element_id"]:
            scope.add(row["element_id"])
        if row["relation_id"]:
            r = store.one("select from_element_id, to_element_id from relation where id=?", row["relation_id"])
            scope |= {r["from_element_id"], r["to_element_id"]}
        if row["claim_id"]:
            scope.add(store.scalar("select subject_id from claim where id=?", row["claim_id"]))
    for e in list(scope):
        for r in relations_from(store, e) + relations_to(store, e):
            scope |= {r["from_element_id"], r["to_element_id"]}
    _, issues = check(store, project, _who(args), scope=sorted(x for x in scope if x), trigger=trigger)
    print(f"承認の後の照らし：照らした要素 {len(scope)}、新しい要確認 {len(issues)} 件（`btruth issues` で見る）。")


def cmd_reject(args) -> int:
    from btruth.review import reject_items

    def go(project, store):
        rid = reject_items(store, project, args.item, reason=args.reason, reviewed_by=_who(args), confirm=_confirm_wrapper(args))
        if rid:
            print(f"却下を記録しました（review {rid}）。")
        return rid
    return _run_review(args, go)


def cmd_hold(args) -> int:
    from btruth.review import hold_issue, hold_items

    def go(project, store):
        if args.issue:
            rid = hold_issue(store, project, args.issue, reason=args.reason, reviewed_by=_who(args), confirm=_confirm_wrapper(args))
        else:
            rid = hold_items(store, project, args.item, reason=args.reason, reviewed_by=_who(args), confirm=_confirm_wrapper(args))
        if rid:
            print(f"保留を記録しました（review {rid}）。")
        return rid
    return _run_review(args, go)


def _parse_value(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def cmd_decide(args) -> int:
    from btruth.review import decide

    def go(project, store):
        rid = decide(store, project, args.element, args.attribute, _parse_value(args.value), reason=args.reason,
                     reviewed_by=_who(args), unit=args.unit, basis_source_version_id=args.basis, confirm=_confirm_wrapper(args),
                     issue_id=args.issue)
        if rid:
            print(f"判断を記録しました（review {rid}）。採用の言い分を書きました。")
        return rid
    return _run_review(args, go)


def cmd_name(args) -> int:
    from btruth.review import name_element

    def go(project, store):
        rid = name_element(store, project, args.element, args.name, reason=args.reason, reviewed_by=_who(args),
                           confirm=_confirm_wrapper(args), issue_id=args.issue, attribute=args.attribute)
        if rid:
            print(f"名前を記録しました（review {rid}）。")
        return rid
    return _run_review(args, go)


def cmd_exclude_room(args) -> int:
    from btruth.review import exclude_room

    def go(project, store):
        rid = exclude_room(store, project, args.element, reason=args.reason, reviewed_by=_who(args), confirm=_confirm_wrapper(args),
                           issue_id=args.issue)
        if rid:
            print(f"「部屋として扱わない」を記録しました（review {rid}）。")
        return rid
    return _run_review(args, go)


def cmd_approve_moves(args) -> int:
    from btruth.review import approve_moves

    def go(project, store):
        from btruth.identity import resolve_run
        run_id = resolve_run(store, args.run)
        rid = approve_moves(store, project, run_id, reason=args.reason, reviewed_by=_who(args), exclude=args.exclude or [],
                            confirm=_confirm_wrapper(args))
        if rid:
            print(f"移動のまとめての承認を記録しました（review {rid}）。")
            _check_after(project, store, args, rid, "移動の承認の後")
        return rid
    return _run_review(args, go)


def cmd_choose(args) -> int:
    from btruth.review import choose_option

    def go(project, store):
        rid = choose_option(store, project, args.issue, args.option, reason=args.reason, reviewed_by=_who(args),
                            confirm=_confirm_wrapper(args))
        if rid:
            print(f"要確認の選択を記録しました（review {rid}）。")
        return rid
    return _run_review(args, go)


def cmd_resolve_recheck(args) -> int:
    from btruth.review import resolve_recheck

    def go(project, store):
        rid = resolve_recheck(store, project, args.mark, args.choice, reason=args.reason, reviewed_by=_who(args),
                              value=_parse_value(args.value) if args.value is not None else None, unit=args.unit,
                              confirm=_confirm_wrapper(args))
        if rid:
            print(f"再確認の印の解消を記録しました（review {rid}、{args.choice}）。")
        return rid
    return _run_review(args, go)


# ---------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="btruth", description="building-truth v3 — 器と入口（第2段）、解釈と確定（第3段）、版の同定と持ち越し（第4段）")
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp):
        sp.add_argument("folder", help="物件のフォルダ（正本の場所は settings/project.csv から読む）")
        sp.add_argument("--by", help="記録する人・道具の名前（既定: 環境変数 BTRUTH_USER か、ログインの名前）")

    sp = sub.add_parser("init", help="器を作る（物件のフォルダ、既定の表、既定の構成）")
    common(sp)
    sp.add_argument("--name", required=True, help="物件の名前")
    sp.add_argument("--office", help="事務所の共通フォルダ（rules/ settings/ knowledge/ を先に読む）")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("import", help="図面・表・文章を取り込む")
    common(sp)
    sp.add_argument("file", help="取り込むファイル（dxf / csv / txt / md）")
    sp.add_argument("--source", help="出どころの呼び名（既定: ファイル名）")
    how = sp.add_mutually_exclusive_group()
    how.add_argument("--next", action="store_true", help="既存の出どころの次の版として取り込む（ファイル名が変わってもよい。呼び名がなければ止める）")
    how.add_argument("--new", action="store_true", help="新しい出どころとして取り込む（同じ呼び名があれば止める）")
    sp.add_argument("--kind", help="書類の区分（法律／議事録／現場説明書／特記仕様書／設計図／事務所の基準／標準仕様書／施工図／条件／その他）")
    sp.add_argument("--drawing-type", help="図面の種類（建築平面図、壁種表、凡例、…）")
    sp.add_argument("--discipline", help="分野（建築／構造／電気／機械設備）")
    sp.add_argument("--document-date", help="書類に書かれた日付")
    sp.set_defaults(func=cmd_import)

    sp = sub.add_parser("versions", help="取り込んだ版の一覧")
    common(sp)
    sp.set_defaults(func=cmd_versions)

    sp = sub.add_parser("compare", help="二つの版の手掛かりを比べる（レイヤを役割に、枠を符号で揃え、幅の中で一致）")
    common(sp)
    sp.add_argument("version_a", help="前の版（<出どころ>@<版の番号> か、版の ID の先頭）")
    sp.add_argument("version_b", help="新しい版")
    sp.set_defaults(func=cmd_compare)

    sp = sub.add_parser("report", help="手掛かりの一覧と読み残しを出す")
    common(sp)
    sp.add_argument("--out", help="書き出す先（省くと画面に出す）")
    sp.add_argument("--html", action="store_true", help="HTML で書く（既定はテキスト）")
    sp.set_defaults(func=cmd_report)

    sp = sub.add_parser("clues", help="一つの版の観測の手掛かりを JSON で出す（AI が読むためのもの）")
    common(sp)
    sp.add_argument("version", help="<出どころ>@<版の番号> か、版の ID の先頭")
    sp.set_defaults(func=cmd_clues)

    sp = sub.add_parser("propose", help="提案の JSON を登録する（ID を振り、規則の確かめを通す。承認はしない）")
    common(sp)
    sp.add_argument("file", help="提案の JSON")
    sp.add_argument("--instructions", help="エージェントが従った手順書（スキル）のファイル。sha256 を agent に記録する")
    sp.set_defaults(func=cmd_propose)

    sp = sub.add_parser("items", help="解釈の item と状態（提案中／承認済み／却下／保留／はじかれた）の一覧")
    common(sp)
    sp.add_argument("--interpretation", help="解釈の ID（先頭でよい）で絞る")
    sp.add_argument("--kind", help="要素の種類で絞る（壁、部屋、…）")
    sp.set_defaults(func=cmd_items)

    sp = sub.add_parser("issues", help="開いている要確認の一覧")
    common(sp)
    sp.set_defaults(func=cmd_issues)

    sp = sub.add_parser("show", help="理解の確認の画面（HTML）を書く。要素をクリックすると根拠の手掛かりが光る")
    common(sp)
    sp.add_argument("--out", help="書き出す先（既定: <物件のフォルダ>/out/show.html）")
    sp.set_defaults(func=cmd_show)

    sp = sub.add_parser("measure", help="AI の解釈を固定の解釈と照らし、数を run_summary に残す（合否は付けない）")
    common(sp)
    sp.add_argument("--interpretation", help="AI の解釈の ID（先頭でよい）")
    sp.add_argument("--against", help="固定の解釈の ID（先頭でよい）")
    sp.add_argument("--condition", default="答えを見せない（docs/MEASURE.md）",
                    help="読ませた条件（既定: 答えを見せない。同じセッションで答えを書いた後なら、そう書く）")
    sp.add_argument("--mark", help="前の測定の run_summary の ID に「答えを知った状態の数字」の印を足す")
    sp.add_argument("--note", help="印の説明")
    sp.add_argument("--list", action="store_true", help="これまでの測定と印の一覧")
    sp.set_defaults(func=cmd_measure)

    sp = sub.add_parser("identify", help="同じ出どころの二つの版を同定する（一段目・二段目。移動は承認待ちの item にする。承認はしない）")
    common(sp)
    sp.add_argument("base", help="前の版（<出どころ>@<版の番号> か、版の ID の先頭）")
    sp.add_argument("new", help="新しい版")
    sp.set_defaults(func=cmd_identify)

    sp = sub.add_parser("diff", help="同定の差分のレポート（一致・移動・追加・消えた・判断できない、自動で処理した数と人に渡した数）")
    common(sp)
    sp.add_argument("--run", help="同定の ID（先頭でよい。既定: 最後の同定）")
    sp.add_argument("--out", help="書き出す先（省くと画面に出す）")
    sp.add_argument("--html", action="store_true", help="HTML で書く")
    sp.set_defaults(func=cmd_diff)

    sp = sub.add_parser("values", help="要素の属性ごとの有効値と、その出どころ、全部の言い分（読むだけ）")
    common(sp)
    sp.add_argument("--element", required=True, help="要素の ID（先頭でよい）")
    sp.set_defaults(func=cmd_values)

    sp = sub.add_parser("check", help="整合の照らし（主の表・格の表、型と実物、境界の区間、向かい合う境界…）。読むだけで、要確認を出す")
    common(sp)
    sp.add_argument("--element", nargs="*", help="照らす要素（既定: 承認済みの全部）")
    sp.set_defaults(func=cmd_check)

    sp = sub.add_parser("identify-sources", help="出どころの間の同定（新しい出どころの解釈の要素を、既にある要素と鍵と足場で照らす。承認はしない）")
    common(sp)
    sp.add_argument("--interpretation", required=True, help="新しい出どころを読んだ解釈の ID（先頭でよい）")
    sp.set_defaults(func=cmd_identify_sources)

    sp = sub.add_parser("rechecks", help="開いている再確認の印の一覧（G-2）")
    common(sp)
    sp.set_defaults(func=cmd_rechecks)

    sp = sub.add_parser("kit", help="答えを見せない測定の場所を作る（手掛かりの JSON と手順書と守りだけ。docs/MEASURE.md）")
    common(sp)
    sp.add_argument("--versions", nargs="+", required=True, help="読ませる版（<出どころ>@<版の番号>）")
    sp.add_argument("--dest", required=True, help="測定の場所（からのフォルダ。リポジトリの外に置く）")
    sp.set_defaults(func=cmd_kit)

    # confirmation commands (terminal only; stopped for Claude Code by the hook)
    _add = sub.add_parser

    def confirm_parser(name: str, help_text: str):
        return _add(name, help=help_text + " " + TERMINAL_HELP,
                    description=f"{help_text}。{TERMINAL_HELP}。人が理由を書く。承認の前に、指す先が承認済みかを確かめる（決定 12）。")

    sp = confirm_parser("approve", "承認する")
    common(sp)
    g = sp.add_mutually_exclusive_group(required=True)
    g.add_argument("--interpretation", help="解釈の全部の item をまとめて承認する（一覧を出してから y/N）")
    g.add_argument("--item", nargs="+", help="承認する item の ID（先頭でよい）")
    sp.add_argument("--exclude", nargs="*", help="まとめての承認から外す item")
    sp.add_argument("--reason", help="理由（人が書く）")
    sp.set_defaults(func=cmd_approve)

    sp = confirm_parser("reject", "却下する")
    common(sp)
    sp.add_argument("--item", nargs="+", required=True, help="却下する item の ID（先頭でよい）")
    sp.add_argument("--reason", required=True, help="理由（人が書く。必須）")
    sp.set_defaults(func=cmd_reject)

    sp = confirm_parser("hold", "保留にする")
    common(sp)
    g = sp.add_mutually_exclusive_group(required=True)
    g.add_argument("--item", nargs="+", help="保留にする item の ID")
    g.add_argument("--issue", help="保留にする要確認の ID")
    sp.add_argument("--reason", help="理由")
    sp.set_defaults(func=cmd_hold)

    sp = confirm_parser("decide", "判断：値を確定する（採用の言い分を書く）")
    common(sp)
    sp.add_argument("--element", required=True, help="要素の ID（先頭でよい）")
    sp.add_argument("--attribute", required=True, help="属性（芯線、厚さ、境界の種類、…）")
    sp.add_argument("--value", required=True, help="値（JSON として読める形。読めなければ文字）")
    sp.add_argument("--unit", help="単位（mm など）")
    sp.add_argument("--reason", help="理由（人が書く）")
    sp.add_argument("--basis", help="根拠にした書類の版の ID（添えればその書類の格。決定 Q8）")
    sp.add_argument("--issue", help="この判断で閉じる要確認の ID")
    sp.set_defaults(func=cmd_decide)

    sp = confirm_parser("name", "名前を付ける（名前のない空間など）")
    common(sp)
    sp.add_argument("--element", required=True, help="要素の ID（先頭でよい）")
    sp.add_argument("--name", required=True, help="名前")
    sp.add_argument("--attribute", default="名前", help="書く属性（既定: 名前。室名 なども）")
    sp.add_argument("--reason", help="理由")
    sp.add_argument("--issue", help="この判断で閉じる要確認の ID")
    sp.set_defaults(func=cmd_name)

    sp = confirm_parser("exclude-room", "部屋として扱わない（面積の合計から外す。決定 Q11）")
    common(sp)
    sp.add_argument("--element", required=True, help="要素の ID（先頭でよい）")
    sp.add_argument("--reason", help="理由")
    sp.add_argument("--issue", help="この判断で閉じる要確認の ID")
    sp.set_defaults(func=cmd_exclude_room)

    sp = confirm_parser("approve-moves", "移動（意味の変更なし）をまとめて承認する（G-1、決定 Q1・Q15）")
    common(sp)
    sp.add_argument("--run", help="同定の ID（先頭でよい。既定: 最後の同定）")
    sp.add_argument("--exclude", nargs="*", help="一覧から外す item")
    sp.add_argument("--reason", help="理由（人が書く）")
    sp.set_defaults(func=cmd_approve_moves)

    sp = confirm_parser("choose", "要確認の選択肢を選ぶ（選択肢に書かれた採用・前提を書く。決定 13）")
    common(sp)
    sp.add_argument("--issue", required=True, help="要確認の ID（先頭でよい）")
    sp.add_argument("--option", required=True, help="選択肢の code（`btruth issues` に出る）")
    sp.add_argument("--reason", help="理由（人が書く）")
    sp.set_defaults(func=cmd_choose)

    sp = confirm_parser("resolve-recheck", "再確認の印を解く：保つ／変える／取り消す（G-2）")
    common(sp)
    sp.add_argument("--mark", required=True, help="再確認の印の ID（先頭でよい）")
    sp.add_argument("--choice", required=True, choices=["保つ", "変える", "取り消す"], help="保つ／変える／取り消す")
    sp.add_argument("--value", help="「変える」の新しい値（JSON として読める形）")
    sp.add_argument("--unit", help="単位")
    sp.add_argument("--reason", help="理由（人が書く）")
    sp.set_defaults(func=cmd_resolve_recheck)
    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    return args.func(args)
