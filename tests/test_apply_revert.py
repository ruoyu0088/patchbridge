from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from patchbridge.applying import apply_session, dry_run, revert_session
from patchbridge.errors import AppError
from patchbridge.exporting import combined_patch
from patchbridge.sessions import SessionStore
from tests.conftest import make_session


def _answer_two_files() -> str:
    return """## 修改说明
Change both files.

## Commit 建议
feat: change both

## 文件补丁
### src/calculator.py
```diff
diff --git a/src/calculator.py b/src/calculator.py
--- a/src/calculator.py
+++ b/src/calculator.py
@@ -1,2 +1,2 @@
 def add(left, right):
-    return left + right
+    return left + right + 1
```
### README.md
```diff
diff --git a/README.md b/README.md
--- a/README.md
+++ b/README.md
@@ -1,1 +1,1 @@
-# Demo
+# Demo Project
```
"""


def test_partial_apply_and_backup(store: SessionStore, profile, project_root: Path):
    session_id = make_session(
        store,
        profile,
        files=["src/calculator.py", "README.md"],
        answer=_answer_two_files(),
    )
    result = apply_session(store, session_id, ["p0001"])
    assert result["paths"] == ["src/calculator.py"]
    assert "+ 1" not in (project_root / "README.md").read_text(encoding="utf-8")
    assert "+ 1" in (project_root / "src" / "calculator.py").read_text(encoding="utf-8")
    event = store.events(session_id)[-1]
    assert event["type"] == "apply"
    manifest_path = store.config.data_dir / Path(*event["data"]["backup_manifest"].split("/"))
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["files"][0]["existed"] is True
    assert manifest["files"][0]["before_sha256"]
    assert manifest["files"][0]["after_sha256"]
    assert store.derived_status(session_id) == "applied"


def test_multiple_batches_and_lifo_revert(store: SessionStore, profile, project_root: Path):
    session_id = make_session(
        store,
        profile,
        files=["src/calculator.py", "README.md"],
        answer=_answer_two_files(),
    )
    apply_session(store, session_id, ["p0001"])
    apply_session(store, session_id, ["p0002"])
    assert (project_root / "README.md").read_text(encoding="utf-8").startswith("# Demo Project")
    with pytest.raises(AppError) as info:
        apply_session(store, session_id, ["p0001"])
    assert info.value.code == "patch_already_applied"

    first = revert_session(store, session_id)
    assert first["paths"] == ["README.md"]
    assert (project_root / "README.md").read_text(encoding="utf-8").startswith("# Demo")
    assert "+ 1" in (project_root / "src" / "calculator.py").read_text(encoding="utf-8")
    second = revert_session(store, session_id)
    assert second["paths"] == ["src/calculator.py"]
    assert "return left + right\n" in (project_root / "src" / "calculator.py").read_text(encoding="utf-8")
    assert store.derived_status(session_id) == "reverted"


def test_hash_change_requires_explicit_confirmation(store: SessionStore, profile, project_root: Path):
    session_id = make_session(store, profile, answer=_answer_two_files())
    target = project_root / "src" / "calculator.py"
    target.write_text(
        "# local edit\n\ndef add(left, right):\n    return left + right\n",
        encoding="utf-8",
    )
    status = dry_run(store, session_id, ["p0001"])
    assert status["results"][0]["hash_status"] == "changed"
    with pytest.raises(AppError) as info:
        apply_session(store, session_id, ["p0001"])
    assert info.value.code == "hash_changed"
    apply_session(
        store,
        session_id,
        ["p0001"],
        confirm_hash_changes=["src/calculator.py"],
    )
    assert "local edit" in target.read_text(encoding="utf-8")
    assert "+ 1" in target.read_text(encoding="utf-8")


