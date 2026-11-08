# 第6段 出口：どう作ったか、なぜそうしたか

依頼書 `BRIEF_v3_step6.md`。仕様は設計書 `DESIGN_STORE.md`（リポジトリの外）の H、M、L、3-8、3-5-2。前提は `CONCEPT.md`。中身は書き写さず、番号で指す。

## 置き場所

| 場所 | 中身 |
|---|---|
| `btruth/outputs.py` | 面積表・仕上表・数量表（CSV と HTML。有効値から計算し保存しない）、生成した図面（`BT_GEN_` のレイヤ）、書き戻し（承認した図面の修正案を新しい DXF に） |
| `btruth/readers/ids_reader.py` | IDS の読み手（specification を一つずつ手掛かりに）。取り込みが `condition` の行を作る |
| `btruth/conditions.py` | 条件（IDS）を有効値に照らす。`condition_check` と要確認「条件を満たさない」 |
| `btruth/ifc.py` | IFC の出口（IFC4。標準ライブラリだけで STEP の文字を書く）、対応表（CSV）、レポート |
| `btruth/review.py` | 足した確定のコマンド：`confirm_drawing`（書き戻した図面を CAD で確かめた）、`allow_ifc`（それでも出す） |
| `btruth/display.py` | 要確認の表示を、ふつうの文と、選べることと、打つコマンドの例に |
| `btruth/consistency.py` | 足したもの：判断で型の値を変えたら許容差によらず図面の修正案（機械で読める `drawing_fix` 付き）、壁種の層と断熱材、柱の偏心の上限 |
| `btruth/cli.py` | `tables`・`drawing`・`writeback`・`writebacks`・`ifc`、`issues --detail`、確定のコマンド `confirm-drawing`・`allow-ifc`。`choose` の後にも照らしが走る |

## 人の決定（§1）と、人の試しで分かった直し

- **Q29〜Q31** の答えを書き、設計書の【仮】の印を外した。
- **判断で型の値を変えたら、許容差によらず図面の修正案**：照らしは、型の値が採用（人の判断）なら、図面の開口の値とぴったり比べ、違えば「言い分の食い違い（主と従）」に図面の修正案を出す。修正案には、どの要素のどの属性をどの値にするか、どの手掛かりを直すかを `drawing_fix` として持つ（書き戻しがこれを使う）。`rules.csv` の許容差は変えていない。設計書の I と C-2d に書いた。
- **確かめの前に、先に入力された文字を捨てる**：`prompt_confirm` が聞く前に、端末に残っている入力を捨てる（Windows は `msvcrt`、ほかは `termios`）。端末でないとき（テスト、パイプ）は何もしない。すべての確定のコマンドがここを通る。
- **要確認の表示**：一件ずつ、`■ 種類［重さ］`、`要確認の ID：…`、`対象：…（要素 …）`、`何が：`（例「建具の型 AD-1 の「幅」が食い違っている。議事録4（格 2）は 900、建具表（格 5）は 800。…」）、`修正案：`、`選べること：［code］ 説明`、`打つ例：… btruth choose … --issue … --option …`。JSON は `--detail` のときだけ。`items` と承認の前の一覧は、打つ ID（item）を先に出し、要素の ID は「参考」として後ろに出す。
- **第5段で残ったもの**：壁の断熱材（凡例で読んだ）が壁種の層にないと要確認（例4）。柱が通り芯の交点から `column_offset_max_mm`（500）を超えて離れたときだけ要確認「柱の偏心が上限を超える」、上限の中は普通の納まり（例2、v2 Q7、D-8）。室番号での出どころの間の同定のテスト（B-13）。

## 出口

