# 第2段 器と入口：どう作ったか、なぜそうしたか

依頼書 `BRIEF_v3_step2.md`。仕様は設計書 `DESIGN_STORE.md`（リポジトリの外）、前提は `CONCEPT.md`。ここでは中身を書き写さず、節と項目の番号で指す。

## 置き場所

| 場所 | 中身 |
|---|---|
| `btruth/schema.py` | 器：設計書 3-2 の A〜N の全部の表（45）。共通の列 `id`・`recorded_at`・`recorded_by`（0-2）。`review`・`review_premise` の UPDATE・DELETE を止めるトリガー（G-1 (d)）。器の版 `schema_migration` |
| `btruth/store.py` | 器への追記と読み。更新・削除の処理はない（例外は物件の設定 `set_project`。A-1）。`review`・`review_premise` への追記は拒む（G-1 (b)：承認のコマンドだけが書く。第3段） |
| `btruth/project.py` | 物件のフォルダ（`settings/project.csv`、`rules/`、`settings/`、`knowledge/`、`archive/`、`out/`）、器を作る、既定の構成（敷地・建物・1階・外部。C-2b、決定 Q17） |
| `btruth/tables.py` | 人が書く表（CSV）の写し（A-5、J）。事務所の共通フォルダ → 物件のフォルダの二段（決定 Q9）。読むときに物件が同じ鍵を上書きする |
| `btruth/readers/` | 読み手：DXF（ezdxf）、CSV、文章。ファイル → 手掛かりの行だけを作る（0-1、B-1） |
| `btruth/intake.py` | 取り込み：出どころ・属性・版・手掛かり・写し・取り込みの記録・CSV の写し。同じ sha256 は取り込まない（A-3）。生成物の見分け（H-2、M-1） |
| `btruth/compare.py` | 形式の違う図面の比べ方（B-14、3-3b 案1 の 1・2・4）：レイヤを役割に、枠を符号で揃え、幅の中で一致 |
| `btruth/report.py` | 手掛かりの一覧と読み残し（B-3）。テキスト／HTML。出したものは `generation` に記録（M-1） |
| `btruth/cli.py` | `btruth init / import / versions / compare / report`。物件のフォルダだけを渡す（G-1 (a)） |
| `btruth/defaults/` | 新しい物件に写す既定の CSV（J-1〜J-7、J-4）。IFC の名前の列つき（E-7） |
| `tests/` | 受入のテスト（下）。架空の図面だけ |

## 決めたこと（設計書の節と、実装での形）

