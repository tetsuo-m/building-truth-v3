# building-truth-v3

図面と書類を読んで、建物の要素に判断とその根拠を紐づけ、後から追えるようにする DB（構想は非公開の `CONCEPT.md`。この README は中身を書き写さない）。

## 今の段

- 第1段（設計）：設計書 `DESIGN_STORE.md`（リポジトリの外）。決めていないことは `QUESTIONS.md`、起きた失敗は `docs/FAILURES.md`。
- 第2段（器と入口）：`btruth/`。器（SQLite）、読み手（DXF・CSV・文章）、取り込み、比べ方、レポート。どう作ったかは `docs/STEP2.md`、入れたライブラリは `docs/DEPENDENCIES.md`。
- 第3段（解釈と確定）：提案の登録、規則の確かめ、有効値、承認のコマンド（端末からだけ）、理解の確認の画面、AI の読みの測定。どう作ったかは `docs/STEP3.md`。Claude Code が図面を読む手順は `.claude/skills/read-drawing/SKILL.md`。
- 第4段以降（同定、整合、出口）は、別の依頼書で。

## 使い方

```
python -m venv .venv
.venv\Scripts\python -m pip install -e .[dev]

python -m btruth init <物件のフォルダ> --name <物件の名前> [--office <事務所の共通フォルダ>]
python -m btruth import <物件のフォルダ> <ファイル> [--source <呼び名>] [--kind <書類の区分>] [--drawing-type <図面の種類>] [--discipline <分野>]
python -m btruth versions <物件のフォルダ>
python -m btruth compare <物件のフォルダ> <呼び名>@1 <呼び名>@2
python -m btruth report <物件のフォルダ> [--out <ファイル> [--html]]

python -m btruth clues <物件のフォルダ> <呼び名>@1              # AI が読む手掛かり（JSON）
python -m btruth propose <物件のフォルダ> <提案.json> [--instructions .claude/skills/read-drawing/SKILL.md]
python -m btruth items <物件のフォルダ> [--kind 壁]             # item と状態
python -m btruth issues <物件のフォルダ>                        # 開いている要確認
python -m btruth show <物件のフォルダ> [--out <HTML>]           # 理解の確認の画面
python -m btruth measure <物件のフォルダ> --interpretation <AI の解釈> --against <固定の解釈>

# 人が端末で打つ（一覧を出してから y/N。Claude Code はフックで止まる）
python -m btruth approve <物件のフォルダ> --interpretation <解釈の ID> [--exclude <item>…] --reason "…"
python -m btruth approve <物件のフォルダ> --item <item の ID>… --reason "…"
python -m btruth reject <物件のフォルダ> --item <item の ID> --reason "…"
python -m btruth hold <物件のフォルダ> --item <item の ID> | --issue <要確認の ID>
python -m btruth decide <物件のフォルダ> --element <要素の ID> --attribute 芯線 --value '[[0,0],[6000,0]]' --unit mm --reason "…" [--issue <要確認の ID>]
python -m btruth name <物件のフォルダ> --element <要素の ID> --name 倉庫 --reason "…" [--issue <要確認の ID>]
python -m btruth exclude-room <物件のフォルダ> --element <要素の ID> --reason "…" [--issue <要確認の ID>]

python -m pytest -q
```

コマンドには物件のフォルダだけを渡す。正本の DB の場所は `<物件のフォルダ>/settings/project.csv` の `db_path`。ID は先頭の数文字でよい（一つに決まれば）。

## 守り

- 承認・判断を確定させる操作は人だけが行う。確定のコマンドは端末からだけ動き（stdin・stdout・stderr が端末で、AI エージェントの環境でない）、一覧を出してから y/N で確かめる。Claude Code はフック（`.claude/hooks/guard_confirm.py`）で止まる。DB のファイルを直接扱うコマンドや `sqlite3` も止まる。
- `review`・`review_premise` を書くのは `btruth/review.py` だけ。書き換え・削除はトリガーで止まる。
- `CONCEPT.md` は人だけが直す。
- 会社の情報、実在の案件の図面、市販の本のデータは入れない。サンプル（`samples/`）と固定の解釈（`tests/fixtures/`）は架空。
