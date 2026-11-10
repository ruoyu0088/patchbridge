from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from patchbridge.applying import apply_session, dry_run, revert_session
from patchbridge.config import AppConfig
from patchbridge.mpatch import resolve_mpatch, run_mpatch_file
from patchbridge.profiles import Profile
from patchbridge.sessions import SessionStore
from tests.conftest import make_session


@pytest.fixture
def mpatch_settings(config: AppConfig) -> dict:
    settings = config.load_settings()
    exe = resolve_mpatch(settings)
    if exe is None:
        pytest.skip("mpatch is not installed")
    settings["mpatch_path"] = str(exe)
    settings["mpatch_fuzz_factor"] = 0.7
    settings["mpatch_timeout_seconds"] = 60
    config.save_settings(settings)
    return settings


def _git_init(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)


def test_run_mpatch_never_writes_real_worktree(
    tmp_path: Path, config: AppConfig, mpatch_settings: dict
) -> None:
    root = tmp_path / "copy-project"
    root.mkdir()
    target = root / "a.py"
    target.write_text("def f():\n    return 1\n", encoding="utf-8")
    _git_init(root)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
    original = target.read_bytes()
    patch = """--- a/a.py
+++ b/a.py
@@ -1,2 +1,3 @@
 def f():
-    return 1
+    return 2
+    # added
"""
    outcome = run_mpatch_file(
        patch,
        root=root,
        path="a.py",
        new_file=False,
        config=config,
        settings=mpatch_settings,
    )
    assert outcome.status == "ok", outcome.reason
    assert target.read_bytes() == original
    assert "+    return 2" in (outcome.final_patch or "")


def test_fuzzy_fallback_applies_derived_patch(
    store: SessionStore,
    profile: Profile,
    project_root: Path,
    mpatch_settings: dict,
) -> None:
    target = project_root / "src" / "calculator.py"
    target.write_text(
        "def add(left, right):\n"
        "    return left + right  # sum\n",
        encoding="utf-8",
    )
    answer = """## 修改说明
Add a comment after the return.

## Commit 建议
feat: annotate add

## 文件补丁
### src/calculator.py
```diff
--- a/src/calculator.py
+++ b/src/calculator.py
@@ -1,2 +1,3 @@
 def add(left, right):
     return left + right
+    # note
```
"""
    session_id = make_session(
        store,
        profile,
        files=["src/calculator.py"],
        answer=answer,
    )
    result = dry_run(store, session_id, ["p0001"])["results"][0]
    assert result["apply_status"] == "ok", result
    assert result["engine"] == "mpatch"
    assert "# note" in (result["final_patch"] or "")
    artifact = store.get_mpatch_artifact(session_id, "p0001")
    assert artifact is not None
    assert artifact["status"] == "ok"
    assert (store.session_dir(session_id) / "mpatch" / "p0001.patch").exists()

    applied = apply_session(store, session_id, ["p0001"])
    assert applied["apply_id"]
    assert "# note" in target.read_text(encoding="utf-8")
    events = store.events(session_id)
    assert any(event["type"] == "apply" for event in events)
    apply_event = next(event for event in events if event["type"] == "apply")
    assert apply_event["data"]["engines"]["p0001"] == "mpatch"
    # The user's original patch must remain untouched.
    assert store.get_patch(session_id, "p0001")["content"].count("# note") == 1

    reverted = revert_session(store, session_id)
    assert "src/calculator.py" in reverted["restored"]
    assert target.read_text(encoding="utf-8") == "def add(left, right):\n    return left + right  # sum\n"
    assert any(event["type"] == "revert" for event in store.events(session_id))


def test_fuzzy_failure_builds_repair_and_artifact(
    store: SessionStore,
    profile: Profile,
    project_root: Path,
    mpatch_settings: dict,
) -> None:
    target = project_root / "src" / "calculator.py"
    target.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    answer = """## 修改说明
Try a different block.

## Commit 建议
chore: try

## 文件补丁
### src/calculator.py
```diff
--- a/src/calculator.py
+++ b/src/calculator.py
@@ -1,3 +1,3 @@
 completely
-different
+changed
 content
```
"""
    session_id = make_session(
        store,
        profile,
        files=["src/calculator.py"],
        answer=answer,
    )
    result = dry_run(store, session_id, ["p0001"])["results"][0]
    assert result["apply_status"] == "conflict"
    assert result["repair"]
    assert "补丁修正请求" in result["repair"]
    assert "src/calculator.py" in result["repair"]
    assert result["mpatch"]["status"] == "failed"
    repair_file = store.session_dir(session_id) / "mpatch" / "p0001.repair.md"
    assert repair_file.exists()
    assert "different" in repair_file.read_text(encoding="utf-8")


