# 入れた外部のライブラリ

入れるものは最小にする（依頼書 第2段 §3）。表に無いものは使っていない。

| ライブラリ | 版 | ライセンス | 何に使うか | なぜ |
|---|---|---|---|---|
| ezdxf | 1.4.5 | MIT | DXF の読み手（`btruth/readers/dxf_reader.py`） | DXF の文法（R12〜2018、バイナリ、コードページ、壊れたファイルの修復）を自分で書かないため。読み手は「ファイル → 手掛かりの行」を作るだけで、器には触れない（設計書 0-1）。Jw_cad の書き出し（表の名前が空）は `ezdxf.recover` で読み、修復したことを取り込みの記録に残す |
| （ezdxf が連れてくるもの）numpy、fonttools、pyparsing、typing_extensions | — | BSD-3 / MIT / MIT / PSF | ezdxf の中でだけ使う | 直接は呼ばない |
| pytest | 9.x | MIT | テスト（開発のときだけ） | 先に失敗するテストを書いてから作る（依頼書 §3） |

- 標準ライブラリで済ませたもの：SQLite（`sqlite3`）、CSV（`csv`）、JSON（`json`）、ハッシュ（`hashlib`）、UUID（`uuid`）、コマンド（`argparse`）。
- フック（`.claude/hooks/*.py`）は標準ライブラリだけで動く（venv なしで Windows でも動かすため）。
- 入れる手順：`python -m venv .venv` → `.venv\Scripts\python -m pip install -e .[dev]`（または `pip install ezdxf pytest`）。
