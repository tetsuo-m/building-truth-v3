"""The report: list of clues per version and the ground for showing what is not yet read (B-3)."""
from __future__ import annotations

from helpers import STEP1, make_project, one_room_dxf


def test_report_lists_clues_and_unread_clues(tmp_path):
    from btruth.intake import import_file
    from btruth.report import build_report, render_html, render_text

    project, store = make_project(tmp_path)
    r = import_file(store, project, STEP1, source_name="1階平面図", kind="設計図", drawing_type="建築平面図",
                    recorded_by="テスト")
    rep = build_report(store, project)
    assert rep["project"]["name"] == "架空の物件"
    ver = [v for v in rep["versions"] if v["id"] == r.source_version_id][0]
    assert ver["source_name"] == "1階平面図"
    assert ver["counts"][("GRID", "LINE")] == 4
    assert ver["clue_total"] == 21 and ver["generated"] == 0
    # nothing has been interpreted yet, so every observed clue is "not yet used"
    assert ver["unread"] == 21
    text = render_text(rep)
    assert "1階平面図" in text and "読み残し" in text and "21" in text
    html = render_html(rep)
    assert html.startswith("<!DOCTYPE html>") and "101 事務室" in html


def test_generated_clues_are_shown_apart_and_not_counted_as_unread(tmp_path):
    from btruth.intake import import_file
    from btruth.report import build_report

    project, store = make_project(tmp_path)
    path = one_room_dxf(tmp_path / "g.dxf", extra=[("LINE", "BT_GEN_WALL_FACE", {"start": (0, 50), "end": (6000, 50)})])
    r = import_file(store, project, path, source_name="平面図", recorded_by="テスト")
    ver = [v for v in build_report(store, project)["versions"] if v["id"] == r.source_version_id][0]
    assert ver["generated"] == 1 and ver["unread"] == 17


def test_a_clue_used_as_evidence_is_no_longer_unread(tmp_path):
    from btruth.intake import import_file
    from btruth.report import build_report

    project, store = make_project(tmp_path)
    r = import_file(store, project, STEP1, source_name="平面図", recorded_by="テスト")
    clue_id = store.conn.execute("select id from clue where source_version_id=? order by seq limit 1",
                                 (r.source_version_id,)).fetchone()[0]
    # a future interpretation (stage 3) will point at clues like this; here we only write the evidence row
    agent = store.conn.execute("select id from agent").fetchone()[0]
    interp = store.insert("interpretation", source_version_ids_json=f'["{r.source_version_id}"]', agent_id=agent,
                          summary="テスト", recorded_by="テスト")
    item = store.insert("interpretation_item", interpretation_id=interp, kind="要素を作る", recorded_by="テスト")
    store.insert("interpretation_evidence", item_id=item, clue_id=clue_id, role="主の根拠", recorded_by="テスト")
    ver = [v for v in build_report(store, project)["versions"] if v["id"] == r.source_version_id][0]
    assert ver["unread"] == 20


def test_write_report_records_a_generation_row(tmp_path):
    from btruth.intake import import_file
    from btruth.report import write_report

    project, store = make_project(tmp_path)
    import_file(store, project, STEP1, source_name="平面図", recorded_by="テスト")
    out = write_report(store, project, project.folder / "out" / "report.html", html=True, recorded_by="テスト")
    assert out.exists() and out.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")
    row = store.conn.execute("select kind, path from generation").fetchone()
    assert row[0] == "レポート" and row[1].endswith("report.html")
