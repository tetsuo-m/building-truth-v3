# building-truth-v3

**Trace every design decision back to its evidence — across drawings, schedules, and meeting minutes.**

building-truth is a database that sits next to an architect's everyday tools (CAD drawings exported as DXF, and spreadsheets). AI reads the drawings and documents and proposes building elements (rooms, walls, openings, doors, wall types); a human reviews and approves them. Every element gets a stable ID, every value keeps its source, and every human decision is stored with its reason, so that months later you can still answer *"why is this door 900 mm, and who decided it?"*

日本語の説明は [下の方](#日本語) にあります。

---

## The problem

In small design offices, one person is the hub that connects the plan drawing, the door schedule, the wall-type table, the finish schedule, meeting minutes, and the building code. When one partition moves, that person chases the change through every table by hand — and the *reasons* behind decisions live only in their head.

Software engineers solved this long ago with version control, diffs, and code review. Drawings have none of that, because a drawing has no stable "line" that means the same thing from one revision to the next. Lines get redrawn, split, and overlapped every time.

## The idea

- **Lines are evidence, not things.** Raw drawing entities and table rows are stored unchanged, with no IDs.
- **IDs go on interpretations.** AI interprets the evidence as building elements (a wall, a room, a space boundary, an opening). Those elements get IDs, and each one points back to the exact lines and rows it was read from.
- **Only humans make values final.** The AI proposes; a person approves, rejects, or decides — from a real terminal, with a `y/N` confirmation. Nothing the AI says becomes an adopted value on its own.
- **Revisions are compared database-to-database, not drawing-to-drawing.** When a new revision arrives, elements are matched to the previous ones, so their IDs — and the decisions attached to them — carry forward. Moves can be approved in one batch.
- **Consistency is checked across all sources.** For each attribute of each element, every source's claim is lined up. A document ranking (law > minutes > site briefing > special specs > design drawings > office standards > standard specs) decides which one is correct; the lower-ranked document gets a correction proposal.
- **Outputs come from the same truth.** Area, finish, and quantity tables, generated drawings, write-back of approved fixes into a *new* DXF, and IFC4 export (with a GlobalId ↔ database-ID mapping table).

The data model follows IFC concepts (spatial structure, space boundaries, openings, type vs. occurrence, material layer sets) and IDS for checkable requirements, while keeping what IFC cannot hold: multiple claims per attribute, evidence, AI proposals, reviews, and revision identity.

## What the demo shows

Fictional sample data: a two-room office plan (DXF), a door schedule and a wall-type table (CSV), and meeting minutes (text).

1. Import the drawing and documents. Claude Code reads them and registers a proposal.
2. Open the review page: click an element and the lines it was read from light up.
3. Approve from the terminal. (If Claude Code tries the same command, a hook stops it.)
4. A conflict appears: the minutes say door type AD-1 is **900 mm**, the door schedule says **800 mm**. The minutes rank higher.
5. The human chooses *"change the type AD-1 to 900"*. The opening in the wall follows automatically, because its width is read through *opening → door → door type*.
6. The plan drawing still shows 800, so a drawing correction is proposed. After approval it is written to a new DXF (the original is never overwritten) and checked in a CAD program.
7. Export IFC4 and open it in a free IFC viewer.

## How it was built with Claude

- **Claude (chat)** worked with the author on the concept and design: every structural decision has a written reason, and a single concept document (kept private) is the source of truth.
- **Claude Code** wrote all of the code, test-first (319 tests), one stage at a time from written briefs. The author is an electrical/architectural designer and a programming beginner; he wrote the specifications and made every decision.
- **Two independent AI reviews** of the design found real gaps (for example, a value could change without human approval when a re-check mark was raised). They were fixed before the code reached them.
- **Guard rails, not promises.** In an earlier version, Claude Code once approved its own proposals and even wrote the reasons. Since then, approval commands run only from a human terminal, hooks block Claude Code from running them or writing the database directly, and approval tables are append-only.
- **Failures are recorded, not hidden.** [`docs/FAILURES.md`](docs/FAILURES.md) lists 15 real failures and what prevents each one now — including the time Claude Code started writing a script that would have slipped past a hook, was stopped, deleted it, and reported it itself.

## Status and limits

Built: stages 1–6 (storage, intake, interpretation and approval, revision identity, cross-source consistency, outputs including IFC4).
Not yet: electrical systems and code checks (stage 7), signing human approvals (planned before real projects), and an honest accuracy measurement of the AI reading on unseen drawings (`docs/MEASURE.md` describes how).

## Quick start

Requires Python 3.11+ on Windows (PowerShell).

```
python -m venv .venv
.venv\Scripts\python -m pip install -e .[dev]
.venv\Scripts\python -m pytest -q
```

The full command list is in the Japanese section below. Step-by-step trial procedures are in `docs/STEP4.md`–`docs/STEP6.md`.

## License

MIT. See [LICENSE](LICENSE).

---

## 日本語

図面と書類を読んで、建物の要素に判断とその根拠を紐づけ、後から追えるようにする DB です。CAD（DXF）と表計算での今の作業はそのままにして、その横に置きます。

- 図面の線や表の行は「手掛かり」として、そのまま保存します。線には ID を付けません。
- AI が手掛かりを読んで、部屋・壁・空間の境界・開口・建具・壁種などの要素として提案します。ID は、この解釈した要素に付きます。
- 値を確定するのは人だけです。承認・判断は、人が打つ端末からだけ動き、y/N で確かめます。Claude Code はフックで止まります。
- 版の比較は、図面どうしではなく DB どうしで行います。同じ要素なら ID を引き継ぐので、付いていた判断も次の版へ引き継がれます。
- 整合は、全部の出どころを通して取ります。書類の格（法律 ＞ 議事録 ＞ 現場説明書 ＞ 特記仕様書 ＞ 設計図 ＞ 事務所の基準 ＞ 標準仕様書）で正を示し、格の低い書類に修正案を出します。
- 面積表・仕上表・数量表、生成した図面、承認した修正の書き戻し（新しい DXF）、IFC4 を、同じ正本から出します。

### 今の段

- 第1段（設計）：設計書は非公開。決めていないことは `QUESTIONS.md`、起きた失敗は `docs/FAILURES.md`。
- 第2段（器と入口）：器（SQLite）、読み手（DXF・CSV・文章）、取り込み、比べ方、レポート。`docs/STEP2.md`、`docs/DEPENDENCIES.md`。
- 第3段（解釈と確定）：提案の登録、規則の確かめ、有効値、承認のコマンド（端末からだけ）、理解の確認の画面、AI の読みの測定。`docs/STEP3.md`、`.claude/skills/read-drawing/SKILL.md`。
- 第4段（版の同定と持ち越し）：節点の網の目による同定、移動のまとめての承認、開口の壁基準の比べ方、再確認の印、差分のレポート、原点の揃え。`docs/STEP4.md`、`docs/MEASURE.md`。
- 第5段（出どころの整合）：表・凡例・議事録を出どころに、主の表と格の表で照らす、出どころの間の同定、意味の面の変化、要確認の選択。`docs/STEP5.md`。
- 第6段（出口）：面積表・仕上表・数量表、生成した図面、書き戻し、IDS の読み手、IFC（IFC4）と対応表。`docs/STEP6.md`。
- 第7段以降（系統・条件・測定）は、これから。

### 使い方

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
python -m btruth issues <物件のフォルダ> [--detail]             # 要確認（何が・選べること・打つ例。JSON は --detail）
python -m btruth show <物件のフォルダ> [--out <HTML>]           # 理解の確認の画面
python -m btruth measure <物件のフォルダ> --interpretation <AI の解釈> --against <固定の解釈>
python -m btruth measure <物件のフォルダ> --list | --mark <測定の ID> --note "…"
python -m btruth kit <物件のフォルダ> --versions 平面図@1 壁種表@1 --dest <測定の場所>   # 答えを見せない測定（docs/MEASURE.md）

python -m btruth identify <物件のフォルダ> 平面図@1 平面図@2     # 版の同定（承認はしない。移動は承認待ちの item に）
python -m btruth diff <物件のフォルダ> [--run <同定の ID>] [--out <ファイル> [--html]]
python -m btruth rechecks <物件のフォルダ>                        # 開いている再確認の印
python -m btruth check <物件のフォルダ> [--element <要素の ID>…]     # 整合の照らし（読むだけ。承認の後にも走る）
python -m btruth identify-sources <物件のフォルダ> --interpretation <新しい出どころの解釈>
python -m btruth values <物件のフォルダ> --element <要素の ID>      # 属性ごとの有効値と出どころ
python -m btruth tables <物件のフォルダ> [--out <フォルダ>]         # 面積表・仕上表・数量表（CSV と HTML）
python -m btruth drawing <物件のフォルダ> [--out <DXF>]             # 生成した図面（BT_GEN_ のレイヤ）
python -m btruth writeback <物件のフォルダ> --source 平面図 --original <元の DXF> --out <新しい DXF>
python -m btruth writebacks <物件のフォルダ>
python -m btruth ifc <物件のフォルダ> [--out <IFC>] [--generation <止めた ID>]

# 人が端末で打つ（一覧を出してから y/N。Claude Code はフックで止まる）
python -m btruth approve <物件のフォルダ> --interpretation <解釈の ID> [--exclude <item>…] --reason "…"
python -m btruth approve <物件のフォルダ> --item <item の ID>… --reason "…"
python -m btruth reject <物件のフォルダ> --item <item の ID> --reason "…"
python -m btruth hold <物件のフォルダ> --item <item の ID> | --issue <要確認の ID>
python -m btruth decide <物件のフォルダ> --element <要素の ID> --attribute 芯線 --value '[[0,0],[6000,0]]' --unit mm --reason "…" [--issue <要確認の ID>]
python -m btruth name <物件のフォルダ> --element <要素の ID> --name 倉庫 --reason "…" [--issue <要確認の ID>]
python -m btruth exclude-room <物件のフォルダ> --element <要素の ID> --reason "…" [--issue <要確認の ID>]
python -m btruth approve-moves <物件のフォルダ> --run <同定の ID> [--exclude <item>…] --reason "…"
python -m btruth resolve-recheck <物件のフォルダ> --mark <印の ID> --choice 保つ|変える|取り消す [--value …] --reason "…"
python -m btruth choose <物件のフォルダ> --issue <要確認の ID> --option <選択肢の code> --reason "…"
python -m btruth confirm-drawing <物件のフォルダ> --writeback <書き戻しの ID> --reason "…"
python -m btruth allow-ifc <物件のフォルダ> --generation <止めた IFC の ID> --reason "…"

python -m pytest -q
```

コマンドには物件のフォルダだけを渡します。正本の DB の場所は `<物件のフォルダ>/settings/project.csv` の `db_path`。ID は先頭の数文字でよい（一つに決まれば）。

### 守り

- 承認・判断を確定させる操作は人だけが行います。確定のコマンドは端末からだけ動き、一覧を出してから y/N で確かめます。確かめの前に、先に入力されて残っている文字は捨てます。Claude Code はフック（`.claude/hooks/guard_confirm.py`）で止まります。DB のファイルを直接扱うコマンドや `sqlite3` も止まります。
- `review`・`review_premise` を書くのは `btruth/review.py` だけです。書き換え・削除はトリガーで止まります。
- 守りに止められたら、くぐらずに止まって人に聞く（`CLAUDE.md`）。
- 構想の文書（`CONCEPT.md`）は非公開で、人だけが直します。
- 会社の情報、実在の案件の図面、市販の本のデータは入れません。サンプル（`samples/`）と固定の解釈（`tests/fixtures/`）は架空です。
