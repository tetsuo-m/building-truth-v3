"""Intake (A-2..A-5, B-1, H-2/M-1): source, attributes, version, clues, archive copy, log;
the same sha256 is not taken in twice; generated clues are kept but excluded from observation.
"""
from __future__ import annotations

import hashlib
import json

from helpers import STEP1, STEP2, count, make_project, one_room_dxf


def test_import_step1_keeps_every_clue_unrounded(tmp_path):
    from btruth.intake import import_file

    project, store = make_project(tmp_path)
    r = import_file(store, project, STEP1, source_name="1階平面図", kind="設計図",
                    drawing_type="建築平面図", discipline="建築", recorded_by="テスト")
    assert not r.skipped
    v = r.source_version_id
    top = "select count(*) from clue where source_version_id=? and parent_clue_id is null and kind=?"
    assert count(store, top, v, "LINE") == 12
    assert count(store, top, v, "TEXT") == 5
    assert count(store, top, v, "CIRCLE") == 4
    g = store.conn.execute(
        "select geometry_json from clue where source_version_id=? and kind='LINE' and layer_raw='GRID' order by seq limit 1",
        (v,)).fetchone()[0]
    assert json.loads(g)["start"] == [0.0, -1500.0, 0.0]
    src = tuple(store.conn.execute("select name, kind from source").fetchone())
    assert src == ("1階平面図", "設計図")
    attrs = {(r[0], r[1], r[2]) for r in store.conn.execute("select attribute, value, origin from source_attribute")}
    assert ("図面の種類", "建築平面図", "コマンドで指定") in attrs
    assert ("分野", "建築", "コマンドで指定") in attrs
    ver = store.conn.execute("select seq, file_name, sha256, format, reader_name, unit_factor, archive_path"
                             " from source_version where id=?", (v,)).fetchone()
    assert ver[0] == 1 and ver[1] == "step1.dxf" and ver[3] == "dxf" and ver[4] == "dxf" and ver[5] == 1.0
    assert ver[2] == hashlib.sha256(STEP1.read_bytes()).hexdigest()
    copy = project.folder / ver[6]
    assert copy.exists() and copy.read_bytes() == STEP1.read_bytes()
    kinds = {r[0] for r in store.conn.execute("select kind from intake_log where source_version_id=?", (v,))}
    assert "レイヤごとの図形の数" in kinds


def test_kind_may_be_left_empty_for_a_later_proposal(tmp_path):
    from btruth.intake import import_file

    project, store = make_project(tmp_path)
    import_file(store, project, STEP1, recorded_by="テスト")
    src = store.conn.execute("select name, kind from source").fetchone()
    assert src[0] == "step1" and src[1] is None
    assert count(store, "select count(*) from source_attribute") == 0


def test_same_sha256_is_not_imported_twice(tmp_path):
    from btruth.intake import import_file

    project, store = make_project(tmp_path)
    r1 = import_file(store, project, STEP1, source_name="平面図", recorded_by="テスト")
    n_clues = count(store, "select count(*) from clue")
    n_versions = count(store, "select count(*) from source_version")
    r2 = import_file(store, project, STEP1, source_name="平面図", recorded_by="テスト")
    assert r2.skipped and r2.existing_version_id == r1.source_version_id
    assert count(store, "select count(*) from clue") == n_clues
    assert count(store, "select count(*) from source_version") == n_versions
    assert count(store, "select count(*) from intake_log where kind='同じ中身の取り込み'") == 1


def test_second_version_of_the_same_source_gets_seq_2(tmp_path):
    from btruth.intake import import_file

    project, store = make_project(tmp_path)
    r1 = import_file(store, project, STEP1, source_name="平面図", recorded_by="テスト")
    r2 = import_file(store, project, STEP2, source_name="平面図", recorded_by="テスト")
    assert r1.source_id == r2.source_id
    seqs = [r[0] for r in store.conn.execute("select seq from source_version order by seq")]
    assert seqs == [1, 2]
    assert count(store, "select count(*) from source") == 1


