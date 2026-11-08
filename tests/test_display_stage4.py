"""What the person sees after stage 4 (findings of the person's trial on out\\try4, 2026-11-08):

1. a move shows the value before (the approved value of the earlier version) and after (the new observation),
   also after the batch approval, when the effective value is already the new one;
2. coordinates shown to the person are relative to the frame of the grid labels (X1・Y1), with one line saying
   so; the stored values are not changed (B-1);
3. the batch approval closes the 移動の承認待ち issue with a record; the diff says whether an issue is open or closed;
4. approve-moves with nothing to approve says why (already approved / waiting for the element's approval / judged,
   one by one / no moves at all).
"""
from __future__ import annotations

import json

import pytest

from helpers import STEP2, STEP2_MOVED, count, import_sample, register_fixture
from btruth.intake import import_file

FRAME_NOTE = "通り芯の符号 X1・Y1 の交点"


def version(store, name, seq):
    return store.scalar("select v.id from source_version v join source s on s.id=v.source_id where s.name=? and v.seq=?",
                        name, seq)


def setup(tmp_path, approve_v1=True):
    from btruth.identity import identify
    from btruth.review import approve_interpretation
    project, store = import_sample(tmp_path, STEP2)
    r = register_fixture(store, project, "step2_fixed")
    if approve_v1:
        approve_interpretation(store, project, r.interpretation_id, reason="ok", reviewed_by="てっちゃん")
    v2 = import_file(store, project, STEP2_MOVED, source_name="平面図", mode="next", recorded_by="テスト").source_version_id
    res = identify(store, project, version(store, "平面図", 1), v2, recorded_by="テスト")
    return project, store, r, res


def move_item_of(store, res, element_id):
    return store.one("select * from interpretation_item where id in (%s) and element_id=?" % ",".join("?" * len(res.move_items)),
                     *res.move_items, element_id)


def approve_moves(store, project, run_id, **kw):
    from btruth.review import approve_moves as go
    return go(store, project, run_id, reason="確かめた", reviewed_by="てっちゃん", **kw)


# ---------------------------------------------------------------- 1 and 2: before / after, aligned coordinates
def test_move_line_shows_before_and_after_in_the_grid_frame_also_after_approval(tmp_path, terminal_ok):
    from btruth.review import describe_item
    project, store, r, res = setup(tmp_path)
    item = move_item_of(store, res, r.element_ids["wall_A"])
    before_approval = describe_item(store, project, item)
    approve_moves(store, project, res.run_id)
    after_approval = describe_item(store, project, item)
    for line in (before_approval, after_approval):
        assert "[[2300.0,0.0],[2300.0,4000.0]] → [[2800.0,0.0],[2800.0,4000.0]]" in line, line
        assert "210002" not in line                       # not the Jw_cad file coordinates
    # the stored values are not changed (B-1)
    assert store.one("select 1 from claim where subject_id=? and value_json like '%210002800%'", r.element_ids["wall_A"])


def test_listing_and_items_carry_one_line_about_the_frame(tmp_path, terminal_ok):
    from btruth.review import listing
    project, store, r, res = setup(tmp_path)
    items = [store.one("select * from interpretation_item where id=?", i) for i in res.move_items]
    text = listing(store, project, items, "一覧")
    assert FRAME_NOTE in text and "保存した値" in text


def test_diff_shows_before_after_aligned_and_the_frame(tmp_path, terminal_ok):
    from btruth.diff import build_diff, render_text
    project, store, r, res = setup(tmp_path)
    text = render_text(build_diff(store, project, res.run_id))
    assert FRAME_NOTE in text
    assert "[[2300.0,0.0],[2300.0,4000.0]] → [[2800.0,0.0],[2800.0,4000.0]]" in text
    assert "210002" not in text


def test_show_and_issues_show_aligned_coordinates(tmp_path, terminal_ok):
    from btruth.show import build_show, render_show
    from btruth.display import issue_lines
    project, store, r, res = setup(tmp_path)
    html = render_show(build_show(store, project))
    assert FRAME_NOTE in html
    panel = [d for d in build_show(store, project)["elements"] if d["id"] == r.element_ids["wall_A"]][0]
    shown = [c["value"] for c in panel["claims"] if c["attribute"] == "芯線"]
    assert any("2300.0,0.0" in v for v in shown) and not any("210002300" in v for v in shown)
    approve_moves(store, project, res.run_id)
    from btruth.effective import open_issues
    text = "\n".join(issue_lines(store, project, open_issues(store, project)))
    assert "名前がない空間" in text and "210000000" not in text


