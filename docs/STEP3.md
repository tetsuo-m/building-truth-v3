# 第3段 解釈と確定：どう作ったか、なぜそうしたか

依頼書 `BRIEF_v3_step3.md`。仕様は設計書 `DESIGN_STORE.md`（リポジトリの外）、前提は `CONCEPT.md`。ここでは中身を書き写さず、節と項目の番号で指す。

## 置き場所

| 場所 | 中身 |
|---|---|
| `btruth/propose.py` | 提案の JSON の形と登録（E-2）。ID を振り、規則の確かめ（E-3）を通し、はじかれた item も残す。すべての言い分は観測（mode=観測）。承認はしない |
| `btruth/checks.py` | 登録のときの軽い照らし（I-2 の一部。本番の照らしは第5段）：名前がない空間、境界の相手がない壁、壁が境界の外に出ている、壁が途中で終わる、建具表にない符号、知らない名前。区間は計算して保存しない（C-2c） |
| `btruth/effective.py` | 有効値（D-1 改訂 6）、item・要素の状態、部屋の面積・周長（出口で計算。B-10）、開いている要確認 |
| `btruth/review.py` | `review`・`review_premise` を書く**唯一**のコード（G-1）。端末の判定、y/N、承認の前の確かめ（決定 12）、採用の言い分を同じトランザクションで |
| `btruth/geometry.py` | 線分の重なり・区間・面積（C-2c、C-2e、E-3） |
| `btruth/show.py` | 理解の確認の画面（HTML。B-4）。要素をクリックすると根拠の手掛かりが光る |
| `btruth/measure.py` | AI の読みを固定の解釈と照らし、数を `run_summary` に残す（D-9） |
| `btruth/cli.py` | `clues / propose / items / issues / show / measure` と、確定のコマンド `approve / reject / hold / decide / name / exclude-room` |
| `.claude/hooks/guard_confirm.py` | フック：確定のコマンド（六つと `rule --set`）、DB のファイル（`*.sqlite`・`*.db`）と `sqlite3` を名指すコマンド、DB のファイルへの Edit・Write を止める（G-1 (a)、F-13） |
| `.claude/skills/read-drawing/SKILL.md` | Claude Code が図面を読んで提案を書く手順書。指紋（sha256）を `agent.instructions_sha256` に残す |
| `tests/fixtures/` | `step1`・`step2` の固定の解釈（提案の JSON）と、それを作るスクリプト |
| `samples/ai_run/` | Claude Code 自身の読み（測定に使った提案の JSON とスクリプト） |

## 提案の JSON（E-2）

形は `btruth/propose.py` の冒頭と、手順書 `SKILL.md` の 3 節に書いた。要点：

- 手掛かりは `平面図@1#13`（出どころ@版#手掛かりの番号）で指す。既存の要素は `{"id": …}` か `{"find": {"kind": "階", "name": "1階"}}`。
- 要素は `ref`・`kind`・`reason`・`confidence`・`evidence`・`claims`。つながりは `kind`・`from`・`to`・`role`。前提は `assumptions`。読めなかった手掛かりは `unreadable`（B-3）。
- `境界の相手` は、どの壁・開口が相手かだけ（区間は保存しない。改訂 6）。開口の `位置` は壁基準。
- 空間の境界は、部屋から見た輪郭の角と角のあいだに一つ（決定 Q13）。外に面した辺は外部の側の境界も作り `向かい合う`（決定 Q17）。

## 規則の確かめ（E-3）で、はじくもの

参照した手掛かり・要素・凡例がない／根拠にできるのは手掛かり・前提・凡例の要素・承認済みの要素だけ（C-8）／`含む` は要素ごとに一本（決定 10）／`くり抜く` は開口ごとに一本（決定 11）／境界の相手の壁・開口が境界の線分に重なる位置にない／向かい合う境界が同じ線分の上にない／部屋の境界が閉じた輪郭を作らない・面積がゼロ／同じ手掛かりを同じ種類の要素で二重に数える（同じ提案の中）／承認済みの要素と根拠がまったく同じ要素の作り直し（例6）。

**設計書の文言から一つ足した所（Q24）**：「承認済みの要素と根拠がまったく同じ」の判定に、`区切る` で区切る空間を加えた。同じ部屋割り線の両側の境界（左の部屋の東辺と右の部屋の西辺、部屋の辺と外部の側の辺）は、同じ手掛かりを根拠にする正しい別の要素だから。これなしでは、固定の解釈の承認の後に片側だけを読み直すと、はじかれる。

はじかれなかったが人に渡すもの（登録のときの照らし）：境界の相手がない壁（決定 2。腰壁・袖壁・塀）、壁が境界の外に出ている（決定 8、例10、F-1）、壁が途中で終わる（例11 の場合 3）、名前がない空間（B-12）、建具表にない符号（C-5、F-5）、知らない名前（J-5）。

## 有効値（D-1 改訂 6）

