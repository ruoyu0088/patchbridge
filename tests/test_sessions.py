from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

import pytest

from patchbridge.errors import AppError
from patchbridge.sessions import SessionStore
from tests.conftest import make_session


def test_session_layout_and_manifest(store: SessionStore, profile, project_root: Path, answer_add_line: str):
    session_id = make_session(store, profile, answer=answer_add_line)
    directory = store.session_dir(session_id)
    for name in ["meta.json", "requirement.md", "selection.json", "bundle.txt", "answer.md", "parsed.json"]:
        assert (directory / name).exists()
    manifest = json.loads((directory / "patches" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["patches"][0]["file"] == "p0001.diff"
    assert manifest["patches"][0]["path"] == "src/calculator.py"
    # Path mapping comes from the manifest, not from the storage filename.
    assert (directory / "patches" / manifest["patches"][0]["file"]).exists()
    details = store.details(session_id)
    assert details["status"] == "parsed"
    assert details["bundle_path"].endswith("bundle.txt")


def test_events_are_appended(store: SessionStore, profile, answer_add_line: str):
    session_id = make_session(store, profile, answer=answer_add_line)
    before = store.events(session_id)
    store.append_event(session_id, "note", {"message": "hello"})
    after = store.events(session_id)
    assert len(after) == len(before) + 1
    assert after[-1]["type"] == "note"
    assert after[-1]["seq"] > after[-2]["seq"]


def test_index_detects_manual_directory_delete(store: SessionStore, profile, answer_add_line: str):
    session_id = make_session(store, profile, answer=answer_add_line)
    store.ensure_index()
    assert store.index_status()["stale"] is False
    shutil.rmtree(store.session_dir(session_id))
    status = store.index_status()
    assert status["stale"] is True
    assert session_id in status["orphan"]
    listed = store.list_sessions()
    assert listed["index"]["rebuilt"] is True
    assert all(item["id"] != session_id for item in listed["sessions"])


def test_archive_structure_and_reload(store: SessionStore, profile, answer_add_line: str):
    session_id = make_session(store, profile, answer=answer_add_line)
    store.archive(session_id)
    assert store.is_archived(session_id)
    zip_path = store.zip_path(session_id)
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
    assert "meta.json" in names
    assert "bundle.txt" in names
    assert "patches/manifest.json" in names
    assert all(not name.startswith("/") and ".." not in name.split("/") for name in names)
    assert store.details(session_id)["status"] == "parsed"
    new_id = store.reload(session_id)
    assert new_id != session_id
    assert store.derived_status(new_id) == "parsed"
    assert len(store.get_patches(new_id)) == 1


def test_delete_active_requires_confirmation(store: SessionStore, profile, project_root: Path):
    from patchbridge.applying import apply_session

    session_id = make_session(
        store,
        profile,
        answer="""## 修改说明
x
## Commit 建议
fix: x
## 文件补丁
```diff
diff --git a/src/calculator.py b/src/calculator.py
--- a/src/calculator.py
+++ b/src/calculator.py
@@ -1,1 +1,1 @@
-def add(left, right):
+def add(a, b):
```
""",
    )
    apply_session(store, session_id, ["p0001"])
    with pytest.raises(AppError) as info:
        store.delete(session_id)
    assert info.value.code == "active_apply"
    store.delete(session_id, confirm_active=True)
    assert not store.session_dir(session_id).exists()


def test_history_filters(store: SessionStore, profile, answer_add_line: str):
    session_id = make_session(store, profile, answer=answer_add_line)
    result = store.list_sessions(status="parsed", query="Make a change")
    assert any(item["id"] == session_id for item in result["sessions"])
    result = store.list_sessions(status="applied")
    assert all(item["id"] != session_id for item in result["sessions"])
