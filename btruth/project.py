"""The project folder (物件のフォルダ) and creating the vessel inside it.

Layout (design J, decision Q9):
    <folder>/settings/project.csv   key,value  — name, db_path, office_dir, archive_dir, dxf_default_codepage, csv_encoding
    <folder>/settings/layer_roles.csv
    <folder>/rules/*.csv            rules, authority, document_rank, element_kinds, attributes, relation_kinds, conditions
    <folder>/knowledge/readings.csv
    <folder>/archive/               copies of every imported file (B-8)
    <folder>/out/                   outputs (H-1); recorded in `generation`
    <folder>/<db_path>              the SQLite master copy (C-9)

Commands receive the folder only; the database path comes from settings (G-1 (a)).
"""
from __future__ import annotations

import csv
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from btruth import __version__
from btruth.common import dumps, now_iso
from btruth.store import Store

DEFAULTS_DIR = Path(__file__).parent / "defaults"
SETTINGS_FILE = Path("settings") / "project.csv"

DEFAULT_SETTINGS = {
    "db_path": "db/truth.sqlite",
    "office_dir": "",
    "archive_dir": "archive",
    "dxf_default_codepage": "ANSI_932",   # Jw_cad exports omit $DWGCODEPAGE; Japanese drawings are Shift_JIS
    "csv_encoding": "utf-8-sig",
}

# Default CSV tables copied into a new project (relative paths are the same in the office folder).
DEFAULT_TABLES = [
    "rules/rules.csv", "rules/authority.csv", "rules/document_rank.csv", "rules/element_kinds.csv",
    "rules/attributes.csv", "rules/relation_kinds.csv", "rules/conditions.csv",
    "settings/layer_roles.csv", "knowledge/readings.csv",
]


@dataclass
class ProjectFolder:
    folder: Path
    settings: dict = field(default_factory=dict)

    @classmethod
    def load(cls, folder: Path) -> "ProjectFolder":
        folder = Path(folder)
        path = folder / SETTINGS_FILE
        if not path.exists():
            raise FileNotFoundError(f"物件のフォルダではありません（{SETTINGS_FILE} がない）: {folder}")
        settings = dict(DEFAULT_SETTINGS)
        with open(path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("key"):
                    settings[row["key"]] = row.get("value", "") or ""
        return cls(folder=folder, settings=settings)

    @property
    def db_path(self) -> Path:
        return self.folder / self.settings["db_path"]

    @property
    def office_dir(self) -> Path | None:
        raw = (self.settings.get("office_dir") or "").strip()
        return Path(raw) if raw else None

    @property
    def archive_dir(self) -> Path:
        return self.folder / (self.settings.get("archive_dir") or "archive")

    @property
    def out_dir(self) -> Path:
        return self.folder / "out"


def write_settings(folder: Path, settings: dict) -> None:
    path = folder / SETTINGS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["key", "value"])
        for k, v in settings.items():
            w.writerow([k, v])


def init_project(folder: Path, name: str, office_dir: Path | None = None,
                 recorded_by: str = "器を作るコマンド") -> ProjectFolder:
    """Create the folder, the default CSV tables, the vessel and the default structure (C-2b)."""
    folder = Path(folder)
    for sub in ("rules", "settings", "knowledge", "archive", "out"):
        (folder / sub).mkdir(parents=True, exist_ok=True)
    settings = dict(DEFAULT_SETTINGS)
    settings["name"] = name
    settings["office_dir"] = str(office_dir) if office_dir else ""
    if not (folder / SETTINGS_FILE).exists():
        write_settings(folder, settings)
    for rel in DEFAULT_TABLES:
        target = folder / rel
        if not target.exists():
            shutil.copyfile(DEFAULTS_DIR / rel, target)
    project = ProjectFolder.load(folder)
    if project.db_path.exists():
        raise FileExistsError(f"正本の DB がすでにあります: {project.db_path}")
    with Store.open(project.db_path, create=True) as store:
        from btruth.schema import SCHEMA_VERSION
        project_id = store.insert("project", recorded_by, name=name, created_at=now_iso(),
                                  schema_version=SCHEMA_VERSION)
        register_readers(store, recorded_by)
        from btruth.tables import load_tables
        load_tables(store, project, recorded_by=recorded_by)
        create_default_structure(store, project_id, recorded_by)
        store.commit()
    return project


def open_store(project: ProjectFolder) -> Store:
    return Store.open(project.db_path)


def register_readers(store: Store, recorded_by: str) -> None:
    """B-2: the readers this vessel knows (adding one later does not change the tables)."""
    from btruth.readers import READERS
    for r in READERS:
        store.insert("reader", recorded_by, name=r.name, version=r.version, formats=",".join(r.formats), note=r.note)


def create_default_structure(store: Store, project_id: str, recorded_by: str) -> None:
    """C-2b / E-2 / decision Q17: 敷地 1, 建物 1, 階 1 (named 1階), 外部 1, aggregated down to the project.

    They are an interpretation of the rule reader (agent.kind = 規則の読み手, summary = 既定の構成), so the
    kinds and names are observed claims that count as the default reading (D-2 step 3) until a person
    renames them.
    """
    agent_id = store.insert("agent", recorded_by, name="規則の読み手", kind="規則の読み手", model=None,
                            version=__version__, instructions_sha256=None)
    interp = store.insert("interpretation", recorded_by, source_version_ids_json="[]", agent_id=agent_id,
                          scope_json=dumps({"kind": "既定の構成"}), premise_json="[]", summary="既定の構成")

    def element(kind: str, name: str) -> str:
        eid = store.insert("element", recorded_by, project_id=project_id, created_by_interpretation_id=interp)
        item = store.insert("interpretation_item", recorded_by, interpretation_id=interp, kind="要素を作る",
                            element_id=eid, reason="器を作るときの既定の構成（E-2）", confidence=1.0,
                            rule_check_status="通った")
        for attribute, value in (("種類", kind), ("名前", name)):
            store.insert("claim", recorded_by, subject_kind="element", subject_id=eid, attribute=attribute,
                         value_json=dumps(value), mode="観測", interpretation_id=interp, agent_id=agent_id,
                         confidence=1.0)
        return eid

    site = element("敷地", "敷地")
    building = element("建物", "建物")
    storey = element("階", "1階")
    outside = element("外部", "外部")

    def aggregate(child: str, parent: str, **role) -> None:
        store.insert("relation", recorded_by, kind="集める", from_element_id=child, to_element_id=parent,
                     role_json=dumps(role) if role else None, created_by_interpretation_id=interp)

    aggregate(site, project_id, to_kind="project")      # 敷地 → 物件 (the project row is the top; E-7)
    aggregate(building, site)
    aggregate(storey, building)
    aggregate(outside, site)                             # the outside belongs to the site (decision Q17)
