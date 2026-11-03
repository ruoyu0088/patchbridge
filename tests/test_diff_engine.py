from __future__ import annotations

from pathlib import Path

import pytest

from patchbridge.diff_engine import apply_file_patch, canonical_patch, parse_unified_diff
from patchbridge.errors import AppError


MODIFY = """diff --git a/src/calculator.py b/src/calculator.py
--- a/src/calculator.py
+++ b/src/calculator.py
@@ -1,2 +1,2 @@
 def add(left, right):
-    return left + right
+    return left + right + 1
"""


def parse_one(text: str, root: Path, known=("src/calculator.py",)):
    patches = parse_unified_diff(text, root=root, known_paths=list(known))
    assert len(patches) == 1
    return patches[0]


def test_modify_preserves_crlf_and_bom(project_root: Path):
    current = b"\xef\xbb\xbfdef add(left, right):\r\n    return left + right\r\n"
    patch = parse_one(MODIFY, project_root)
    result = apply_file_patch(patch, current)
    assert result.data.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" in result.data
    assert b"return left + right + 1" in result.data
    assert result.data.count(b"\n") == 2


def test_modify_no_final_newline(project_root: Path):
    text = """diff --git a/src/calculator.py b/src/calculator.py
--- a/src/calculator.py
+++ b/src/calculator.py
@@ -1,1 +1,1 @@
-def add(left, right):
+def add(a, b):
\\ No newline at end of file
"""
    patch = parse_one(text, project_root)
    result = apply_file_patch(patch, b"def add(left, right):")
    assert result.text == "def add(a, b):"
    assert not result.data.endswith(b"\n")


def test_new_file(project_root: Path):
    text = """diff --git a/src/new.py b/src/new.py
new file mode 100644
--- /dev/null
+++ b/src/new.py
@@ -0,0 +1,2 @@
+one
+two
"""
    patch = parse_one(text, project_root, known=("src/new.py",))
    result = apply_file_patch(patch, None)
    assert result.new_file is True
    assert result.data == b"one\ntwo\n"


def test_context_conflict(project_root: Path):
    patch = parse_one(MODIFY, project_root)
    with pytest.raises(AppError) as info:
        apply_file_patch(patch, b"def add(a, b):\n    return a + b\n")
    assert info.value.code == "patch_context_mismatch"


def test_offset_is_tolerated(project_root: Path):
    text = """diff --git a/src/calculator.py b/src/calculator.py
--- a/src/calculator.py
+++ b/src/calculator.py
@@ -1,1 +1,1 @@
-def add(left, right):
+def add(a, b):
"""
    patch = parse_one(text, project_root)
    result = apply_file_patch(patch, b"# header\n\ndef add(left, right):\n")
    assert "def add(a, b):" in result.text
    assert result.warnings


def test_canonical_patch_is_stable(project_root: Path):
    patch = parse_one(MODIFY, project_root)
    canonical = canonical_patch(patch)
    assert canonical.startswith("diff --git a/src/calculator.py b/src/calculator.py\n")
    assert "--- a/src/calculator.py" in canonical
    assert "+++ b/src/calculator.py" in canonical
    assert canonical.endswith("\n")
    reparsed = parse_one(canonical, project_root)
    assert reparsed.path == patch.path


def test_canonical_preserves_no_newline_marker(project_root: Path):
    text = """diff --git a/src/calculator.py b/src/calculator.py
--- a/src/calculator.py
+++ b/src/calculator.py
@@ -1,1 +1,1 @@
-def add(left, right):
+def add(a, b):
\\ No newline at end of file
"""
    patch = parse_one(text, project_root)
    canonical = canonical_patch(patch)
    assert "\\ No newline at end of file" in canonical
    reparsed = parse_one(canonical, project_root)
    result = apply_file_patch(reparsed, b"def add(left, right):")
    assert result.text == "def add(a, b):"


def test_hunk_count_mismatch_is_warned_not_fatal(project_root: Path):
    text = MODIFY.replace("@@ -1,2 +1,2 @@", "@@ -1,2 +1,3 @@")
    patch = parse_one(text, project_root)
    assert patch.warnings
    result = apply_file_patch(patch, b"def add(left, right):\n    return left + right\n")
    assert "return left + right + 1" in result.text
