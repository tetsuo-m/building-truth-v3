"""Access to the vessel: open, append rows, read rows.

There is deliberately no `update` or `delete` here (0-2, B-6). The single exception is
`set_project`, which rewrites the project's own settings row (A-1). Writing `review` /
`review_premise` is the confirmation command's job (stage 3, terminal only; G-1 (b)); nothing in
stage 2 writes those two tables.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from btruth import schema
from btruth.common import new_id, now_iso


class Store:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row

    # ------------------------------------------------------------------ open / close
    @classmethod
    def open(cls, db_path: Path, create: bool = False) -> "Store":
        db_path = Path(db_path)
        if not create and not db_path.exists():
            raise FileNotFoundError(f"正本の DB がありません: {db_path}")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        store = cls(conn)
        if create:
            schema.create_all(conn)
        return store

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------------ append
    def insert(self, table: str, recorded_by: str, **cols) -> str:
        """Append one row. Adds id / recorded_at unless given. Returns the id."""
        if table in ("review", "review_premise"):
            # G-1 (b): only the confirmation command (stage 3, terminal) writes these two tables.
            raise PermissionError("review / review_premise は承認のコマンドだけが書く（G-1）")
        row = dict(cols)
        row.setdefault("id", new_id())
        row.setdefault("recorded_at", now_iso())
        row["recorded_by"] = recorded_by
        names = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        self.conn.execute(f"insert into {table} ({names}) values ({marks})", tuple(row.values()))
        return row["id"]

    def commit(self) -> None:
        self.conn.commit()

    # ------------------------------------------------------------------ read
    def one(self, sql: str, *params) -> sqlite3.Row | None:
        return self.conn.execute(sql, params).fetchone()

    def all(self, sql: str, *params) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    def scalar(self, sql: str, *params):
        row = self.conn.execute(sql, params).fetchone()
        return None if row is None else row[0]

    def project_id(self) -> str:
        return self.scalar("select id from project")

    def clue_kind(self, clue_id: str) -> str | None:
        return self.scalar("select kind from clue where id = ?", clue_id)

    # ------------------------------------------------------------------ the one exception (A-1)
    def set_project(self, recorded_by: str, **cols) -> None:
        """The project's own settings (name, schema_version) may be rewritten (A-1, 0-2)."""
        allowed = {"name", "schema_version"}
        bad = set(cols) - allowed
        if bad:
            raise ValueError(f"project で直せるのは {sorted(allowed)} だけ: {sorted(bad)}")
        sets = ", ".join(f"{k} = ?" for k in cols)
        self.conn.execute(f"update project set {sets}, recorded_at = ?, recorded_by = ?",
                          (*cols.values(), now_iso(), recorded_by))
        self.conn.commit()