def test_conflict_blocks_but_other_file_can_still_apply(store: SessionStore, profile, project_root: Path):
    session_id = make_session(
        store,
        profile,
        files=["src/calculator.py", "README.md"],
        answer=_answer_two_files(),
    )
    (project_root / "src" / "calculator.py").write_text("def add(a, b):\n    return a + b\n")
    status = dry_run(store, session_id, ["p0001", "p0002"])
    results = {item["patch_id"]: item for item in status["results"]}
    assert results["p0001"]["apply_status"] == "conflict"
    assert results["p0002"]["apply_status"] == "ok"
    with pytest.raises(AppError) as info:
        apply_session(store, session_id, ["p0001", "p0002"], confirm_hash_changes=["src/calculator.py"])
    assert info.value.code == "dry_run_failed"
    apply_session(store, session_id, ["p0002"])
    assert "+ 1" not in (project_root / "README.md").read_text(encoding="utf-8")


def test_new_file_apply_and_revert_delete(store: SessionStore, profile, project_root: Path):
    answer = """## 修改说明
Add file.
## Commit 建议
feat: add file
## 文件补丁
```diff
diff --git a/src/new_file.py b/src/new_file.py
new file mode 100644
--- /dev/null
+++ b/src/new_file.py
@@ -0,0 +1,2 @@
+one
+two
```
"""
    session_id = make_session(store, profile, answer=answer)
    apply_session(store, session_id, ["p0001"])
    target = project_root / "src" / "new_file.py"
    assert target.read_text(encoding="utf-8") == "one\ntwo\n"
    revert_session(store, session_id)
    assert not target.exists()


def test_revert_external_change_requires_confirmation(store: SessionStore, profile, project_root: Path):
    session_id = make_session(store, profile, answer=_answer_two_files())
    apply_session(store, session_id, ["p0001"])
    target = project_root / "src" / "calculator.py"
    target.write_text(target.read_text(encoding="utf-8") + "# external\n", encoding="utf-8")
    with pytest.raises(AppError) as info:
        revert_session(store, session_id)
    assert info.value.code == "revert_hash_changed"
    revert_session(store, session_id, confirm_hash_changes=True)
    assert "external" not in target.read_text(encoding="utf-8")


def test_patch_is_locked_after_apply(store: SessionStore, profile, project_root: Path):
    session_id = make_session(
        store,
        profile,
        files=["src/calculator.py", "README.md"],
        answer=_answer_two_files(),
    )
    apply_session(store, session_id, ["p0001"])
    with pytest.raises(AppError) as info:
        store.update_patch(session_id, "p0002", "anything")
    assert info.value.code == "session_locked"


def test_crlf_bom_preserved_after_apply(store: SessionStore, profile, project_root: Path):
    target = project_root / "src" / "calculator.py"
    target.write_bytes(b"\xef\xbb\xbfdef add(left, right):\r\n    return left + right\r\n")
    session_id = make_session(store, profile, answer=_answer_two_files())
    apply_session(store, session_id, ["p0001"])
    data = target.read_bytes()
    assert data.startswith(b"\xef\xbb\xbf")
    assert data.count(b"\r\n") == 2
    assert b"return left + right + 1\r\n" in data


def test_exported_patch_applies_in_clean_git_copy(
    store: SessionStore, profile, project_root: Path, tmp_path: Path
):
    session_id = make_session(store, profile, answer=_answer_two_files())
    patch_text = combined_patch(store, session_id)
    clean = tmp_path / "clean"
    shutil.copytree(project_root, clean, ignore=shutil.ignore_patterns(".git"))
    subprocess.run(["git", "init"], cwd=clean, check=True, capture_output=True)
    patch_file = tmp_path / "change.patch"
    patch_file.write_text(patch_text, encoding="utf-8")
    subprocess.run(["git", "apply", "--check", str(patch_file)], cwd=clean, check=True)
    subprocess.run(["git", "apply", str(patch_file)], cwd=clean, check=True)
    assert "+ 1" in (clean / "src" / "calculator.py").read_text(encoding="utf-8")
