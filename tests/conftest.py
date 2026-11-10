from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from patchbridge.config import AppConfig
from patchbridge.packing import build_bundle
from patchbridge.profiles import Profile, save_profile, serialize_profile
from patchbridge.sessions import SessionStore


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    (root / "src" / "calculator.py").write_text(
        "def add(left, right):\n"
        "    return left + right\n"
        "\n"
        "def divide(left, right):\n"
        "    return left / right\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text("# Demo\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    return root


@pytest.fixture
def config(tmp_path: Path) -> AppConfig:
    cfg = AppConfig(data_dir=tmp_path / "data", project_root=tmp_path)
    cfg.ensure_dirs()
    return cfg


@pytest.fixture
def profile(config: AppConfig, project_root: Path) -> Profile:
    prof = serialize_profile(
        profile_id="demo",
        name="Demo",
        root=str(project_root),
        mode="exclude",
        rules=["*.log", "__pycache__/"],
    )
    save_profile(config.profiles_dir, prof)
    return prof


@pytest.fixture
def store(config: AppConfig) -> SessionStore:
    return SessionStore(config)


def make_session(
    store: SessionStore,
    profile: Profile,
    *,
    files: list[str] | None = None,
    requirement: str = "Make a change.",
    answer: str | None = None,
    mode: str = "diff",
) -> str:
    selected = files or ["src/calculator.py"]
    bundle = build_bundle(
        profile=profile,
        requirement=requirement,
        selected_paths=selected,
        prompt_template="Return a unified diff.\n",
        mode=mode,
    )
    session_id = store.create_session(
        project_id=profile.id,
        project_name=profile.name,
        root=profile.root,
        profile=profile.to_snapshot(),
        requirement=requirement,
        bundle_text=bundle.text,
        selection=bundle.selection,
        mode=mode,
    )
    if answer is not None:
        store.save_answer(session_id, answer)
    return session_id


@pytest.fixture
def answer_add_line() -> str:
    return """好的，下面是修改。

## 修改说明
在 divide 前增加一个空行并添加注释。

## Commit 建议
refactor(calculator): document divide

## 文件补丁
### src/calculator.py
```diff
diff --git a/src/calculator.py b/src/calculator.py
--- a/src/calculator.py
+++ b/src/calculator.py
@@ -2,1 +2,2 @@ def add(left, right):
     return left + right
+# explain divide
```
"""
