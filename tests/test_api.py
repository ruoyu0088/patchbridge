from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from patchbridge.app import create_app
from patchbridge.config import AppConfig


ANSWER = """## 修改说明
Add one.
## Commit 建议
feat: add one
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


def _client(tmp_path: Path) -> tuple[TestClient, Path]:
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "src" / "calculator.py").write_text(
        "def add(left, right):\n    return left + right\n", encoding="utf-8"
    )
    subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True)
    config = AppConfig(data_dir=tmp_path / "data", project_root=tmp_path)
    config.ensure_dirs()
    return TestClient(create_app(config)), project


def test_full_api_flow(tmp_path: Path):
    client, project = _client(tmp_path)
    assert client.get("/api/health").json()["ok"] is True

    profile = f"name: Demo\nroot: {project}\nmode: exclude\n\n[rules]\n"
    response = client.post("/api/projects", json={"raw": profile})
    assert response.status_code == 200
    project_id = response.json()["data"]["project"]["id"]

    tree = client.get(f"/api/projects/{project_id}/tree").json()["data"]
    assert tree["files"][0]["path"] == "src/calculator.py"

    packed = client.post(
        f"/api/projects/{project_id}/pack",
        json={"requirement": "Add one.", "files": ["src/calculator.py"]},
    )
    assert packed.status_code == 200
    session_id = packed.json()["data"]["session_id"]
    assert packed.json()["data"]["bundle_path"].endswith("bundle.txt")

    parsed = client.post(f"/api/sessions/{session_id}/answer", json={"answer": ANSWER})
    assert parsed.status_code == 200
    assert len(parsed.json()["data"]["patches"]) == 1

    dry = client.post(f"/api/sessions/{session_id}/dry-run", json={"patch_ids": ["p0001"]})
    assert dry.status_code == 200
    assert dry.json()["data"]["ok"] is True

    applied = client.post(
        f"/api/sessions/{session_id}/apply",
        json={"patch_ids": ["p0001"], "confirm_hash_changes": []},
    )
    assert applied.status_code == 200
    assert "+ 1" in (project / "src" / "calculator.py").read_text(encoding="utf-8")

    exported = client.get(f"/api/sessions/{session_id}/export?format=patch")
    assert exported.status_code == 200
    assert exported.text.startswith("diff --git a/src/calculator.py")

    archive = client.post(f"/api/sessions/{session_id}/archive", json={})
    assert archive.status_code == 409
    assert archive.json()["error"]["code"] == "archive_active_apply"
    archive = client.post(
        f"/api/sessions/{session_id}/archive",
        json={"confirm_active_apply": True},
    )
    assert archive.status_code == 200

    details = client.get(f"/api/sessions/{session_id}").json()["data"]
    assert details["archived"] is True
    assert details["status"] == "applied"

    reloaded = client.post(f"/api/sessions/{session_id}/reload")
    assert reloaded.status_code == 200
    assert reloaded.json()["data"]["validation"] is not None

    missing = client.get("/api/sessions/not-a-session")
    assert missing.status_code == 404
    assert missing.json()["ok"] is False
    assert missing.json()["error"]["code"] == "session_not_found"


def test_align_indent_endpoint_returns_preview(tmp_path: Path):
    client, project = _client(tmp_path)
    (project / "src" / "foo.js").write_text(
        "  function foo() {\n"
        "    const value = 1;\n"
        "    return value;\n"
        "  }\n",
        encoding="utf-8",
    )
    profile = f"name: Demo\nroot: {project}\nmode: exclude\n\n[rules]\n"
    project_id = client.post("/api/projects", json={"raw": profile}).json()["data"]["project"]["id"]
    packed = client.post(
        f"/api/projects/{project_id}/pack",
        json={"requirement": "add one", "files": ["src/foo.js"]},
    ).json()["data"]
    session_id = packed["session_id"]
    answer = """## 文件补丁
```diff
diff --git a/src/foo.js b/src/foo.js
--- a/src/foo.js
+++ b/src/foo.js
@@ -2,2 +2,2 @@
   const value = 1;
-  return value;
+  return value + 1;
```
"""
    client.post(f"/api/sessions/{session_id}/answer", json={"answer": answer})
    aligned = client.post(
        f"/api/sessions/{session_id}/patches/p0001/align-indent",
        json={"align_added": True},
    )
    assert aligned.status_code == 200
    data = aligned.json()["data"]
    assert data["aligned"] is True
    assert data["content"]
    assert data["changes"][0]["count"] == 2
    client.put(
        f"/api/sessions/{session_id}/patches/p0001",
        json={"content": data["content"]},
    )
    dry = client.post(f"/api/sessions/{session_id}/dry-run", json={"patch_ids": ["p0001"]})
    assert dry.status_code == 200
    assert dry.json()["data"]["ok"] is True


def test_pack_marker_conflict_returns_structured_error(tmp_path: Path):
    client, project = _client(tmp_path)
    (project / "src" / "bad.py").write_text(
        "===== PATCHBRIDGE FILE BEGIN: bad.py\n", encoding="utf-8"
    )
    profile = f"name: Demo\nroot: {project}\nmode: exclude\n\n[rules]\n"
    project_id = client.post("/api/projects", json={"raw": profile}).json()["data"]["project"]["id"]
    response = client.post(
        f"/api/projects/{project_id}/pack",
        json={"requirement": "x", "files": ["src/bad.py"]},
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "bundle_marker_conflict"
    assert "src/bad.py" in error["details"]["conflicts"]


def test_tree_lists_binary_file_paths(tmp_path: Path):
    client, project = _client(tmp_path)
    (project / "src" / "blob.bin").write_bytes(b"\x00\x01\x02")
    profile = f"name: Demo\nroot: {project}\nmode: exclude\n\n[rules]\n"
    project_id = client.post("/api/projects", json={"raw": profile}).json()["data"]["project"]["id"]
    tree = client.get(f"/api/projects/{project_id}/tree")
    assert tree.status_code == 200
    data = tree.json()["data"]
    assert data["skipped_files"]["binary"] == ["src/blob.bin"]
    assert data["summary"]["skipped"]["binary"] == 1


def test_unavailable_project_blocks_tree_and_pack(tmp_path: Path):
    client, _ = _client(tmp_path)
    missing = tmp_path / "does-not-exist"
    profile = f"name: Missing\nroot: {missing}\nmode: exclude\n\n[rules]\n"
    created = client.post("/api/projects", json={"raw": profile})
    assert created.status_code == 200
    project = created.json()["data"]["project"]
    assert project["root_status"]["accessible"] is False
    project_id = project["id"]
    tree = client.get(f"/api/projects/{project_id}/tree")
    assert tree.status_code == 409
    assert tree.json()["error"]["code"] == "project_unavailable"
    packed = client.post(
        f"/api/projects/{project_id}/pack",
        json={"requirement": "x", "files": ["a.py"]},
    )
    assert packed.status_code == 409


def test_index_rebuild_endpoint(tmp_path: Path):
    client, _ = _client(tmp_path)
    assert client.get("/api/index/status").json()["ok"] is True
    result = client.post("/api/index/rebuild")
    assert result.status_code == 200
    assert result.json()["data"]["status"]["stale"] is False
