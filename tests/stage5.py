"""Builders for the stage-5 tests: fictional tables, minutes, legends and plans (BRIEF step2 §3: no real data)."""
from __future__ import annotations

from pathlib import Path

from helpers import STOREY, claim, element, ev, make_project, proposal, relation, seg, write_dxf
from btruth.intake import import_file


def write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def imp(store, project, path, source, kind, drawing_type=None, date=None, mode="auto", discipline=None):
    return import_file(store, project, path, source_name=source, kind=kind, drawing_type=drawing_type, document_date=date,
                       discipline=discipline, mode=mode, recorded_by="テスト").source_version_id


def ref(store, source: str, seq_of_version: int, text: str, kinds=("ROW", "SENTENCE", "TEXT")) -> str:
    """The clue ref "<source>@<v>#<seq>" of the clue whose text contains `text`."""
    row = store.one("select c.seq from clue c join source_version v on v.id=c.source_version_id join source s on s.id=v.source_id "
                    "where s.name=? and v.seq=? and instr(coalesce(c.text_raw,''), ?) > 0 and c.kind in (%s) order by c.seq"
                    % ",".join("?" * len(kinds)), source, seq_of_version, text, *kinds)
    assert row, (source, text)
    return f"{source}@{seq_of_version}#{row['seq']}"


def approve(store, project, interpretation_id):
    from btruth.review import approve_interpretation
    return approve_interpretation(store, project, interpretation_id, reason="見比べた", reviewed_by="てっちゃん")


def register(store, project, p):
    from btruth.propose import register_proposal
    return register_proposal(store, project, p, recorded_by="テスト")


def check(store, project, scope=None):
    from btruth.consistency import check as run
    return run(store, project, recorded_by="テスト", scope=scope)


def open_kinds(store, project):
    from btruth.effective import open_issues
    return sorted(i["kind"] for i in open_issues(store, project))


def open_of(store, project, kind):
    from btruth.effective import open_issues
    return [i for i in open_issues(store, project) if i["kind"] == kind]


# ---------------------------------------------------------------- a project with documents only (例3・例8)
WT_HEADER = "type_code,name,core,board,boards,sides,total_mm\n"


def wall_type_project(tmp_path, wt1_boards=1, with_site=True):
    project, store = make_project(tmp_path)
    imp(store, project, write_text(tmp_path / "wt.csv", WT_HEADER + f"WT-1,間仕切,LGS65,PB12.5,{wt1_boards},両面,{65 + 25 * wt1_boards}\n"
                                   "WT-2,間仕切,LGS65,PB12.5,1,両面,90\n"), "壁種表", "設計図", "壁種表")
    imp(store, project, write_text(tmp_path / "minutes3.md", "# 第3回 打合せ\n\nWT-1 の間仕切は PB 二重張りとする。WT-2 の遮音性能は次回確認。\n"),
        "議事録3", "議事録", date="2026-10-01")
    if with_site:
        imp(store, project, write_text(tmp_path / "lgs.csv", "type_code,board,boards\nWT-1,PB12.5,1\n"), "施工図LGS", "施工図", "LGS割付図")
    return project, store


def composition(boards):
    return {"下地": "LGS65", "ボード": "PB12.5", "枚数": boards, "面": "両面"}


def wall_type_reading(store, with_site=True):
    """The AI's reading of the wall-type table, the minutes and the site drawing (one proposal, refs by text)."""
    row1, row2 = ref(store, "壁種表", 1, "WT-1"), ref(store, "壁種表", 1, "WT-2")
    s_decide, s_open = ref(store, "議事録3", 1, "二重張りとする"), ref(store, "議事録3", 1, "次回確認")
    els = [element("wt1", "壁種", [claim("符号", "WT-1", [ev(row1)]), claim("構成", composition(1), [ev(row1)])], [ev(row1)]),
           element("wt2", "壁種", [claim("符号", "WT-2", [ev(row2)])], [ev(row2)])]
    claims = [dict(claim("構成", composition(2), [ev(s_decide)]), subject="wt1", statement_kind="決定", source="議事録3@1"),
              dict(claim("遮音性能", "次回確認", [ev(s_open)]), subject="wt2", statement_kind="未決", source="議事録3@1")]
    sources = ["壁種表@1", "議事録3@1"]
    if with_site:
        site = ref(store, "施工図LGS", 1, "WT-1")
        claims.append(dict(claim("構成", composition(1), [ev(site)]), subject="wt1", source="施工図LGS@1"))
        sources.append("施工図LGS@1")
    return proposal(els, claims=claims, sources=sources, agent_name="AI の読み（テスト）")


# ---------------------------------------------------------------- the plan of 例9 with a door schedule and minutes
DOOR_HEADER = "code,type,width,height,spec\n"


def door_schedule(tmp_path, rows="AD-1,片開き扉,800,2000,木製フラッシュ\n", name="doors.csv"):
    return write_text(tmp_path / name, DOOR_HEADER + rows)
