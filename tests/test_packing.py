from __future__ import annotations

from pathlib import Path

import pytest

from patchbridge.errors import AppError
from patchbridge.fsutil import sha256_bytes
from patchbridge.packing import build_bundle, render_tree


def test_bundle_contains_metadata_tree_and_content(project_root: Path, profile):
    bundle = build_bundle(
        profile=profile,
        requirement="Add a guard.",
        selected_paths=["src/calculator.py", "README.md"],
        prompt_template="Project {{PROJECT_NAME}} has {{FILE_COUNT}} files.",
    )
    assert "# PATCHBRIDGE BUNDLE v1" in bundle.text
    assert "project: Demo" in bundle.text
    assert "src/" in bundle.tree
    assert "calculator.py" in bundle.tree
    assert "README.md" in bundle.text
    assert "===== PATCHBRIDGE FILE BEGIN: src/calculator.py =====" in bundle.text
    assert "def divide(left, right):" in bundle.text
    assert "Project Demo has 2 files." in bundle.text
    assert bundle.file_count == 2
    selected = {item["path"]: item for item in bundle.selection["files"]}
    assert selected["src/calculator.py"]["sha256"] == sha256_bytes(
        (project_root / "src" / "calculator.py").read_bytes()
    )


def test_marker_conflict_is_rejected(project_root: Path, profile):
    (project_root / "src" / "bad.py").write_text(
        "# ===== PATCHBRIDGE FILE BEGIN: bad.py\n", encoding="utf-8"
    )
    with pytest.raises(AppError) as info:
        build_bundle(
            profile=profile,
            requirement="x",
            selected_paths=["src/bad.py"],
            prompt_template="diff",
        )
    assert info.value.code == "bundle_marker_conflict"
    assert "src/bad.py" in info.value.details["conflicts"]


def test_content_is_not_reindented_and_final_newline(project_root: Path, profile):
    target = project_root / "src" / "no_newline.py"
    target.write_bytes(b"if True:\n    pass")
    bundle = build_bundle(
        profile=profile,
        requirement="x",
        selected_paths=["src/no_newline.py"],
        prompt_template="diff",
    )
    assert "if True:\n    pass\n===== PATCHBRIDGE FILE END: src/no_newline.py =====" in bundle.text
    entry = bundle.selection["files"][0]
    assert entry["final_newline"] is False


def test_crlf_and_bom_metadata(project_root: Path, profile):
    target = project_root / "src" / "bom.py"
    target.write_bytes(b"\xef\xbb\xbfa\r\nb\r\n")
    bundle = build_bundle(
        profile=profile,
        requirement="x",
        selected_paths=["src/bom.py"],
        prompt_template="diff",
    )
    entry = bundle.selection["files"][0]
    assert entry["bom"] is True
    assert entry["eol"] == "crlf"
    assert "a\r\nb\r\n" in bundle.text


def test_tree_rendering():
    tree = render_tree(["src/a.py", "src/b.py", "README.md"], "demo")
    assert "demo/" in tree
    assert "  src/" in tree
    assert "    a.py" in tree
    assert "  README.md" in tree
