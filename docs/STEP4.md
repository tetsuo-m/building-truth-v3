# 第4段 版の同定と持ち越し：どう作ったか、なぜそうしたか

依頼書 `BRIEF_v3_step4.md`。仕様は設計書 `DESIGN_STORE.md`（リポジトリの外）の 3-3b、H、G-1、G-2、D-1。前提は `CONCEPT.md`。中身は書き写さず、番号で指す。

## 置き場所

| 場所 | 中身 |
|---|---|
| `btruth/identity.py` | 同定（一段目・二段目）。節点の網の目、面と角の対応、出どころごとの根拠の探し方、移動・壁に従う・意味が変わった、再確認の印、影響、AI に渡す範囲。`review` は書かない |
| `btruth/review.py` | 足したもの：移動のまとめての承認 `approve_moves`、再確認の印の解消 `resolve_recheck`、一覧に入れる移動の選び方 `moves_listing_items`。承認の前の確かめに「移動した要素そのものが承認済みか」を足した |
| `btruth/effective.py` | 足したもの：「取り消す」で採用が終わる。「移動の承認待ち」の要確認は、item が承認・却下・保留されたら閉じる |
| `btruth/checks.py` | `check_after_moves`：まとめての承認の後の照らし。壁と境界のずれを一件にまとめる（例1） |
| `btruth/diff.py` | 差分のレポート（テキストと HTML。`generation` に記録） |
| `btruth/kit.py` | 答えを見せない測定の場所（`docs/MEASURE.md`） |
| `btruth/cli.py` | `identify`・`diff`・`rechecks`・`kit`、`measure --mark/--list/--condition`、確定のコマンド `approve-moves`・`resolve-recheck` |
| `.claude/hooks/guard_confirm.py`、`.claude/settings.json` | 二つの確定のコマンドを止める一覧に足した |

## 同定の流れ（`btruth identify <物件> <出どころ>@<前の版> <出どころ>@<新しい版>`）

1. **座標の枠**（F-9）：両方の版にある一番小さい通り芯の符号の交点で揃え、`identity_run.frame_json` と `intake_log`（座標の枠の揃え方）に書く。
2. **節点の網の目**（B-7、決定 Q2）：役割が部屋割り線の線の端点と交点を 0.1 mm でまとめて節点に、節点のあいだを辺に、辺で閉じた輪を面にする。保存せず、結果だけを `mesh_json` に残す（節点・辺の数、足場、動いた節点、面の対応、角の対応、分かれた辺）。
3. **面と角の対応**：面は、足場の角（節点と、その角の二辺の向き）で対応させる。新しい面一つに入れば一致、二つ以上なら分割、新しい面一つに前の面の足場が二つ以上入れば統合。T 字の節点はまっすぐ通るので角ではなく、反対側の部屋の境界は分かれない（F-2、決定 Q13）。
4. **出どころごとの根拠**（決定 16）：要素の根拠の手掛かりを出どころで分け、新しい版が来た出どころのものだけを新しい版で探す。表（CSV）の根拠は持ち越す。
5. **分け方**：
   - 部屋：面が一致なら一致。分割・統合は「判断できない」で候補（新しい面の角）を人に渡す。
   - 部屋の境界：部屋が一致なら角の対応で。両端が足場なら一致、角が動けば移動（新しい線分と、その線分が載る新しい部屋割り線を根拠に）。部屋が分割・統合なら判断できない。
   - 壁・通り芯・外部の側の境界：根拠の線が見つかれば一致。なければ、同じ役割の平行な線で `wall_move_max_mm` 以内のものが一本だけあれば移動。
   - 開口・建具：くり抜く壁の動きの分だけずらして手掛かりが見つかれば「一致（壁に従う）」で、移動の一覧に入れない（例9、決定 11）。絶対の位置は保存せず、壁の芯線の有効値と壁基準の位置から計算する（`propose.opening_segment`）。手掛かりが元の位置に残り、壁から総厚の半分＋50 mm を超えて離れたら「判断できない」と要確認「建具が壁から外れた」。
   - 同じ位置で文字・ブロックの中身だけが変わった手掛かりは「意味が変わった」（案3）。
6. **書くもの**：同定の解釈（エージェント＝規則の読み手、名前＝同定）。移動ごとに、新しい位置の観測（出どころ＝新しい版）と item（`既存の要素と同じ`）。`identity_link`、`impact`（変わった要素と、つながりで一段先の要素）、判断の付いた要素が一致でなければ `recheck_mark`、分割した部屋の境界の `向かい合う` の `relation_end`、要確認（移動の承認待ち、部屋の分割・統合、建具が壁から外れた、意味が変わった、消えた部屋・壁）、`intake_log`（追加の候補、AI に渡す範囲）、`run_summary`。
7. **AI に渡す範囲**（案4）：判断できない・消えた・意味が変わった要素の根拠と、追加の候補の手掛かりの外接矩形を `reread_margin_mm` だけ広げ、その中の手掛かりと、縁に触れる要素（文脈の要素）を記録する。