`effective.effective_value(store, project, 主体, 属性)`：
1. 最新の採用（`review` が生んだ claim）。再確認の印が付いても外さず `recheck=True` で返す（決定 9）。
2. なければ、`型である` の先の型の採用。
3. なければ、承認済みの観測。同じ出どころに新旧の版の承認済みが複数あれば最新の版のもの（決定 10）。複数の出どころなら `authority.csv` の主。決まらなければ「決まらない」。型と実物の観測が食い違えば「決まらない」（決定 9）。
4. なければ、既定の構成（規則の読み手）の観測。承認なしで使えるのはこれだけ（決定 11）。

item が「承認済み」かは、その item を指すレビュー（`interpretation_item`）か、item の ID を含むまとめてのレビュー（`interpretation`／`identity_run` の `choice_json.item_ids`）の、**最新**の行で読む（却下の後に承認すれば承認済み。B-6：行は書き換えない）。要素の claims は、その要素の `要素を作る` item の承認に従う（claim ごとの item は作らない）。

## 確定のコマンド（G-1）

| コマンド | 書くもの |
|---|---|
| `approve --interpretation ID [--exclude …]` | `review(target_kind=interpretation, action=まとめて承認, choice_json={item_ids})` 一行。一覧（要素の種類・名前・確かさ・根拠の版）を出してから y/N |
| `approve --item ID …` | 一つなら `review(target_kind=interpretation_item, action=承認)`。複数なら解釈ごとにまとめて承認 |
| `reject --item ID --reason …` | `却下`（理由は必須） |
| `hold --item ID` / `hold --issue ID` | `保留` |
| `decide --element ID --attribute A --value V [--unit] [--basis] [--issue]` | `review(target_kind=element, action=判断)` と `claim(mode=採用, review_id)` を同じトランザクションで。`--issue` で要確認も閉じる |
| `name --element ID --name N` | `名前を付ける` ＋ 採用の `名前` |
| `exclude-room --element ID` | `部屋として扱わない` ＋ 採用の `部屋として扱う=false`（決定 Q11） |

- `review_premise`（承認した時点の前提。B-14）：item の根拠の手掛かり（`interpretation_evidence`・`claim_evidence`）、頼った前提（`interpretation.premise_json`）、参照した要素、使った表の写し（`table_load` の最新）、判断なら比べた言い分。
- **承認の前の確かめ（決定 12）**：承認する要素が `ふさぐ・くり抜く・区切る・境界の相手・型である・集める・含む・…` で指す先、つながりの両端、言い分の主体が、承認済み（または既定の構成）か、同じ承認に入っているかを確かめる。だめなら `ApprovalBlocked` で止め、理由を出し、何も書かない。却下された開口をふさぐ建具だけの承認は止まる（テスト）。
- 理由（`reason`）は人が書く。コマンドは文章を作らない（F-3）。
- 要確認は、それを対象にしたレビュー（保留以外）で閉じる。加えて、条件が成り立たなくなった要確認は開いていない扱い（名前がない空間に名前が付いた、部屋として扱わないになった）。

## 承認を守る仕組み（G-1 (a)(b)(d)、F-13）と、手元の Windows の PC で確かめたこと（F-11）

| 守り | 作り | 手元の PC での確かめ（2026-11-08、このセッション） |
|---|---|---|
| (a) DB のファイル・`sqlite3` を名指すコマンドをフックで止める | `guard_confirm.py`：Bash に `.sqlite` / `.sqlite3` / `.db`（拡張子）か `sqlite3` の語があれば止める。Edit・Write・MultiEdit・NotebookEdit の対象が DB のファイルなら止める。`settings.json` の deny にも足した | `ls -la out/ai_run/db/truth.<拡張子>` → フックで止まった。`python -c "import sqlite3; …"` → 止まった。Write ツールで `out/ai_run/db/probe.db` → `settings.json` の deny で止まった |
| (b) 端末以外から呼ばれた btruth は `review`・`review_premise` に書かない | 書く処理は `btruth/review.py` だけ。`Store.insert` はこの二つの表を拒む。`require_terminal`：stdin・stdout・stderr の**三つ**が端末で、かつ `CLAUDECODE`・`CLAUDE_CODE_ENTRYPOINT`・`AI_AGENT` の環境変数がないとき だけ通す | Claude Code の Bash（Windows）で `sys.stdin.isatty()` は **True**、stdout・stderr は False だった（これが F-11 の正体：stdin だけ見ると端末に見える）。`_real_terminal()` は False、`is_terminal_for(out/ai_run の DB)` は False。取り込み・提案の登録・測定・画面は Claude Code から動いた |
| (c) 承認は端末からだけ、y/N | 六つの確定のコマンド。一覧を出してから `確定しますか？ (y/N)` | `btruth approve …`、`btruth name …` を Claude Code から打つ → `guard_confirm.py` で止まった（人が実行するよう促す文を表示） |
| (d) `review`・`review_premise` の UPDATE・DELETE を止めるトリガー | 第2段のまま。承認の後に UPDATE・DELETE が `IntegrityError` になることをテストで確かめた | 自動テスト（`test_review.py`、`test_failures_stage3.py`） |
| テストでの差し替え | 環境変数 `BTRUTH_TEST_TERMINAL=ok` は、DB が OS の一時フォルダの下にあるときだけ効く | `test_terminal_override_does_not_work_outside_the_temporary_folder`：`out/` の下の DB には効かない |
| F-12（フックが読み込まれているか） | 手順書の 0 節：わざと止められて確かめる | このセッションではフックが読み込まれていて、上のとおり止まった |

