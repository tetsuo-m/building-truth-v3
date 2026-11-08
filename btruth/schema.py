"""The vessel: one table per unit of storage of design 3-2 (A..N).

Rules shared by every table (design 0-2):
  * `id` is a UUID string, every row has `recorded_at` and `recorded_by`;
  * rows are appended only (B-6). No code here or elsewhere updates or deletes rows, except the
    project's own settings (A-1). `review` / `review_premise` additionally carry triggers that abort
    UPDATE and DELETE (G-1 (d): a guard against slips, not a security measure);
  * kinds (of sources, clues, elements, relations, ...) are plain text, never CHECK constraints or
    enumerations (C-1, E-1; failure F-7). The lists people read live in CSV (J-5).
The version of the vessel is recorded in `project.schema_version` and `schema_migration`, so later
stages can add tables without rebuilding the database.
"""
from __future__ import annotations

import sqlite3

from btruth.common import now_iso

SCHEMA_VERSION = 2

COMMON = "id TEXT PRIMARY KEY, recorded_at TEXT NOT NULL, recorded_by TEXT NOT NULL"

# name -> columns besides the common three. Comments give the design section.
TABLES: dict[str, str] = {
    # A. project, sources, versions, intake
    "project": "name TEXT, created_at TEXT, schema_version INTEGER, element_id TEXT",         # A-1 (element_id: 改訂 6)
    "source": "project_id TEXT, name TEXT, kind TEXT, note TEXT",                              # A-2 (kind = 書類の区分)
    "source_attribute": "source_id TEXT, attribute TEXT, value TEXT, origin TEXT",            # A-2
    "source_version": ("source_id TEXT, seq INTEGER, file_name TEXT, sha256 TEXT, format TEXT, reader_name TEXT, "
                       "reader_version TEXT, unit_factor REAL, document_date TEXT, archive_path TEXT, imported_at TEXT, "
                       "imported_by TEXT, writeback_id TEXT, note TEXT"),                     # A-3
    "intake_log": "source_version_id TEXT, kind TEXT, detail_json TEXT",                      # A-4
    "table_load": "kind TEXT, scope TEXT, path TEXT, sha256 TEXT, row_count INTEGER, loaded_at TEXT",   # A-5
    "rules_loaded": "table_load_id TEXT, key TEXT, value TEXT, unit TEXT, origin TEXT, since TEXT, use TEXT, note TEXT",  # J-1 (use: 改訂 6)
    "authority_loaded": ("table_load_id TEXT, element_kind TEXT, attribute TEXT, primary_source_kind TEXT, "
                         "secondary_source_kinds TEXT, core TEXT, note TEXT"),                # J-2
    "document_rank_loaded": "table_load_id TEXT, source_kind TEXT, rank TEXT, compare_only TEXT, note TEXT",  # J-3
    "layer_roles_loaded": "table_load_id TEXT, scope TEXT, layer_pattern TEXT, entity_kind TEXT, roles TEXT, note TEXT",  # J-4
    "knowledge_loaded": ("table_load_id TEXT, scope TEXT, kind TEXT, pattern_json TEXT, meaning_json TEXT, "
                         "origin_review_id TEXT, source_version_id TEXT, written_at TEXT, note TEXT"),   # J-6
    "relation_kinds_loaded": ("table_load_id TEXT, kind TEXT, from_kinds TEXT, to_kinds TEXT, ifc_relation TEXT, "
                              "max_per_from TEXT, note TEXT"),                                # J-5
    "attributes_loaded": ("table_load_id TEXT, attribute TEXT, applies_to TEXT, ifc_pset TEXT, ifc_property TEXT, "
                          "ifc_attribute TEXT, value_type TEXT, note TEXT"),                  # J-5
    "element_kinds_loaded": "table_load_id TEXT, kind TEXT, ifc_class TEXT, ifc_predefined_type TEXT, is_type TEXT, note TEXT",  # J-5
    "conditions_loaded": ("table_load_id TEXT, key TEXT, category TEXT, subject_kind TEXT, rule TEXT, severity TEXT, "
                          "source_ref TEXT, note TEXT"),                                      # J-7
    # B. clues
    "clue": ("source_version_id TEXT, seq INTEGER, kind TEXT, layer_raw TEXT, geometry_json TEXT, text_raw TEXT, "
             "style_json TEXT, format_extra_json TEXT, parent_clue_id TEXT, generated_from TEXT"),   # B-1
    "reader": "name TEXT, version TEXT, formats TEXT, note TEXT",                              # B-2
    # C. elements and relations
    "element": "project_id TEXT, created_by_interpretation_id TEXT",                          # C-1 (nothing else: E-6)
    "relation": "kind TEXT, from_element_id TEXT, to_element_id TEXT, role_json TEXT, created_by_interpretation_id TEXT",  # C-2
    "relation_end": "relation_id TEXT, reason TEXT",                                           # C-2
    # D. claims
    "claim": ("subject_kind TEXT, subject_id TEXT, attribute TEXT, value_json TEXT, unit TEXT, mode TEXT, "
              "statement_kind TEXT, source_version_id TEXT, interpretation_id TEXT, review_id TEXT, agent_id TEXT, "
              "confidence REAL"),                                                              # D-1 (statement_kind: 決定／未決／記述, 改訂 6)
    "claim_evidence": "claim_id TEXT, clue_id TEXT, role TEXT, reason TEXT",                   # D-1
    # E. interpretations
    "agent": "name TEXT, kind TEXT, model TEXT, version TEXT, instructions_sha256 TEXT",       # E-1
    "interpretation": "source_version_ids_json TEXT, agent_id TEXT, scope_json TEXT, premise_json TEXT, summary TEXT",  # E-2
    "interpretation_item": ("interpretation_id TEXT, kind TEXT, element_id TEXT, relation_id TEXT, claim_id TEXT, "
                            "assumption_id TEXT, reason TEXT, confidence REAL, rule_check_status TEXT, "
                            "rule_check_reason TEXT"),                                        # E-2
    "interpretation_evidence": "item_id TEXT, clue_id TEXT, element_ref_id TEXT, role TEXT, reason TEXT",  # E-2, K
    "rule_check": "interpretation_item_id TEXT, rule TEXT, result TEXT, detail_json TEXT",      # E-3
    # F. assumptions
    "assumption": ("level INTEGER, scope_json TEXT, kind TEXT, value_json TEXT, confidence REAL, "
                   "created_by_interpretation_id TEXT, review_id TEXT"),                       # F-1
    "assumption_evidence": "assumption_id TEXT, clue_id TEXT, role TEXT, reason TEXT",         # F-1
    # G. reviews (written by the person only; stage 3 builds the command)
    "review": ("target_kind TEXT, target_id TEXT, action TEXT, choice_json TEXT, reason TEXT, "
               "basis_source_version_id TEXT, reviewed_by TEXT, signature TEXT, signer_key_id TEXT"),   # G-1
    "review_premise": "review_id TEXT, kind TEXT, ref_id TEXT",                                # G-1
    "recheck_mark": "review_id TEXT, caused_by_kind TEXT, caused_by_id TEXT, reason TEXT, detail_json TEXT",  # G-2
    # H. identity
    "identity_run": ("kind TEXT, base_source_version_id TEXT, new_source_version_id TEXT, frame_json TEXT, "
                     "rules_table_load_id TEXT, mesh_json TEXT, interpretation_id TEXT, counts_json TEXT"),  # H-1
    "identity_link": ("run_id TEXT, element_id TEXT, new_element_id TEXT, candidates_json TEXT, verdict TEXT, "
                      "reason TEXT, basis_json TEXT, facts_json TEXT, decided_by TEXT"),       # H-2
    "impact": "run_id TEXT, element_id TEXT, relation_id TEXT, reason TEXT, action TEXT, depth INTEGER",   # H-3
    # I. consistency checks and issues
    "check_run": ("trigger TEXT, scope_json TEXT, authority_table_load_id TEXT, rank_table_load_id TEXT, "
                  "rules_table_load_id TEXT, counts_json TEXT"),                               # I-1
    "issue": ("check_run_id TEXT, identity_run_id TEXT, condition_check_id TEXT, kind TEXT, severity TEXT, "
              "subject_ids_json TEXT, basis_json TEXT, facts_json TEXT, proposal_json TEXT"),  # I-2
    "issue_option": "issue_id TEXT, code TEXT, label TEXT, effect_json TEXT",                  # I-2
    # L. conditions
    "condition": ("form TEXT, source_version_id TEXT, clue_id TEXT, category TEXT, text_ref TEXT, ids_json TEXT, "
                  "rule_json TEXT, severity TEXT, scope_json TEXT"),                           # L-1
    "condition_check": ("condition_id TEXT, check_run_id TEXT, generation_id TEXT, subject_ids_json TEXT, "
                        "result TEXT, facts_json TEXT, agent_id TEXT"),                        # L-2
    # M. outputs
    "generation": "kind TEXT, as_of_json TEXT, path TEXT, sha256 TEXT, marker_json TEXT",       # M-1
    "writeback": ("generation_id TEXT, base_source_version_id TEXT, base_sha256_verified INTEGER, "
                  "review_ids_json TEXT, new_path TEXT, sha256 TEXT, status TEXT"),            # M-2
    # N. other
    "external_send": "destination TEXT, content_summary TEXT, sha256 TEXT, approved_by_review_id TEXT",  # N-1
    "run_summary": "kind TEXT, counts_json TEXT",                                              # N-2
}