- **表**（`btruth tables`）：面積表（部屋として扱わない部屋は別に）、仕上表（床・幅木・壁・天井・天井高の有効値）、数量表。数量は v2 Q17〜Q20・Q31 のとおり：張り上げ高さ = 天井高 + 100、壁の面積 = 周長 × 高さ − 開口（0.5 ㎡ を超えるものだけ）、ボードの枚数 = 切り上げ（面積 ÷（0.91 × 1.82）×（1 + 0.10））、部屋ごと。天井高のない部屋は数えず「数えられなかったもの」に理由を出す（要確認は重ねない）。ルールの表に `board_height_extra_mm`・`board_width_mm`・`board_length_mm` を足した。どの時点の有効値かを `generation.as_of_json` に記録する。
- **生成した図面**（`btruth drawing`）：壁の両面の線（有効値の芯線と厚さ）と室名・面積を、`BT_GEN_WALL_FACE`・`BT_GEN_ROOM_NAME` に書く。そのまま取り込むと、版ごと生成物として観測から外れる（sha256）。人が自分のレイヤに描き足して取り込むと、描き足しだけが観測になる（例7）。
- **書き戻し**（`btruth writeback`）：人が `choose` で「図面の修正案」の選択肢を選んだもの（`applies_drawing_fix`）だけを書く。書く前に、人の元の図面（`--original`）の sha256 が、取り込んだ版と同じかを確かめ、違えば何も書かず、書かなかったことを記録する。元の図面は上書きしない（新しいファイル）。開口の幅は扉のブロックの尺度を幅の比で掛け、壁芯線は線の端点を動かす。Jw_cad の DXF は図形の番号（handle）が重なることがあるので、図形は種類・レイヤ・形で探す。書き戻した図面は、人が `confirm-drawing` を打つまで「未確認」。書き戻した図面をそのまま取り込むと、生成物ではなく人の図面として読み、`source_version.writeback_id` で書き戻しと結ぶ。
- **IDS**：`.ids` のファイルを `--kind 条件` で取り込むと、specification ごとに手掛かりと条件の行ができる。区分は IDS の `<purpose>`（なければ図面の種類）から（Q32）。
- **IFC**（`btruth ifc`）：IFC4（ADD2 TC1、スキーマの名前 `IFC4`）。承認済みの要素だけを有効値で出す。
  - GlobalId は UUID から決まった変換。分けた境界・仮想の要素・まとめた関係・性質の組は、決まった部品から UUID v5 を作って変換する。二回出しても同じ。
  - 物件 → 敷地 → 建物 → 階 → 部屋（IfcSpace）、外部（IfcExternalSpatialElement）、壁（IfcWall。芯線と厚さと高さで押し出し）、柱、開口（IfcOpeningElement。空間の構成に入れない。IfcRelVoidsElement）、建具（IfcDoor／IfcWindow。IfcRelFillsElement）、型（IfcWallType・IfcDoorType。IfcRelDefinesByType は型ごとに一つ。Q33）、通り芯（IfcGrid）、材料（IfcMaterialLayerSet）、境界（IfcRelSpaceBoundary。区間ごと。開口が相手の区間は開口、相手のない区間だけ IfcVirtualElement）、性質（`BT_Common.ElementId`、`HasOpenIssue`、`HeightAssumed`、`attributes.csv` の組）、数量（Qto_SpaceBaseQuantities・Qto_WallBaseQuantities を計算）、書類の参照（有効値の出どころの版）。
  - 座標は、人に見せる表示と同じく、通り芯の符号の交点を原点にした mm。
  - 一緒に出すもの：対応表（`*.map.csv`。GlobalId・材料の名前 → DB の ID、分けた境界なら境界の ID・相手の ID・区間の順番）、レポート（`*.report.txt`。既定の高さで押し出した要素の一覧、要確認が開いている要素の一覧）。
  - 受け渡しの要件（区分が「受け渡しの要件」の条件）があれば先に照らし、満たさなければ IFC を出さず、要確認を出して止める。人が端末で `allow-ifc` を打てば、`btruth ifc --generation <止めた ID>` で出せる。
  - **確かめ方**：IfcOpenShell 0.9.0 を、リポジトリの依存にせず、別の環境（`out/_ifcvenv`。Git に入れない）に入れ、step2・扉・材料・仮想の境界の四つの IFC を `ifcopenshell.validate`（スキーマと決まり）で確かめて、問題 0 件。`ifcopenshell.geom` で形のある要素の形が全部作れた。この確かめで、型の性質の組の付け方（IfcRelDefinesByProperties ではなく型の HasPropertySets）、既定の構成の `集める` の出し方、仮想の要素の GlobalId の重なりを直した。

## 受入の基準ごとの結果（依頼書 §3）

