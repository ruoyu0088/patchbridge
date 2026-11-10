from __future__ import annotations

from patchbridge.diff_view import build_diff_rows


def test_side_by_side_rows_for_change():
    rows = build_diff_rows(b"one\ntwo\nthree\n", b"one\nTWO\nthree\n")["rows"]
    assert rows[0]["type"] == "equal"
    changed = next(row for row in rows if row["type"] == "change")
    assert changed["old_line"] == 2
    assert changed["new_line"] == 2
    assert changed["old_text"] == "two"
    assert changed["new_text"] == "TWO"


def test_side_by_side_add_has_no_old_line():
    rows = build_diff_rows(b"one\n", b"one\ntwo\n")["rows"]
    added = next(row for row in rows if row["type"] == "add")
    assert added["old_line"] is None
    assert added["new_line"] == 2
    assert added["new_text"] == "two"


def test_side_by_side_delete_has_no_new_line():
    rows = build_diff_rows(b"one\ntwo\n", b"one\n")["rows"]
    deleted = next(row for row in rows if row["type"] == "del")
    assert deleted["old_line"] == 2
    assert deleted["new_line"] is None
    assert deleted["old_text"] == "two"