## 移動のまとめての承認と、再確認の印（G-1、G-2、決定 Q1・Q15）

- `btruth approve-moves <物件> --run <同定の ID>`：同定の「移動（意味の変更なし）」で、まだ提案中のもの全部を一覧に出してから y/N。`review(target_kind=identity_run, action=移動をまとめて承認, choice_json={item_ids})` を一行書く。`--exclude` で外せる。移動の量では絞らない。
- 一覧に入れないもの：その属性に判断（採用）が付いている要素（再確認の印が付く。一つずつ `approve --item` で）、意味が変わった要素、判断できないもの。
- 承認の後に、`check_after_moves` が照らす。`step2_boundary_only` では、壁 A（2300 のまま）と境界（2800）のずれを一件「壁と境界のずれ」にまとめ、選択肢「境界線に合わせる」「追従を外す」を出す。採用は書かない。
- `btruth resolve-recheck <物件> --mark <印> --choice 保つ|変える|取り消す`：保つは採用のまま印が消える。変えるは新しい採用を書く。取り消すは採用が終わり、有効値は承認済みの観測に戻る。印が付いている間も、有効値は採用のまま（決定 9）。
- 有効値の新旧（決定 10）：同じ出どころに承認済みの観測が新旧の版であれば、新しい版のものを使う。新しい版の移動が保留なら前の値（テストで確かめた）。

## 受入の基準ごとの結果（依頼書 §3）

| 基準 | 結果 | テスト |
|---|---|---|
| `step2_moved` で全 ID 一致、移動の承認待ち 1 件 → まとめての承認 → 開いている要確認は名前なし 1 件 | 通った。移動は壁 1・境界 6 の 7 件、どれも 500 mm。承認の後に左 11.20 ㎡・右 12.80 ㎡ | `test_identity.py::test_step2_moved_keeps_every_id_and_waits_for_one_batch` |
| `step2_boundary_only` で採用が動かず、まとめての承認の後にずれ 1 件（選択肢 2 つ）、壁の有効値は 2300 | 通った。移動は境界 6 件だけ。照らしをもう一度走らせても二件目は出ない | `::test_step2_boundary_only_keeps_the_wall_and_hands_over_one_offset` |
| `mesh_json` に節点 6・辺 7・足場 4 | 通った（動いた節点 2、面 一致・一致） | `::test_mesh_json_has_nodes_6_edges_7_anchors_4` |
| 片側の部屋にだけ間仕切を足すと、その部屋は判断できない、反対側の境界の ID と判断が残る（F-2） | 通った。節点 8、分かれた辺 2。左の境界の判断に印は付かない。`向かい合う` だけが終わる | `::test_partition_added_to_the_right_room_only_keeps_the_left_boundary` |
| 壁と一緒に動いた扉が移動に数えられず、扉の絶対の位置が新しい壁から計算される（例9） | 通った。承認の前は (2300, 1100)〜(2300, 1900)、承認の後は x 2800 | `::test_a_door_moving_with_its_wall_is_not_a_move`（ほかに、壁から外れた扉、符号が変わった扉） |
| 判断の後に根拠が変わると再確認の印、有効値は採用のまま（決定 9） | 通った。印の解消（保つ・変える・取り消す）も | `::test_a_judged_wall_*`、`::test_recheck_resolution_*` |
| 同じ図面を二回読んでも ID が揺れない（例6） | 通った。中身が違うが形が同じファイルで、全部一致、item 0 | `::test_the_same_geometry_twice_keeps_every_id`（登録の側の守りは第3段の `test_propose.py`） |
| 平面図だけ改版したとき、表の根拠が「見つからない」にならない（決定 16） | 通った | `::test_unchanged_tables_are_carried_over` |
| 第4段の失敗（F-2、F-4、F-8、F-9）の再現 | 通った。`docs/FAILURES.md` の「確かめた」に書いた | 上のテストと `::test_shifted_origin_is_aligned_on_the_grid_labels_and_recorded` |
| 新しい確定のコマンドが Claude Code から止まる（F-11） | 手元の Windows の PC で止まった（下） | `test_guard_confirm.py` |

## 手元の Windows の PC で確かめたこと（2026-11-08、このセッション）

