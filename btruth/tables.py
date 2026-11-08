"""The CSV tables people read and write (design J, C-9) and their copies in the vessel (A-5).

The CSV is the master copy; the vessel keeps a copy of each version it saw, so a check can say which
table it used (B-10). Two scopes: the office's shared folder is read first, the project's folder
overrides the same key (decision Q9). Nothing is merged on disk; `effective_rows` merges when reading.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from btruth.common import now_iso, sha256_of
from btruth.project import ProjectFolder
from btruth.store import Store


@dataclass(frozen=True)
class TableKind:
    kind: str
    rel_path: str
    table: str
    columns: tuple[str, ...]
    key_columns: tuple[str, ...]


TABLE_KINDS: dict[str, TableKind] = {t.kind: t for t in [
    TableKind("rules", "rules/rules.csv", "rules_loaded",
              ("key", "value", "unit", "origin", "since", "note"), ("key",)),
    TableKind("authority", "rules/authority.csv", "authority_loaded",
              ("element_kind", "attribute", "primary_source_kind", "secondary_source_kinds", "core", "note"),
              ("element_kind", "attribute")),
    TableKind("document_rank", "rules/document_rank.csv", "document_rank_loaded",
              ("source_kind", "rank", "compare_only", "note"), ("source_kind",)),
    TableKind("layer_roles", "settings/layer_roles.csv", "layer_roles_loaded",
              ("scope", "layer_pattern", "entity_kind", "roles", "note"), ("layer_pattern", "entity_kind")),
    TableKind("knowledge", "knowledge/readings.csv", "knowledge_loaded",
              ("scope", "kind", "pattern_json", "meaning_json", "origin_review_id", "source_version_id",
               "written_at", "note"), ("kind", "pattern_json")),
    TableKind("relation_kinds", "rules/relation_kinds.csv", "relation_kinds_loaded",
              ("kind", "from_kinds", "to_kinds", "ifc_relation", "max_per_from", "note"), ("kind",)),
    TableKind("attributes", "rules/attributes.csv", "attributes_loaded",
              ("attribute", "applies_to", "ifc_pset", "ifc_property", "ifc_attribute", "value_type", "note"),
              ("attribute", "applies_to")),
    TableKind("element_kinds", "rules/element_kinds.csv", "element_kinds_loaded",
              ("kind", "ifc_class", "ifc_predefined_type", "is_type", "note"), ("kind",)),
    TableKind("conditions", "rules/conditions.csv", "conditions_loaded",
              ("key", "category", "subject_kind", "rule", "severity", "source_ref", "note"), ("key",)),
]}

SCOPE_OFFICE = "事務所"
SCOPE_PROJECT = "物件"


def read_csv(path: Path, encoding: str = "utf-8-sig") -> list[dict]:
    with open(path, encoding=encoding, newline="") as f:
        return [dict(r) for r in csv.DictReader(f)]


def _scopes(project: ProjectFolder) -> list[tuple[str, Path]]:
    scopes = []
    if project.office_dir is not None:
        scopes.append((SCOPE_OFFICE, project.office_dir))
    scopes.append((SCOPE_PROJECT, project.folder))
    return scopes


def load_tables(store: Store, project: ProjectFolder, recorded_by: str = "取り込みのコマンド") -> list[str]:
    """Copy every CSV whose content changed into the vessel. Returns the new table_load ids."""
    loaded = []
    encoding = project.settings.get("csv_encoding") or "utf-8-sig"
    for scope, base in _scopes(project):
        for tk in TABLE_KINDS.values():
            path = base / tk.rel_path
            if not path.exists():
                continue
            sha = sha256_of(path)
            if store.one("select id from table_load where kind=? and scope=? and sha256=?", tk.kind, scope, sha):
                continue
            rows = read_csv(path, encoding)
            load_id = store.insert("table_load", recorded_by, kind=tk.kind, scope=scope, path=str(path),
                                   sha256=sha, row_count=len(rows), loaded_at=now_iso())
            for row in rows:
                if not any((row.get(c) or "").strip() for c in tk.columns):
                    continue
                store.insert(tk.table, recorded_by, table_load_id=load_id,
                             **{c: (row.get(c) if row.get(c) is not None else "") for c in tk.columns})
            loaded.append(load_id)
    store.commit()
    return loaded


def latest_load_id(store: Store, kind: str, scope: str) -> str | None:
    row = store.one("select id from table_load where kind=? and scope=? order by rowid desc limit 1", kind, scope)
    return row["id"] if row else None


def rows_of_load(store: Store, kind: str, load_id: str) -> list[dict]:
    tk = TABLE_KINDS[kind]
    cols = ", ".join(tk.columns)
    return [dict(r) for r in store.all(f"select {cols} from {tk.table} where table_load_id=? order by rowid", load_id)]


def effective_rows(store: Store, project: ProjectFolder, kind: str) -> list[dict]:
    """Office rows first, then project rows; a project row with the same key replaces the office row."""
    tk = TABLE_KINDS[kind]
    merged: dict[tuple, dict] = {}
    order: list[tuple] = []
    for scope, _ in _scopes(project):
        load_id = latest_load_id(store, kind, scope)
        if load_id is None:
            continue
        for row in rows_of_load(store, kind, load_id):
            key = tuple((row.get(c) or "").strip() for c in tk.key_columns)
            if key not in merged:
                order.append(key)
            row["_scope"] = scope
            merged[key] = row
    return [merged[k] for k in order]


def effective_rules(store: Store, project: ProjectFolder) -> dict[str, str]:
    return {r["key"].strip(): (r["value"] or "").strip() for r in effective_rows(store, project, "rules")}