残っている穴（設計書 3-9 F-13 のとおり）：AI が Python のファイルを書いて実行すると、フックは中身を見られない。署名は問題になったときに足す。

## AI の読みの測定（3-5-1 (2)、D-9）

手順：`out/ai_run`（step1）と `out/ai_run2`（step2）に器を作り、`平面図`・`壁種表`・`仕上表` を取り込み、固定の解釈を登録。Claude Code が `btruth clues` で手掛かりを読み、手順書に従って提案を書き（`samples/ai_run/make_claude_proposals.py` → `step1_claude.json`、`step2_claude.json`）、`--instructions` 付きで登録し、`btruth measure` で照らした。承認はしていない。

| | step1 | step2 |
|---|---|---|
| 要素（固定／AI／一致） | 18 / 18 / 18 | 24 / 24 / 24 |
| 種類ごと | 通り芯 4/4、壁 4/4、部屋 1/1、空間の境界 8/8、壁種 1/1 | 通り芯 4/4、壁 5/5、部屋 2/2、空間の境界 12/12、壁種 1/1 |
| 一致した要素の言い分（全体／同じ値） | 34 / 33 | 43 / 41 |
| つながり（固定／AI／一致） | 29 / 29 / 29 | 43 / 43 / 43 |
| 人に渡した数 | 要確認 0、はじかれた 0 | 要確認 1（名前がない空間）、はじかれた 0 |

言い分の違いは、壁種の `構成` の JSON の書き方（キーの組）と、間仕切の `芯線` の向き（固定は南→北、AI は北→南。同定の照合は向きを問わないので要素は一致）。合格・不合格の線は引かない。数字は `run_summary(kind=AI の解釈の正しさの測定)` に残る（`out/` は Git に入れないので、この表が記録）。

## 受入の基準（依頼書 §4）

| 基準 | テスト |
|---|---|
| 固定の解釈で step1・step2 の期待値（面積 24.00、部屋 1／2、境界 4／8、要確認 0／1） | `test_review.py::test_step1_expected_values_after_approval`、`::test_step2_expected_values_after_approval` |
| はじかれた提案が残る | `test_propose.py::test_unresolved_reference_is_rejected_but_kept`、`::test_recreating_an_approved_element_…` |
| 例10 で兼ねる線から壁が二つ、全長の壁は要確認（F-1） | `test_failures_stage3.py::test_f1_*` |
| 却下した開口をふさぐ建具だけの承認が止まる（決定 12） | `test_review.py::test_approving_a_door_whose_opening_was_rejected_is_stopped` |
| 再確認の印が付いても有効値が変わらない（決定 9） | `test_effective.py::test_adopted_value_wins_and_survives_a_recheck_mark` |
| フックが承認のコマンドと DB への直接の書き込みを止める | `test_guard_confirm.py`（＋手元の PC での確かめ、上の表） |
| 端末以外から呼んだ btruth は `review` に書けず、取り込みと登録は動く | `test_review.py::test_review_refuses_outside_a_terminal`、`test_cli_stage3.py::test_approve_refuses_outside_a_terminal` |
| `review` の UPDATE・DELETE が失敗する | `test_review.py::test_review_rows_cannot_be_updated_or_deleted_after_a_real_approval` |
| テスト用の差し替えが物件のフォルダの DB に効かない | `test_review.py::test_terminal_override_does_not_work_outside_the_temporary_folder` |
| AI の読みの測定の数字が `run_summary` に残る | `test_measure_show.py`、上の表 |
| 第3段の失敗（F-1、F-3、F-5、F-13）の再現 | `test_failures_stage3.py` |

## 設計書と違う形にした所

- Q24（`QUESTIONS.md`）：承認済みの要素の作り直しの判定に、区切る空間を加えた（上）。
- 登録のときの照らし（`checks.py`）は、提案の観測の値（まだ承認されていない）で見る。設計書の照らし（I）は有効値だけを見るが、第3段の受入「全長の壁の提案が要確認になる」は提案の時点で出す必要があるため。第5段の本番の照らしは有効値で。
- 開いている要確認の読み方（決定 15）に「条件が成り立たなくなった要確認は開いていない」を足した（名前がない空間に限る）。
- `attributes.csv` に行を足した：`線分,通り芯`、`厚さ,壁種`、`階高,階`、建具の型の `幅・高さ・仕様`、材料の `名称`（E-1：行を足すだけ）。