def test_preview_does_not_persist_mpatch_artifact(
    store: SessionStore,
    profile: Profile,
    project_root: Path,
    mpatch_settings: dict,
) -> None:
    target = project_root / "src" / "calculator.py"
    target.write_text(
        "def add(left, right):\n"
        "    return left + right  # sum\n",
        encoding="utf-8",
    )
    answer = """## 文件补丁
```diff
--- a/src/calculator.py
+++ b/src/calculator.py
@@ -1,2 +1,3 @@
 def add(left, right):
     return left + right
+    # note
```
"""
    session_id = make_session(store, profile, files=["src/calculator.py"], answer=answer)
    result = dry_run(store, session_id, ["p0001"], persist=False)["results"][0]
    assert result["engine"] == "mpatch", result
    assert result["mpatch"]["status"] == "ok"
    assert not (store.session_dir(session_id) / "mpatch" / "p0001.json").exists()


def test_preview_of_archived_session_does_not_unarchive(
    store: SessionStore,
    profile: Profile,
    project_root: Path,
    mpatch_settings: dict,
) -> None:
    target = project_root / "src" / "calculator.py"
    target.write_text(
        "def add(left, right):\n"
        "    return left + right  # sum\n",
        encoding="utf-8",
    )
    answer = """## 文件补丁
```diff
--- a/src/calculator.py
+++ b/src/calculator.py
@@ -1,2 +1,3 @@
 def add(left, right):
     return left + right
+    # note
```
"""
    session_id = make_session(store, profile, files=["src/calculator.py"], answer=answer)
    store.archive(session_id)
    assert not store.session_dir(session_id).exists()
    assert store.zip_path(session_id).exists()

    result = dry_run(store, session_id, ["p0001"], persist=False)["results"][0]
    assert result["engine"] == "mpatch", result
    assert not store.session_dir(session_id).exists()
    assert store.zip_path(session_id).exists()


def test_mpatch_result_preserves_bom_and_crlf(
    store: SessionStore,
    profile: Profile,
    project_root: Path,
    mpatch_settings: dict,
) -> None:
    target = project_root / "src" / "calculator.py"
    target.write_bytes(
        b"\xef\xbb\xbfdef add(left, right):\r\n    return left + right  # sum\r\n"
    )
    answer = """## 文件补丁
```diff
--- a/src/calculator.py
+++ b/src/calculator.py
@@ -1,2 +1,3 @@
 def add(left, right):
     return left + right
+    # note
```
"""
    session_id = make_session(store, profile, files=["src/calculator.py"], answer=answer)
    result = dry_run(store, session_id, ["p0001"])["results"][0]
    assert result["engine"] == "mpatch", result
    apply_session(store, session_id, ["p0001"])
    data = target.read_bytes()
    assert data.startswith(b"\xef\xbb\xbf")
    assert data.count(b"\r\n") == 3
    assert b"# note\r\n" in data


def test_uniform_indentation_is_fixed_before_mpatch(
    store: SessionStore,
    profile: Profile,
    project_root: Path,
    mpatch_settings: dict,
) -> None:
    target = project_root / "src" / "calculator.py"
    target.write_text("def add(left, right):\n    return left + right\n", encoding="utf-8")
    answer = """## 文件补丁
```diff
--- a/src/calculator.py
+++ b/src/calculator.py
@@ -1,2 +1,3 @@
 def add(left, right):
   return left + right
+  # note
```
"""
    session_id = make_session(store, profile, files=["src/calculator.py"], answer=answer)
    result = dry_run(store, session_id, ["p0001"])["results"][0]
    assert result["apply_status"] == "ok", result
    assert result["engine"] == "strict+align"
