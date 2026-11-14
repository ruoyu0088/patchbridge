from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from patchbridge.app import create_app
from patchbridge.config import AppConfig


def _client(tmp_path: Path) -> TestClient:
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "src" / "calculator.py").write_text(
        "def add(left, right):\n    return left + right\n", encoding="utf-8"
    )
    subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True)
    config = AppConfig(data_dir=tmp_path / "data", project_root=tmp_path)
    config.ensure_dirs()
    return TestClient(create_app(config))


def test_english_errors_and_prompt_selection(tmp_path: Path):
    client = _client(tmp_path)
    english = {"Accept-Language": "en-US,en;q=0.9"}

    meta = client.get("/api/meta", headers=english).json()["data"]
    assert meta["language"] == "en"
    assert meta["prompt_path"].endswith("default_en.md")

    missing = client.get("/api/sessions/missing", headers=english)
    assert missing.status_code == 404
    assert missing.json()["error"]["message"] == "Session does not exist: missing"

    settings = client.get("/api/settings", headers=english).json()["data"]
    assert settings["language"] == "en"
    assert settings["prompt_path_resolved"].endswith("default_en.md")
    assert settings["python_prompt_path_resolved"].endswith("python_en.md")


def test_english_export_labels(tmp_path: Path):
    client = _client(tmp_path)
    english = {"Accept-Language": "en"}
    profile = f"name: English Demo\nroot: {tmp_path / 'project'}\nmode: exclude\n\n[rules]\n"
    project_id = client.post("/api/projects", json={"raw": profile}).json()["data"]["project"]["id"]
    session_id = client.post(
        f"/api/projects/{project_id}/pack",
        json={"requirement": "Add one.", "files": ["src/calculator.py"], "mode": "diff"},
        headers=english,
    ).json()["data"]["session_id"]
    answer = """## Explanation
Add one.
## Commit suggestion
feat: add one
## File patches
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
    client.post(f"/api/sessions/{session_id}/answer", json={"answer": answer}, headers=english)
    exported = client.get(f"/api/sessions/{session_id}/export?format=md", headers=english)
    assert exported.status_code == 200
    text = exported.text
    assert "## Explanation" in text
    assert "## Commit suggestion" in text
    assert "## File patches" in text
    assert "Added 1 lines, removed 1 lines" in text
    assert "## 修改说明" not in text


def test_english_pack_uses_english_prompt(tmp_path: Path):
    client = _client(tmp_path)
    english = {"Accept-Language": "en"}
    profile = f"name: English Demo\nroot: {tmp_path / 'project'}\nmode: exclude\n\n[rules]\n"
    created = client.post("/api/projects", json={"raw": profile}).json()["data"]["project"]

    diff_pack = client.post(
        f"/api/projects/{created['id']}/pack",
        json={"requirement": "Add one.", "files": ["src/calculator.py"], "mode": "diff"},
        headers=english,
    ).json()["data"]
    assert diff_pack["mode"] == "diff"
    bundle = Path(diff_pack["bundle_path"]).read_text(encoding="utf-8")
    assert "You are a rigorous software engineer" in bundle
    assert "MODE: diff" in bundle

    python_pack = client.post(
        f"/api/projects/{created['id']}/pack",
        json={"requirement": "Add one.", "files": ["src/calculator.py"], "mode": "python"},
        headers=english,
    ).json()["data"]
    assert python_pack["mode"] == "python"
    python_bundle = Path(python_pack["bundle_path"]).read_text(encoding="utf-8")
    assert "MODE: python" in python_bundle
    assert "PatchBridge" in python_bundle


def test_english_profile_diagnostics(tmp_path: Path):
    client = _client(tmp_path)
    english = {"Accept-Language": "en"}
    profile = f"name: Broken Demo\nroot: {tmp_path / 'missing'}\nmode: exclude\n\n[rules]\n"
    created = client.post("/api/projects", json={"raw": profile}, headers=english).json()["data"]["project"]
    assert created["root_status"]["error"] == "Project root does not exist"
    listed = client.get("/api/projects", headers=english).json()["data"]["projects"][0]
    assert listed["root_status"]["error"] == "Project root does not exist"