def test_next_version_of_a_source_even_when_the_file_name_differs(tmp_path):
    """改訂 6 (6): the person chooses: next version of an existing source, or a new source."""
    from btruth.intake import SourceExists, SourceNotFound, import_file
    import pytest

    project, store = make_project(tmp_path)
    r1 = import_file(store, project, STEP1, source_name="1階平面図", kind="設計図", recorded_by="テスト")
    r2 = import_file(store, project, STEP2, source_name="1階平面図", mode="next", recorded_by="テスト")
    assert r2.source_id == r1.source_id and r2.seq == 2 and r2.source_created is False
    with pytest.raises(SourceNotFound):
        import_file(store, project, STEP2, source_name="無い名前", mode="next", recorded_by="テスト")
    with pytest.raises(SourceExists):
        import_file(store, project, STEP2, source_name="1階平面図", mode="new", recorded_by="テスト")
    other = one_room_dxf(tmp_path / "other.dxf", dx=1.0)
    r3 = import_file(store, project, other, source_name="2階平面図", mode="new", recorded_by="テスト")
    assert r3.source_created is True and r3.seq == 1
    assert count(store, "select count(*) from source") == 2


def test_generated_layer_is_kept_but_excluded_from_observation(tmp_path):
    from btruth.intake import import_file

    project, store = make_project(tmp_path)
    path = one_room_dxf(tmp_path / "plan_v4.dxf", extra=[
        ("LINE", "BT_GEN_WALL_FACE", {"start": (0, 50), "end": (6000, 50)}),
        ("LINE", "BT_GEN_WALL_FACE", {"start": (0, -50), "end": (6000, -50)}),
    ])
    r = import_file(store, project, path, source_name="平面図", recorded_by="テスト")
    v = r.source_version_id
    gen = count(store, "select count(*) from clue where source_version_id=? and generated_from is not null", v)
    obs = count(store, "select count(*) from clue where source_version_id=? and generated_from is null and parent_clue_id is null", v)
    assert gen == 2 and obs == 17
    assert r.generated_count == 2
    kinds = {r[0] for r in store.conn.execute("select kind from intake_log where source_version_id=?", (v,))}
    assert "生成物として外した手掛かり" in kinds


def test_a_file_the_vessel_itself_wrote_is_excluded_whole(tmp_path):
    """M-1: a file whose sha256 matches a generation row is a generated file; every clue is excluded."""
    from btruth.intake import import_file

    project, store = make_project(tmp_path)
    path = one_room_dxf(tmp_path / "gen.dxf")
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    gid = store.insert("generation", kind="図面", as_of_json="{}", path=str(path), sha256=sha,
                       marker_json=json.dumps({"layer_prefix": "BT_GEN_"}), recorded_by="テスト")
    r = import_file(store, project, path, source_name="平面図", recorded_by="テスト")
    v = r.source_version_id
    assert count(store, "select count(*) from clue where source_version_id=? and generated_from is null", v) == 0
    assert store.conn.execute("select distinct generated_from from clue where source_version_id=?", (v,)).fetchone()[0] == gid


def test_csv_and_text_files_go_through_the_same_intake(tmp_path):
    from btruth.intake import import_file

    project, store = make_project(tmp_path)
    minutes = tmp_path / "minutes.txt"
    minutes.write_text("WT-1 の間仕切は PB 二重張りとする。\n", encoding="utf-8")
    r = import_file(store, project, minutes, source_name="第3回打合せ議事録", kind="議事録", recorded_by="テスト")
    assert count(store, "select count(*) from clue where source_version_id=? and kind='SENTENCE'", r.source_version_id) == 1
    from conftest import ROOT
    wt = ROOT / "samples" / "step1" / "wall_types.csv"
    r2 = import_file(store, project, wt, source_name="壁種表", kind="設計図", drawing_type="壁種表", recorded_by="テスト")
    assert count(store, "select count(*) from clue where source_version_id=? and kind='ROW'", r2.source_version_id) == 1
    assert store.conn.execute("select format from source_version where id=?", (r2.source_version_id,)).fetchone()[0] == "csv"


def test_unknown_format_is_refused_without_touching_the_vessel(tmp_path):
    import pytest

    from btruth.intake import UnsupportedFormat, import_file

    project, store = make_project(tmp_path)
    p = tmp_path / "x.jww"
    p.write_bytes(b"JwwData")
    before = count(store, "select count(*) from source_version")
    with pytest.raises(UnsupportedFormat):
        import_file(store, project, p, recorded_by="テスト")
    assert count(store, "select count(*) from source_version") == before