- **ID と列**（0-2）：UUID v4 の文字列。`recorded_by` は、コマンドの `--by`、なければ環境変数 `BTRUTH_USER`、なければログインの名前。
- **積み重ね**（B-6）：`Store` に `insert` しかない。`review` のトリガーは「うっかりよけ」で守りではない（G-1 (d)）。
- **器の版**：`project.schema_version` と `schema_migration`。表を足すときは `schema.TABLES` に行を足し、版を上げて `create_all` を流す（`create table if not exists` なので作り直さない）。
- **既定の構成**（C-2b）：敷地・建物・1階・外部は、`agent(kind=規則の読み手)` の `interpretation(summary=既定の構成)` が作った要素。種類と名前は観測の言い分（D-2 の 3 番目、既定の読み方）。`集める` は 階→建物→敷地→物件（敷地の `集める` の相手は `project` の ID。`role_json={"to_kind":"project"}`）、外部→敷地。
- **書類の区分**（A-2）：`source.kind` は人が `--kind` で指定した区分、なければ空（NULL）。図面の種類と分野は `source_attribute`（`origin=コマンドで指定`。v2 Q57）。同じ呼び名の出どころに別の区分を指定したときは、`source_attribute(書類の区分)` の行を足す（訂正は行で）。
- **手掛かり**（B-1）：値は ezdxf が返す float を JSON の `repr` で書く（丸めない）。単位は `source_version.unit_factor`（`$INSUNITS` から。なければ 1.0 とみなして記録）。ブロックの定義は `BLOCK_DEF` の手掛かり、その中の図形は `parent_clue_id` で指す。レイヤごとの数・文字コード・修復・単位・ブロックの数を `intake_log` に書く（B-6）。
- **Jw_cad の DXF**：`$DWGCODEPAGE` がないので、物件の設定 `dxf_default_codepage`（既定 ANSI_932）を仮定して読み、そのことを記録する。表の名前が空で ezdxf の通常の読み込みが止まるので `ezdxf.recover` で読み、修復の数を記録する。座標は Jw_cad が書いたまま（原点のずれは比べるときに揃える）。
- **生成物**（H-2、M-1）：ファイルの sha256 が `generation` にあれば版ごと、レイヤが `rules.csv` の `generated_layer_prefix`（`BT_GEN_`）で始まればその手掛かりだけ、`generated_from` を付けて観測から外す。生成の記録がないときは印の文字を入れる（**Q21**）。
- **比べ方**（B-14）：役割は `settings/layer_roles.csv` の部分一致（`GRID` は `_0-2_GRID` にも当たる）。枠は、両方の版にある一番小さい `X`・`Y` の符号の文字の位置の交点（v2 Q62・Q65-3・Q66）。幅は `rules.csv` の `same_position_mm`・`same_angle_deg` だけ。文字はぴったり。揃えたこと・一致の数・追加の候補を、新しい版の `intake_log` に書く。これは第4段の同定の足場で、要素には触れない。
- **読み残し**（B-3）：観測の手掛かり（最上位、生成物でない、`BLOCK_DEF` でない）のうち、`interpretation_evidence`・`claim_evidence`・`assumption_evidence` のどれからも指されていないもの。第2段では解釈がないので全部が読み残し。
- **読み方の知識の CSV**：書いた日時の列は `written_at`（**Q22**）。

## 設計書と違う形にした所（`QUESTIONS.md`）

- Q21：生成の記録がない生成物の印（`generated_from` に `marker:BT_GEN_`）。
- Q22：`knowledge/readings.csv` の列 `recorded_at` → `written_at`。
- 設計書 3-5-1 の「Jw_cad で増えた CIRCLE 4」は事実と違った（`step1.dxf` にも符号の丸が 4 つある）。設計書を直し、二つの版は 21 の手掛かりがすべて一致する。

## 受入のテスト（依頼書 §5）

| 基準 | テスト |
|---|---|
| `step1.dxf`・`step1_JW.dxf`・`step2*.dxf` の手掛かりが丸めずに保存される | `test_readers.py`、`test_intake.py::test_import_step1_keeps_every_clue_unrounded` |
| 二つの形式の手掛かりが、役割に正規化し 0.1 mm の幅で一致する | `test_compare.py::test_step1_and_its_jwcad_export_match_within_tolerance`（21 が一致）、`..._candidates`（追加の候補の記録） |
| 同じ sha256 を二回取り込んでも行が増えない | `test_intake.py::test_same_sha256_is_not_imported_twice` |
| 生成専用レイヤの手掛かりが観測から外れる | `test_intake.py::test_generated_layer_is_kept_but_excluded_from_observation`、`..._excluded_whole` |
| 器の表に 3-2 の全部の単位がある | `test_schema.py::test_all_units_of_storage_exist` |
| 器を作ると「1階」が一つある | `test_init_project.py::test_default_structure_has_one_first_storey` |
| 3-9 の第2段の失敗（F-7）を再現して起きないことを確かめる | `test_failures_stage2.py` |
| 写したフックのテストが通る | `test_guard_hook.py`、`test_guard_confirm.py`、`test_guard_concept.py` |

## 第3段へ渡すこと

- `review`・`review_premise` に書く処理はない。`Store.insert` はこの二つを拒む。承認のコマンド（端末からだけ、y/N、一覧を出してから）は第3段で、`Store` の外に別の経路で作る。
- DB を直接書くコマンドを止めるフック（G-1 (a)）はまだ入れていない（第3段）。btruth のコマンドは今から DB のファイル名を受け取らないので、入れても止まらない。
