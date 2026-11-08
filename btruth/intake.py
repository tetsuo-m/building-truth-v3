"""Intake: one file -> source, attributes, version, clues, archive copy, intake log (design A-2..A-5, B-1).

What it does and why:
  * the CSV tables are copied first, so the vessel can say which tables were in force (A-5, B-10);
  * a file whose sha256 is already in the vessel is not taken in again; the attempt is logged (A-3);
  * the source's kind is the document class (A-2: 法律／議事録／…／設計図／…). It is what the person
    typed, or empty, to be proposed later by the AI as a source attribute;
  * every clue is stored as the reader gave it; clues the vessel itself produced are kept but marked
    `generated_from` so no interpretation reads them as observation (H-2, M-1);
  * nothing here interprets (B-2 is stage 3); nothing here writes review (G-1).
"""
from __future__ import annotations

import shutil
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from btruth.common import dumps, new_id, now_iso, sha256_of
from btruth.project import ProjectFolder
from btruth.readers import reader_for
from btruth.store import Store
from btruth.tables import effective_rules, load_tables

ORIGIN_COMMAND = "コマンドで指定"      # v2 Q57: a value the person gave on the command line


class UnsupportedFormat(Exception):
    pass


class SourceExists(Exception):
    """`mode="new"` but a source with that name already exists (A-2, 改訂 6 (6))."""


class SourceNotFound(Exception):
    """`mode="next"` but no source with that name exists."""


@dataclass
class ImportResult:
    source_id: str | None
    source_version_id: str | None
    skipped: bool = False
    existing_version_id: str | None = None
    counts: dict = field(default_factory=dict)
    generated_count: int = 0
    notes: list = field(default_factory=list)
    file_name: str = ""
    seq: int | None = None
    source_created: bool | None = None      # True: new source, False: next version of an existing one


