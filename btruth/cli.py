"""The btruth command (stage 2): init / import / versions / compare / report.

Every subcommand takes the project folder; the database path comes from settings/project.csv
(G-1 (a): no *.sqlite on the command line, so the hook that stops direct database writes does not
stop btruth). There is no confirmation command here (stage 3; terminal only; G-1 (b)).
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path


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


def cmd_init(args) -> int:
    from btruth.project import init_project
    project = init_project(Path(args.folder), name=args.name, office_dir=Path(args.office) if args.office else None,
                           recorded_by=_who(args))
    print(f"器を作りました: {project.folder}（物件 {args.name}）。正本の場所は settings/project.csv の db_path。")
    return 0


def cmd_import(args) -> int:
    from btruth.intake import SourceExists, SourceNotFound, UnsupportedFormat, import_file
    from btruth.project import ProjectFolder, open_store
    project = ProjectFolder.load(Path(args.folder))
    mode = "new" if args.new else ("next" if args.next else "auto")
    with open_store(project) as store:
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
    from btruth.project import ProjectFolder, open_store
    project = ProjectFolder.load(Path(args.folder))
    with open_store(project) as store:
        rows = store.all("select s.name, s.kind, v.seq, v.file_name, v.imported_at, v.id from source_version v "
                         "join source s on s.id=v.source_id order by s.name, v.seq")
        for r in rows:
            print(f"{r['name']}@{r['seq']}  {r['file_name']}  区分={r['kind'] or '（未指定）'}  {r['imported_at']}  {r['id']}")
        if not rows:
            print("取り込んだ版はまだありません。")
    return 0


def cmd_compare(args) -> int:
    from btruth.compare import compare_versions
    from btruth.project import ProjectFolder, open_store
    project = ProjectFolder.load(Path(args.folder))
    with open_store(project) as store:
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
    from btruth.project import ProjectFolder, open_store
    from btruth.report import build_report, render_text, write_report
    project = ProjectFolder.load(Path(args.folder))
    with open_store(project) as store:
        if args.out:
            out = write_report(store, project, Path(args.out), html=args.html, recorded_by=_who(args))
            print(f"レポートを書きました: {out}")
        else:
            print(render_text(build_report(store, project)))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="btruth", description="building-truth v3 — 器と入口（第2段）")
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
    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    return args.func(args)
