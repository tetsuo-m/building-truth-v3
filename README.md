# building-truth-v3

図面と書類を読んで、建物の要素に判断とその根拠を紐づけ、後から追えるようにする DB（構想は非公開の `CONCEPT.md`。この README は中身を書き写さない）。

## 今の段

- 第1段（設計）：設計書 `DESIGN_STORE.md`（リポジトリの外）。決めていないことは `QUESTIONS.md`、起きた失敗は `docs/FAILURES.md`。
- 第2段（器と入口）：`btruth/`。器（SQLite）、読み手（DXF・CSV・文章）、取り込み、比べ方、レポート。どう作ったかは `docs/STEP2.md`、入れたライブラリは `docs/DEPENDENCIES.md`。
- 第3段以降（解釈と確定、同定、整合、出口）は、別の依頼書で。

## 使い方

```
python -m venv .venv
.venv\Scripts\python -m pip install -e .[dev]

python -m btruth init <物件のフォルダ> --name <物件の名前> [--office <事務所の共通フォルダ>]
python -m btruth import <物件のフォルダ> <ファイル> [--source <呼び名>] [--kind <書類の区分>] [--drawing-type <図面の種類>] [--discipline <分野>]
python -m btruth versions <物件のフォルダ>
python -m btruth compare <物件のフォルダ> <呼び名>@1 <呼び名>@2
python -m btruth report <物件のフォルダ> [--out <ファイル> [--html]]
python -m pytest -q
```

コマンドには物件のフォルダだけを渡す。正本の DB の場所は `<物件のフォルダ>/settings/project.csv` の `db_path`。

## 守り

- 承認・判断を確定させる操作は人だけが行う。Claude Code はフック（`.claude/hooks/`）で止まる。第2段には確定のコマンドはない。
- `CONCEPT.md` は人だけが直す。
- 会社の情報、実在の案件の図面、市販の本のデータは入れない。サンプル（`samples/`）は架空。