- Claude Code の Bash から `btruth approve-moves out/try4 --run 93cb8719 …` を打つ → `guard_confirm.py` で止まった（「このコマンドは人が実行してください」）。
- `btruth resolve-recheck out/try4 --mark x --choice 保つ …` → 同じく止まった。
- 端末の判定：この Bash では stdin が端末、stdout・stderr は端末でない。`_real_terminal()` は False、`is_terminal_for(out/try4 の DB)` は False。フックを抜けても書けない。
- 取り込み・提案の登録・同定・差分・測定の印は、Claude Code から動いた。

## 人が試す DB（`out/try4`）と、打つ順

テスト用の解釈（固定の解釈）は入れていない（F-14）。入っている解釈は三つで、`items` の出力の名前で区別できる。報告の前に、下の ID が名前のとおりであることを `items` の出力で照らした。

| 名前（`items` の表示） | 解釈の ID | 何か |
|---|---|---|
| `Claude Code` | `412d42c0` | 版1（`step2.dxf`）の AI の読み。第3段で Claude Code が書いた `samples/ai_run/step2_claude.json`（答えを知った状態で書いたもの。承認の試しには使える） |
| `同定` | `59edf8ce` | 版1 → 版2（`step2_moved.dxf`）の移動 7 件。同定の ID は `93cb8719` |
| `規則の読み手` | `52ba3fc4` | 既定の構成（承認は要らない） |

リポジトリのフォルダで PowerShell を開き（Claude Code の中ではない）、この順で打つ。どの確定のコマンドも、一覧を出してから「確定しますか？ (y/N)」と聞く。

```
.venv\Scripts\python -m btruth items out\try4
.venv\Scripts\python -m btruth show out\try4                    # out\try4\out\show.html を図面と見比べる
.venv\Scripts\python -m btruth approve out\try4 --interpretation 412d42c0 --reason "図面と見比べた"
.venv\Scripts\python -m btruth diff out\try4 --run 93cb8719      # 同定の結果（移動 7、どれも 500 mm）
.venv\Scripts\python -m btruth approve-moves out\try4 --run 93cb8719 --reason "間仕切の移動を確かめた"
.venv\Scripts\python -m btruth diff out\try4 --run 93cb8719 --out out\try4\out\diff.html --html
.venv\Scripts\python -m btruth issues out\try4                   # 名前がない空間 1 件だけが残る
```

- 版1の承認より先に `approve-moves` を打つと、「移動した要素がまだ承認されていない」で止まる（Q25）。
- `issues` に残る「名前がない空間」は左の部屋（要素 `accdc90b`、要確認 `b61898e4`）。名前を付けるなら `btruth name out\try4 --element accdc90b --name 倉庫 --reason "…" --issue b61898e4`。
- 試し直すときは `out\try4` を消し、この文書の作り方で作り直す（`init` → `import` 三つ → `propose samples\ai_run\step2_claude.json` → `import step2_moved.dxf --source 平面図 --next` → `identify 平面図@1 平面図@2`）。ID は変わる。

## 測定（依頼書 §1-2）

- 第3段の測定の数字（`out/ai_run`、`out/ai_run2`）に「答えを知った状態」の印を足した（`btruth measure --list` で見える）。D-9 の測定ではない。
- 答えを見せない測定の手順は `docs/MEASURE.md`。`btruth kit` が、手掛かりの JSON・手順書・守りだけの場所を作り、人が新しい Claude Code をそこで起動する。手順書 `SKILL.md` から、読む側が固定の解釈を登録する手順を外した。

## 設計書と違う作り方をした所

- **Q25**：版1が未承認でも同定できるよう、提案中の要素も提案の根拠で照らす（どちらで照らしたかを `basis_json.根拠の時点` に残す）。移動の item は元の要素の承認を待つ。承認済みの要素の根拠は、`review_premise` の代わりに、承認された言い分と item の根拠の手掛かりで読む（同じ手掛かり）。
- **Q26**：部屋は一致したが角の数が変わったとき、境界を分けずに「判断できない」で人に渡す。
- **Q28**：設計書 3-3b 案1-5 の「変わった（一部の根拠が見つからない）」は、`identity_link.verdict` の一覧（H-2）にないので、`判断できない`（理由＝根拠が変わった）にした。ただし、壁の芯線・境界の線分など**値の根拠**が見つかって補助の根拠だけが見つからないときは、一致（`facts.補助の根拠が見つからない`）にした。`step2_boundary_only` の壁 A（芯線は同じ、部屋割り線だけが動いた）を一致にするため。
- **Q27**：再確認の印は、判断（採用）の付いた要素の同定が一致でないときに付ける。判断の前提の手掛かりの一つが見つからないだけでは付けない（例：左の部屋の名前の判断は、間仕切が動いても部屋が一致なので付かない。D-8）。
- 照らしの要確認の種類の名前は「壁と境界のずれ」にした（設計書の例1 は「言い分の食い違い（観測と期待）」）。中身と選択肢は例1 のとおり。
