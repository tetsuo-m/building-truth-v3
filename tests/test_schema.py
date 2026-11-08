"""The vessel (design 3-2 A..N, 0-2): every unit of storage exists, rows are only appended,
every table carries id / recorded_at / recorded_by, and the version of the vessel is recorded.
"""
from __future__ import annotations

import sqlite3

import pytest

from helpers import make_project

# Design 3-2: one table per unit of storage (plus the per-kind copies of the CSV tables, A-5).
DESIGN_TABLES = {
    "project", "source", "source_attribute", "source_version", "intake_log", "table_load",
    "rules_loaded", "authority_loaded", "document_rank_loaded", "layer_roles_loaded",
    "knowledge_loaded", "relation_kinds_loaded", "attributes_loaded", "element_kinds_loaded",
    "conditions_loaded",
    "clue", "reader",
    "element", "relation", "relation_end",
    "claim", "claim_evidence",
    "agent", "interpretation", "interpretation_item", "interpretation_evidence", "rule_check",
    "assumption", "assumption_evidence",
    "review", "review_premise", "recheck_mark",
    "identity_run", "identity_link", "impact",
    "check_run", "issue", "issue_option",
    "condition", "condition_check",
    "generation", "writeback",
    "external_send", "run_summary",
}


def table_names(store):
    return {r[0] for r in store.conn.execute(
        "select name from sqlite_master where type='table' and name not like 'sqlite_%'")}


def test_all_units_of_storage_exist(tmp_path):
    _, store = make_project(tmp_path)
    assert DESIGN_TABLES <= table_names(store)


def test_every_table_has_id_recorded_at_recorded_by(tmp_path):
    _, store = make_project(tmp_path)
    for name in table_names(store):
        if name == "schema_migration":
            continue
        cols = {r[1] for r in store.conn.execute(f"pragma table_info({name})")}
        assert {"id", "recorded_at", "recorded_by"} <= cols, name


def test_schema_version_is_recorded(tmp_path):
    from btruth.schema import SCHEMA_VERSION

    _, store = make_project(tmp_path)
    row = store.conn.execute("select schema_version from project").fetchone()
    assert row[0] == SCHEMA_VERSION
    applied = [r[0] for r in store.conn.execute("select version from schema_migration order by version")]
    assert applied[-1] == SCHEMA_VERSION


def test_review_rows_cannot_be_updated_or_deleted(tmp_path):
    """G-1 (d): triggers stop UPDATE and DELETE on review / review_premise. This test writes a row
    directly to a *temporary test database* only to exercise the trigger; no code path writes review."""
    _, store = make_project(tmp_path)
    conn = store.conn
    conn.execute("insert into review(id, target_kind, target_id, action, reviewed_by, recorded_at, recorded_by)"
                 " values ('r1', 'issue', 'x', '承認', 'テスト', '2026-01-01T00:00:00+09:00', 'テスト')")
    conn.execute("insert into review_premise(id, review_id, kind, ref_id, recorded_at, recorded_by)"
                 " values ('p1', 'r1', 'clue', 'c1', '2026-01-01T00:00:00+09:00', 'テスト')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("update review set action='却下' where id='r1'")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("delete from review where id='r1'")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("update review_premise set ref_id='c2' where id='p1'")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("delete from review_premise where id='p1'")


def test_columns_added_by_the_second_review_exist(tmp_path):
    """改訂 6: project points at the project element (2), claim has statement_kind (3), rules have `use` (14)."""
    _, store = make_project(tmp_path)
    cols = lambda t: {r[1] for r in store.conn.execute(f"pragma table_info({t})")}
    assert "element_id" in cols("project")
    assert "statement_kind" in cols("claim")
    assert "use" in cols("rules_loaded")


def test_an_older_vessel_is_migrated_without_rebuilding(tmp_path):
    """The vessel's version lets later stages add columns and tables without recreating the database."""
    from btruth.schema import SCHEMA_VERSION, migrate

    _, store = make_project(tmp_path)
    conn = store.conn
    # make the database look like version 1 (the shape committed in a120810)
    conn.execute("alter table project drop column element_id")
    conn.execute("alter table claim drop column statement_kind")
    conn.execute("alter table rules_loaded drop column use")
    conn.execute("delete from schema_migration where version > 1")
    conn.execute("update project set schema_version = 1")
    conn.commit()
    applied = migrate(conn, applied_by="テスト")
    assert applied == list(range(2, SCHEMA_VERSION + 1))
    assert "element_id" in {r[1] for r in conn.execute("pragma table_info(project)")}
    assert conn.execute("select schema_version from project").fetchone()[0] == SCHEMA_VERSION
    assert migrate(conn, applied_by="テスト") == []          # idempotent


def test_review_signature_columns_exist_and_stay_empty(tmp_path):
    _, store = make_project(tmp_path)
    cols = {r[1] for r in store.conn.execute("pragma table_info(review)")}
    assert {"signature", "signer_key_id"} <= cols
    assert store.conn.execute("select count(*) from review").fetchone()[0] == 0


def test_store_has_no_update_or_delete_helpers():
    """0-2: rows are appended only. The only exception is the project's own settings (A-1)."""
    from btruth.store import Store

    names = {n for n in dir(Store) if n.startswith(("update", "delete", "remove", "set_"))}
    assert names <= {"set_project"}, names


def test_no_kind_is_fixed_by_a_check_constraint(tmp_path):
    """C-1 / E-1 / F-7: kinds live in CSV rows, never in enumerations baked into the schema."""
    _, store = make_project(tmp_path)
    import re
    ddl = " ".join(r[0] or "" for r in store.conn.execute("select sql from sqlite_master where type='table'"))
    assert not re.search(r"\bCHECK\s*\(", ddl, re.I)          # (the table check_run is not a constraint)
