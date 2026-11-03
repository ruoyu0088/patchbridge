from __future__ import annotations

from pathlib import Path

from patchbridge.applying import apply_session, revert_session
from patchbridge.exporting import combined_patch, disk_diff
from patchbridge.sessions import SessionStore
from tests.conftest import make_session


ANSWER = """## 修改说明
Change it.
## Commit 建议
feat: change
## 文件补丁
```diff
diff --git a/src/calculator.py b/src/calculator.py
--- a/src/calculator.py
+++ b/src/calculator.py
@@ -1,2 +1,2 @@
 def add(left, right):
-    return left + right
+    return left + right + 1
```
"""


def test_archived_session_can_be_reverted(store: SessionStore, profile, project_root: Path):
    session_id = make_session(store, profile, answer=ANSWER)
    apply_session(store, session_id, ["p0001"])
    store.archive(session_id)
    assert store.is_archived(session_id)
    result = revert_session(store, session_id)
    assert result["restored"] == ["src/calculator.py"]
    assert not store.is_archived(session_id)
    assert "return left + right\n" in (
        project_root / "src" / "calculator.py"
    ).read_text(encoding="utf-8")
    assert store.derived_status(session_id) == "reverted"


def test_disk_diff_reports_external_change(store: SessionStore, profile, project_root: Path):
    session_id = make_session(store, profile, answer=ANSWER)
    apply_session(store, session_id, ["p0001"])
    (project_root / "src" / "calculator.py").write_text(
        "def add(left, right):\n    return left + right + 2\n", encoding="utf-8"
    )
    diff = disk_diff(store, session_id)
    assert diff["available"] is True
    assert diff["files"][0]["path"] == "src/calculator.py"
    assert diff["files"][0]["status"] == "modified"
    assert "+    return left + right + 2" in diff["files"][0]["diff"]


def test_export_from_archive(store: SessionStore, profile, project_root: Path):
    session_id = make_session(store, profile, answer=ANSWER)
    store.archive(session_id)
    text = combined_patch(store, session_id)
    assert text.startswith("diff --git a/src/calculator.py")
    assert "+++ b/src/calculator.py" in text