| 基準 | 結果 | テスト |
|---|---|---|
| 例7。生成物を取り込んでも観測にならない。書き戻しの前に sha256 を確かめ、違えば書かない | 通った | `test_outputs.py::test_a_generated_drawing_*`、`::test_writeback_*`、`::test_confirming_*` |
| 数量が v2 の規則で出る（開口を差し引く） | 通った。扉 1.6 ㎡ を両側の部屋で差し引く。0.4 ㎡ は差し引かない。天井高のない部屋は数えない | `test_outputs.py::test_quantity_*`、`::test_quantities_*` |
| step2 の IFC に IfcBuildingStorey 1・IfcSpace 2・IfcWall 5・部屋の側の IfcRelSpaceBoundary 8（外部の側は 4） | 通った。参照の `#n` が全部ある | `test_ifc.py::test_step2_ifc_*` |
| GlobalId が二回出しても同じ。全部の要素に ElementId。対応表で関係と材料から DB の ID | 通った | `test_ifc.py::test_globalids_*`、`::test_the_mapping_*`、`::test_materials_*` |
| 開口が IfcRelContainedInSpatialStructure に入っていない | 通った | `test_ifc.py::test_the_mapping_*` |
| 受け渡しの要件の IDS を満たさないとき IFC が出ず、要確認の一覧が出る | 通った。人の allow-ifc で出せる。性質を足すと止まらない | `test_ifc.py::test_unmet_*`、`::test_ids_is_read_*` |
| type_width で 800 → 900 の後、図面の開口 800 に修正案 | 通った | `test_stage6_fixes.py::test_a_judged_type_width_*` |
| 第5段で残った三つ | 通った | `test_stage6_fixes.py` |
| 設計書 3-9 の第6段の失敗 | 3-9 に「確かめる段」が第6段の行はない。生成物を観測として読まない（H-2）は例7 のテストで確かめた | — |
| 新しい確定のコマンドがフックで止まる | 手元の PC で止まった（下） | `test_guard_confirm.py`、`test_cli_stage6.py` |

## 手元の Windows の PC で確かめたこと（2026-11-08、このセッション）

- Claude Code の Bash から `btruth confirm-drawing …` と `btruth allow-ifc …` を打つと、どちらも `guard_confirm.py` で止まった。
- 人の試しの流れ（承認 → type_width → 図面の修正案の承認 → 書き戻し → 表 → IFC）は、一時フォルダの自動テストで通した（`test_cli_stage6.py`）。その流れで出た IFC そのものは IfcOpenShell で確かめていない（同じ形の扉の IFC は確かめた）。

## 人が試す DB（`out\try6`）と、打つ順

テスト用の解釈（固定の解釈）は入れていない。第5段と同じ架空の平面図（扉つき）・壁種表・仕上表・建具表・議事録と、Claude Code の読み（承認していない）。下の ID は、`items` の出力の名前と照らした。

| 名前（`items` の表示） | ID |
|---|---|
| `Claude Code` の解釈 | `c4c2d3b9` |
| 建具の型 AD-1（建具表、幅 800） | 要素 `3b95e43b` |
| 建具 AD-1（図面の扉） | 要素 `6e4ecf38` |
| 開口（図面、幅 800） | 要素 `c604014d` |

リポジトリのフォルダで PowerShell を開き（Claude Code の中ではない）、この順で打つ。確定のコマンドは、一覧を出してから「確定しますか？ (y/N)」と聞く（前に貼った行は答えに使わない）。

1. 解釈を承認する。

   ```
   .venv\Scripts\python -m btruth items out\try6
   .venv\Scripts\python -m btruth approve out\try6 --interpretation c4c2d3b9 --reason "図面と表と議事録を見比べた"
   .venv\Scripts\python -m btruth issues out\try6
   ```

2. 「決定が未反映」（AD-1 の幅。議事録 900、建具表 800）で、型の幅を 900 にする。`issues` の「打つ例」の行の `--issue` の値を使う。

   ```
   .venv\Scripts\python -m btruth choose out\try6 --issue <決定が未反映の要確認の ID> --option type_width --reason "議事録どおり"
   .venv\Scripts\python -m btruth issues out\try6
   ```

