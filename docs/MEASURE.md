# 答えを見せない測定の手順（人が行う）

AI の読みの正しさを測る手順（CONCEPT D-9、設計書 3-5-1 (2)、第4段の依頼書 §1-2）。測るのは人で、読ませるのは**新しいセッション**の Claude Code。

## なぜ別のセッションで測るか

第3段の測定は、同じセッションで固定の解釈（テスト用の答え）を書いた後に読ませたので、一致して当然だった。その数字は `run_summary` に「答えを知った状態の数字」の印を足して、本当の測定と分けた（`btruth measure --list` で見える）。

測定のときは、読む側が次のものを読めない状態にする。

- 固定の解釈（`tests/fixtures/`）
- 期待値の文書（`samples/*/expected*.md`）
- テストのコード（`tests/`）と、それまでの会話

渡すのは、手掛かり（図面と表）と、読ませる手順書（`.claude/skills/read-drawing/SKILL.md`）だけ。

## 手順

ここで `<測定の物件>` は、測定のためだけに作る物件のフォルダ（人が試す DB とも、テストの DB とも別）。`<測定の場所>` は、**リポジトリの外**の空のフォルダ（例 `C:\dev\btruth-measure\step2`）。

1. 測定の物件を作り、読ませる図面と表を取り込む（リポジトリのフォルダの PowerShell で）。

   ```
   .venv\Scripts\python -m btruth init <測定の物件> --name 測定
   .venv\Scripts\python -m btruth import <測定の物件> samples\step2\step2.dxf --source 平面図 --kind 設計図 --drawing-type 建築平面図
   .venv\Scripts\python -m btruth import <測定の物件> samples\step1\wall_types.csv --source 壁種表 --kind 設計図 --drawing-type 壁種表
   .venv\Scripts\python -m btruth import <測定の物件> samples\step1\finish_schedule.csv --source 仕上表 --kind 設計図 --drawing-type 仕上表
   ```

2. 測定の場所を作る。手掛かりの JSON・手順書・守り（フック）・作業の説明（`TASK.md`）だけが入る。固定の解釈・期待値・DB・btruth のコードは入らない。

   ```
   .venv\Scripts\python -m btruth kit <測定の物件> --versions 平面図@1 壁種表@1 仕上表@1 --dest <測定の場所>
   ```

3. **新しい Claude Code を、測定の場所で起動する**（`cd <測定の場所>` してから `claude`）。前の会話を引き継がない。最初に次の一文だけを渡す。

   > TASK.md に従って作業してください。

   - フックは測定の場所の `.claude/` から読み込まれる。`guard_paths.py` が、そのフォルダの外（リポジトリ）を読むことを止める。
   - Claude Code が手順書の 0 節で守りを確かめ、`clues/` を読み、`proposal.json` を書いて止まる。
   - 外のファイルを読もうとして止められた、などがあれば、その測定は記録に書き添える。

4. 書かれた提案と、固定の解釈を、**人が**測定の物件に登録して照らす（リポジトリのフォルダの PowerShell で）。

   ```
   .venv\Scripts\python -m btruth propose <測定の物件> <測定の場所>\proposal.json --instructions .claude\skills\read-drawing\SKILL.md
   .venv\Scripts\python -m btruth propose <測定の物件> tests\fixtures\step2_fixed.json
   .venv\Scripts\python -m btruth items <測定の物件>
   .venv\Scripts\python -m btruth measure <測定の物件> --interpretation <「Claude Code」の解釈の ID> --against <「固定の解釈（テスト）」の解釈の ID>
   ```

   - 二つの解釈の ID は、`items` の出力の、解釈の名前（`Claude Code`、`固定の解釈（テスト）`）の行から写す。
   - `measure` は、条件「答えを見せない（docs/MEASURE.md）」を数字と一緒に `run_summary` に残す。違う条件で読ませたときは `--condition` で書く。
   - 合格・不合格の線は引かない。数字を見る（D-9）。

5. 測定の物件は、承認の試しには使わない（固定の解釈が入っているため。F-14）。

## 前の測定に印を付ける

```
.venv\Scripts\python -m btruth measure <物件> --list
.venv\Scripts\python -m btruth measure <物件> --mark <測定の run_summary の ID の先頭> --note "なぜ測定にならないか"
```

印は新しい行として積む（B-6。前の行は書き換えない）。