# ---------------------------------------------------------------- 3: the waiting issue is closed, with a record
def test_batch_approval_closes_the_waiting_issue_with_a_record(tmp_path, terminal_ok):
    from btruth.diff import build_diff, render_text
    from btruth.effective import open_issues
    project, store, r, res = setup(tmp_path)
    waiting = store.scalar("select id from issue where identity_run_id=? and kind='移動の承認待ち'", res.run_id)
    text = render_text(build_diff(store, project, res.run_id))
    assert "移動の承認待ち" in text and "開いている" in text
    rid = approve_moves(store, project, res.run_id)
    close = store.one("select action, choice_json from review where target_kind='issue' and target_id=?", waiting)
    assert close is not None and json.loads(close["choice_json"])["review_id"] == rid
    assert waiting not in {i["id"] for i in open_issues(store, project)}
    text = render_text(build_diff(store, project, res.run_id))
    assert "閉じた" in text


# ---------------------------------------------------------------- 4: nothing to approve, and why
def test_nothing_to_approve_says_already_approved(tmp_path, terminal_ok):
    from btruth.review import ApprovalBlocked
    project, store, r, res = setup(tmp_path)
    approve_moves(store, project, res.run_id)
    with pytest.raises(ApprovalBlocked) as exc:
        approve_moves(store, project, res.run_id)
    assert "すでに承認済み" in str(exc.value) and "7" in str(exc.value)


def test_nothing_to_approve_says_waiting_for_the_element(tmp_path, terminal_ok):
    from btruth.review import ApprovalBlocked
    project, store, r, res = setup(tmp_path, approve_v1=False)
    with pytest.raises(ApprovalBlocked) as exc:
        approve_moves(store, project, res.run_id)
    msg = str(exc.value)
    assert "元の要素が未承認" in msg and r.element_ids["wall_A"] in msg
    assert count(store, "select count(*) from review where target_kind='identity_run'") == 0


def test_judged_moves_are_named_and_the_rest_is_approved(tmp_path, terminal_ok):
    from btruth.review import ApprovalBlocked, decide
    from helpers import JW_ORIGIN
    project, store = import_sample(tmp_path, STEP2)
    r = register_fixture(store, project, "step2_fixed")
    from btruth.review import approve_interpretation
    approve_interpretation(store, project, r.interpretation_id, reason="ok", reviewed_by="てっちゃん")
    wall = r.element_ids["wall_A"]
    decide(store, project, wall, "芯線", [[JW_ORIGIN[0] + 2300, JW_ORIGIN[1]], [JW_ORIGIN[0] + 2300, JW_ORIGIN[1] + 4000]],
           reason="現地", reviewed_by="てっちゃん", unit="mm")
    from btruth.identity import identify
    v2 = import_file(store, project, STEP2_MOVED, source_name="平面図", mode="next", recorded_by="テスト").source_version_id
    res = identify(store, project, version(store, "平面図", 1), v2, recorded_by="テスト")
    seen = {}
    approve_moves(store, project, res.run_id, confirm=lambda text: seen.setdefault("t", text) is not None)
    assert "判断が付いていて一つずつ" in seen["t"] and wall in seen["t"]
    with pytest.raises(ApprovalBlocked) as exc:
        approve_moves(store, project, res.run_id)
    msg = str(exc.value)
    assert "判断が付いていて一つずつ" in msg and wall in msg and "すでに承認済み" in msg


def test_nothing_to_approve_says_there_were_no_moves(tmp_path, terminal_ok):
    from btruth.identity import identify
    from btruth.review import ApprovalBlocked, approve_interpretation
    from helpers import step2_like_dxf, make_project, WALL_TYPES, step2_fixture_at
    project, store = make_project(tmp_path)
    import_file(store, project, step2_like_dxf(tmp_path / "v1.dxf"), source_name="平面図", kind="設計図",
                drawing_type="建築平面図", recorded_by="テスト")
    import_file(store, project, WALL_TYPES, source_name="壁種表", kind="設計図", drawing_type="壁種表", recorded_by="テスト")
    from btruth.propose import register_proposal
    p = step2_fixture_at(0, 0)
    p["source_versions"] = ["平面図@1", "壁種表@1"]
    for e in p["elements"]:
        e["claims"] = [c for c in e["claims"] if c.get("attribute") != "天井高"]
    rr = register_proposal(store, project, p, recorded_by="テスト")
    approve_interpretation(store, project, rr.interpretation_id, reason="ok", reviewed_by="てっちゃん")
    import ezdxf
    v2 = step2_like_dxf(tmp_path / "v2.dxf")
    doc = ezdxf.readfile(v2)
    doc.layers.add("UNUSED")
    doc.saveas(v2)
    vid = import_file(store, project, v2, source_name="平面図", mode="next", recorded_by="テスト").source_version_id
    res = identify(store, project, version(store, "平面図", 1), vid, recorded_by="テスト")
    with pytest.raises(ApprovalBlocked) as exc:
        approve_moves(store, project, res.run_id)
    assert "移動がない" in str(exc.value)