INDEXES = [
    "create index if not exists ix_clue_version on clue(source_version_id)",
    "create index if not exists ix_clue_parent on clue(parent_clue_id)",
    "create index if not exists ix_claim_subject on claim(subject_kind, subject_id, attribute)",
    "create index if not exists ix_source_version_sha on source_version(sha256)",
    "create index if not exists ix_source_version_source on source_version(source_id, seq)",
    "create index if not exists ix_intake_log_version on intake_log(source_version_id)",
    "create index if not exists ix_table_load_kind on table_load(kind, scope)",
    "create index if not exists ix_ievidence_clue on interpretation_evidence(clue_id)",
    "create index if not exists ix_cevidence_clue on claim_evidence(clue_id)",
    "create index if not exists ix_aevidence_clue on assumption_evidence(clue_id)",
]

# G-1 (d): review rows are never rewritten; corrections are new rows (B-6).
TRIGGERS = [
    ("review_no_update", "before update on review", "review は書き換えない。訂正は新しい行で積む（B-6、G-1）"),
    ("review_no_delete", "before delete on review", "review は消さない。取り消しも新しい行で積む（B-6、G-1）"),
    ("review_premise_no_update", "before update on review_premise", "review_premise は書き換えない（B-6、G-1）"),
    ("review_premise_no_delete", "before delete on review_premise", "review_premise は消さない（B-6、G-1）"),
]