def import_file(store: Store, project: ProjectFolder, path: Path, source_name: str | None = None,
                kind: str | None = None, drawing_type: str | None = None, discipline: str | None = None,
                document_date: str | None = None, mode: str = "auto",
                recorded_by: str = "取り込みのコマンド") -> ImportResult:
    """mode (改訂 6 (6)): "next" = the next version of an existing source (the file name may differ),
    "new" = a new source (stops if the name exists), "auto" = next if the name exists, else new."""
    if mode not in ("auto", "new", "next"):
        raise ValueError(f"mode は auto / new / next のどれか: {mode}")
    path = Path(path)
    reader = reader_for(path)
    if reader is None:
        raise UnsupportedFormat(f"この形式の読み手がありません: {path.suffix}")
    load_tables(store, project, recorded_by=recorded_by)
    rules = effective_rules(store, project)
    project_id = store.project_id()
    sha = sha256_of(path)

    # A-2 / 改訂 6 (6): what the person asked for (next version / new source) is checked before anything else
    source_name = source_name or path.stem
    row = store.one("select id from source where project_id=? and name=?", project_id, source_name)
    if mode == "next" and not row:
        raise SourceNotFound(f"出どころ「{source_name}」がありません（--next は既存の出どころの次の版として取り込む）")
    if mode == "new" and row:
        raise SourceExists(f"出どころ「{source_name}」はすでにあります（--new は新しい出どころとして取り込む。別の呼び名を）")

    # A-3: the same content is never taken in twice (ids must not change on re-import)
    existing = store.one("select id, source_id from source_version where sha256=?", sha)
    if existing:
        store.insert("intake_log", recorded_by, source_version_id=existing["id"], kind="同じ中身の取り込み",
                     detail_json=dumps({"file_name": path.name, "path": str(path), "sha256": sha,
                                        "note": "すでに同じ中身の版があるので取り込まない（A-3）"}))
        store.commit()
        return ImportResult(source_id=existing["source_id"], source_version_id=None, skipped=True,
                            existing_version_id=existing["id"], file_name=path.name)

    # A-2: the source (出どころ) is found by name within the project, or created
    if row:
        source_id, source_created = row["id"], False
    else:
        source_id = store.insert("source", recorded_by, project_id=project_id, name=source_name, kind=kind, note=None)
        source_created = True
    for attribute, value in (("図面の種類", drawing_type), ("分野", discipline)):
        if value:
            store.insert("source_attribute", recorded_by, source_id=source_id, attribute=attribute, value=value,
                         origin=ORIGIN_COMMAND)
    if kind and row and store.scalar("select kind from source where id=?", source_id) != kind:
        # the person gave a different class for an existing source: keep it as an attribute row (A-2: corrections are rows)
        store.insert("source_attribute", recorded_by, source_id=source_id, attribute="書類の区分", value=kind,
                     origin=ORIGIN_COMMAND)

    result = reader.read(path, project.settings)

    # A-3: the version, with a copy of the file (B-8)
    seq = (store.scalar("select max(seq) from source_version where source_id=?", source_id) or 0) + 1
    archive_rel = Path(project.settings.get("archive_dir") or "archive") / f"{sha[:16]}_{path.name}"
    archive_abs = project.folder / archive_rel
    archive_abs.parent.mkdir(parents=True, exist_ok=True)
    if not archive_abs.exists():
        shutil.copyfile(path, archive_abs)
    writeback_of_file = store.one("select id from writeback where sha256=?", sha)       # H-3: linked, still observed
    version_id = store.insert("source_version", recorded_by, source_id=source_id, seq=seq, file_name=path.name,
                              sha256=sha, format=result.format, reader_name=result.reader_name,
                              reader_version=result.reader_version, unit_factor=result.unit_factor,
                              document_date=document_date, archive_path=archive_rel.as_posix(),
                              imported_at=now_iso(), imported_by=recorded_by,
                              writeback_id=writeback_of_file["id"] if writeback_of_file else None, note=None)

    # M-1 / H-2: generated output is recognised by the file's sha256 or by the layer marker
    # a written-back drawing (H-3) is the person's drawing, not a generated output: linked, and observed
    generation_of_file = store.one("select id from generation where sha256=? and kind<>'書き戻し'", sha)
    prefix = rules.get("generated_layer_prefix") or "BT_GEN_"
    prefix_generations = [g["id"] for g in store.all("select id, marker_json from generation")
                          if prefix in (g["marker_json"] or "")]

    def generated_from(layer: str | None) -> str | None:
        if generation_of_file:
            return generation_of_file["id"]
        if layer and layer.startswith(prefix):
            return prefix_generations[-1] if prefix_generations else f"marker:{prefix}"
        return None

    # B-1: every clue, as read
    ids = [new_id() for _ in result.clues]
    counts: Counter = Counter()
    generated = Counter()
    for seq_no, (cid, rec) in enumerate(zip(ids, result.clues), start=1):
        gen = generated_from(rec.layer_raw)
        store.insert("clue", recorded_by, id=cid, source_version_id=version_id, seq=seq_no, kind=rec.kind,
                     layer_raw=rec.layer_raw, geometry_json=dumps(rec.geometry) if rec.geometry is not None else None,
                     text_raw=rec.text_raw, style_json=dumps(rec.style) if rec.style else None,
                     format_extra_json=dumps(rec.format_extra) if rec.format_extra else None,
                     parent_clue_id=ids[rec.parent_index] if rec.parent_index is not None else None,
                     generated_from=gen)
        if rec.parent_index is None and rec.kind != "BLOCK_DEF":
            if gen:
                generated[(rec.layer_raw or "", rec.kind)] += 1
            else:
                counts[(rec.layer_raw or "", rec.kind)] += 1

    # L-1: an IDS file — one condition row per specification (the rule reader's reading; conditions are not claims)
    if result.format == "ids":
        categories = ("法律", "系統の規則", "設計の規則", "受け渡しの要件")
        dt = store.scalar("select value from source_attribute where source_id=? and attribute='図面の種類' order by rowid desc limit 1",
                          source_id)
        for cid, rec in zip(ids, result.clues):
            if rec.kind != "SPECIFICATION":
                continue
            purpose = (rec.format_extra or {}).get("purpose")
            category = purpose if purpose in categories else (dt if dt in categories else "設計の規則")
            store.insert("condition", recorded_by, form="ids", source_version_id=version_id, clue_id=cid, category=category,
                         text_ref=(rec.format_extra or {}).get("ids", {}).get("name"),
                         ids_json=dumps((rec.format_extra or {}).get("ids")), rule_json=None,
                         severity="要確認", scope_json=dumps({"title": (rec.format_extra or {}).get("title")}))

    # A-4: the intake log (B-6: nothing silently)
    def log(kind: str, detail: dict) -> None:
        store.insert("intake_log", recorded_by, source_version_id=version_id, kind=kind, detail_json=dumps(detail))

    log("レイヤごとの図形の数", {"counts": [{"layer": l, "kind": k, "n": n} for (l, k), n in sorted(counts.items())],
                           "total": sum(counts.values())})
    for note_kind, detail in result.notes:
        log(note_kind, detail)
    if generated:
        log("生成物として外した手掛かり", {
            "counts": [{"layer": l, "kind": k, "n": n} for (l, k), n in sorted(generated.items())],
            "total": sum(generated.values()),
            "by": "sha256 が生成の記録と一致（版ごと）" if generation_of_file else f"レイヤ名の印 {prefix}",
            "generation_id": generation_of_file["id"] if generation_of_file else (prefix_generations[-1] if prefix_generations else None)})
    store.insert("run_summary", recorded_by, kind="取り込み", counts_json=dumps({
        "source_version_id": version_id, "clues": len(result.clues), "observed_top_level": sum(counts.values()),
        "generated_top_level": sum(generated.values())}))
    store.commit()
    return ImportResult(source_id=source_id, source_version_id=version_id, counts=dict(counts),
                        generated_count=sum(generated.values()), notes=result.notes, file_name=path.name,
                        seq=seq, source_created=source_created)
