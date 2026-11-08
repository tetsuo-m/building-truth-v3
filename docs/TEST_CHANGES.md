# 既にあるテストを変えた記録

依頼書 第2段 §3：既にあるテストを変えるときは、理由をここに書く。新しく足したテストは書かない。

| 日付 | テスト | 何を変えたか | なぜ |
|---|---|---|---|
| 2026-11-08 | `tests/test_compare.py::test_step1_and_its_jwcad_export_match_within_tolerance`、`tests/test_cli.py` | 一致の期待値を 17 → 21、追加の候補を 4 → 0 に（コミット a120810 の前） | 設計書 3-5-1 の「Jw_cad で増えた CIRCLE 4」が事実と違った。`step1.dxf` にも通り芯の符号の丸が 4 つあり、両方の版で一致する。追加の候補の記録は、架空の図面に丸を足す別のテストで確かめる |
| 2026-11-08 | `tests/test_init_project.py::test_default_structure_has_one_first_storey`、`..._is_an_interpretation_of_the_rule_reader` | 既定の構成の要素を 4 → 5（物件を足す）、種類の一覧に「物件」、敷地の `集める` の相手を `project` の ID から物件の要素に | 設計書 改訂 6（人の決定 2）：物件も要素にし、`project` の表は物件の要素を指す |
| 2026-11-08 | `tests/test_init_project.py::test_default_csv_tables_are_copied_and_loaded` | `relation_kinds_loaded` の確かめに「含む の from_kinds に開口がない」、属性の確かめに「境界の種類」「建具の種類」、主の表の「建具, 建具の種類」を足した | 改訂 6（決定 1・4）：「種類」の名前を三つに分ける。開口は含むで階につながない |
| 2026-11-08 | `tests/test_init_project.py::test_rules_hold_the_tolerances_in_one_place` | `rules_loaded` の `use` の列を確かめる | 改訂 6（決定 14）：許容差をどこで使うか（図面の計測／書類の比較…）を行に書く |
| 2026-11-08 | `tests/test_cli.py::test_init_import_report_compare_through_the_command` | 二つ目の取り込みを `--next` で行い、`--next` で無い呼び名、`--new` で既にある呼び名が止まることを足した | 改訂 6（決定 6）：既存の出どころの次の版か、新しい出どころかを人が選べる |
| 2026-11-08（第3段） | `tests/test_cli.py::test_a_terminal_only_subcommand_does_not_exist_yet` → `test_the_confirmation_subcommands_exist_and_say_they_are_terminal_only` | 「approve / decide / reject が無い」の確かめを、「六つの確定のコマンドがあり、help に端末からだけ動くと書いてある」に替えた | 第3段で確定のコマンドを作った（依頼書 §3-3） |
| 2026-11-08（第3段） | `tests/test_guard_confirm.py` | v2 の形のコマンド例（`--db out/a.sqlite` など）を、v3 の形（物件のフォルダを渡す）に書き直した。許す例から DB のファイル名を含むものを外した。新しい確定のコマンド名、DB のファイル・sqlite3 を名指すコマンド、DB のファイルへの Edit・Write が止まることを足した | G-1 (a)：DB のファイル名を含むコマンドは今は止める対象。btruth は DB のファイル名を受け取らない（第2段の決定） |
| 2026-11-08（第3段） | `tests/conftest.py`、`tests/helpers.py` | 端末の差し替えのフィクスチャ（`terminal_ok`、`no_terminal`）と、提案を組むヘルパを足した。既存のヘルパは変えていない | 第3段のテストのため |