3. 選んだ後の照らしで、「言い分の食い違い（主と従）」（開口の幅。基準の建具表 900、平面図 800。型の値が人の判断で変わった）が出る。図面の修正案を承認する。

   ```
   .venv\Scripts\python -m btruth choose out\try6 --issue <その要確認の ID> --option fix_secondary --reason "図面の開口を 900 に"
   .venv\Scripts\python -m btruth values out\try6 --element c604014d
   ```

4. 書き戻した DXF を出す（元の図面は `samples\step5\plan.dxf`。上書きしない）。

   ```
   .venv\Scripts\python -m btruth writeback out\try6 --source 平面図 --original samples\step5\plan.dxf --out out\try6\out\plan_wb.dxf
   .venv\Scripts\python -m btruth writebacks out\try6
   ```

   - **Jw_cad で確かめる**：Jw_cad を開き、「ファイル」→「DXF 読込み」で `out\try6\out\plan_wb.dxf` を開く。間仕切（左から 2300 の線）の扉のブロックが、元の図面より大きく（900/800 倍）描かれていることを、元の `samples\step5\plan.dxf` と見比べる。ほかの線は変わっていない。
   - 確かめたら、確認済みと記録する。

     ```
     .venv\Scripts\python -m btruth confirm-drawing out\try6 --writeback <writebacks に出た書き戻しの ID> --reason "Jw_cad で開いて確かめた"
     ```

5. 面積表・数量表を出す。

   ```
   .venv\Scripts\python -m btruth tables out\try6
   ```

   - `out\try6\out\tables\` に `area.csv`・`area.html`・`finishes.*`・`quantities.*` ができる。面積は左 9.20 ㎡・右 14.80 ㎡。数量は、天井高 2700 の右の部屋（101 事務室）だけが出て、開口（900 × 2000 = 1.8 ㎡）を差し引く。左の部屋は天井高がないので「数えられなかったもの」に出る。

6. IFC を出す。

   ```
   .venv\Scripts\python -m btruth ifc out\try6
   ```

   - `out\try6\out\model.ifc`（IFC4）、`model.map.csv`（対応表）、`model.report.txt`（既定の高さ 2700 で押し出した要素、要確認が開いている要素）ができる。
   - **無料の IFC ビューアで確かめる**：たとえば BIMvision、BIMcollab ZOOM（無料の版）、Open IFC Viewer などで `model.ifc` を開く。壁 5 枚、部屋 2 つ、間仕切の開口と扉、通り芯 X1・X2・Y1・Y2 が見える。要素を選ぶと、性質の組 `BT_Common` に `ElementId`（DB の ID）があり、左の部屋には `HasOpenIssue`（名前がない空間）が付いている。

- 試し直すときは `out\try6` を消し、`init` → `import` 五つ（平面図・壁種表・仕上表・建具表は `--kind 設計図 --drawing-type <図面の種類> --discipline 建築`、議事録は `--kind 議事録 --document-date 2026-10-15`）→ `propose samples\ai_run\step5_claude.json` で作り直す。ID は変わる。

## 設計書と違う作り方をした所

- **Q32**：IDS の条件の区分は、IDS の `<purpose>`、なければ取り込みのときの図面の種類から取る。
- **Q33**：IfcRelDefinesByType は、IFC4 の決まり（型から見て一つまで）に合わせて型ごとにまとめる。DB のつながりの ID は対応表に並べる。
- 生成した表（CSV）の 1 行目に印を入れる、は入れなかった（M-1）。CSV の読み手が 1 行目を見出しとして読むので、印を入れると取り込みの形が崩れる。生成物は sha256 とファイルの記録（`generation`）で見分ける。

## 第6段で作っていないもの・限り

- 層の例外のある壁に、その壁専用の IfcMaterialLayerSet を付けて出す（3-8-4 (d)、決定 Q19）は、まだない（型の層の組み立てだけを出す）。
- 人の承認を IfcApproval で出すことは、まだない。
- 書き戻しは DXF だけ（JWW は第8段）。書き戻すのは、開口の幅（扉のブロックの尺度）と、壁芯線・境界の線分（線の端点）だけ。
- 書き戻した図面を人が描き足して取り込んだとき、`writeback_id` は結ばれない（中身が変わり sha256 が違うため）。描き足しは人の変更として読む。
- 照らしの区分のうち、IDS で照らすのは性質（property）と属性（attribute）の切り口だけ。分類・材料・PartOf の切り口は「判定できない」になる。