# Changes to a vessel that already exists, by the version that introduces them. A fresh vessel gets the
# full TABLES above and records every version as applied; an older vessel runs only what it lacks.
MIGRATIONS: dict[int, list[str]] = {
    2: [
        "alter table project add column element_id TEXT",            # 改訂 6 (2): the project is an element
        "alter table claim add column statement_kind TEXT",          # 改訂 6 (3): 決定／未決／記述
        "alter table rules_loaded add column use TEXT",              # 改訂 6 (14): where a rule value is used
    ],
}


def table_names() -> list[str]:
    return list(TABLES)


def _applied_versions(conn: sqlite3.Connection) -> list[int]:
    conn.execute("create table if not exists schema_migration (version INTEGER PRIMARY KEY, applied_at TEXT, applied_by TEXT)")
    return [r[0] for r in conn.execute("select version from schema_migration order by version")]


def _record(conn: sqlite3.Connection, version: int, applied_by: str) -> None:
    conn.execute("insert or ignore into schema_migration(version, applied_at, applied_by) values (?, ?, ?)",
                 (version, now_iso(), applied_by))


def create_all(conn: sqlite3.Connection, applied_by: str = "器を作るコマンド") -> None:
    """Create every table, index and trigger of a fresh vessel and record the vessel's version."""
    cur = conn.cursor()
    for name, cols in TABLES.items():
        cur.execute(f"create table if not exists {name} ({COMMON}, {cols})")
    for sql in INDEXES:
        cur.execute(sql)
    for name, event, message in TRIGGERS:
        cur.execute(f"create trigger if not exists {name} {event} begin select raise(abort, '{message}'); end")
    _applied_versions(conn)                            # creates schema_migration
    for version in range(1, SCHEMA_VERSION + 1):      # a fresh vessel already has every change
        _record(conn, version, applied_by)
    conn.commit()


def migrate(conn: sqlite3.Connection, applied_by: str = "器の更新") -> list[int]:
    """Bring an existing vessel up to SCHEMA_VERSION without rebuilding it. Returns the versions applied."""
    applied = _applied_versions(conn)
    current = max(applied) if applied else 0
    done = []
    for version in range(current + 1, SCHEMA_VERSION + 1):
        for sql in MIGRATIONS.get(version, []):
            conn.execute(sql)
        for name, cols in TABLES.items():                 # tables added later are created whole
            conn.execute(f"create table if not exists {name} ({COMMON}, {cols})")
        _record(conn, version, applied_by)
        done.append(version)
    if done:
        conn.execute("update project set schema_version = ?, recorded_at = ?, recorded_by = ?",
                     (SCHEMA_VERSION, now_iso(), applied_by))
        conn.commit()
    return done
