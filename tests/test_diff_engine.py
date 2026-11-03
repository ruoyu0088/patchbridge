from __future__ import annotations

from pathlib import Path

import pytest

from patchbridge.diff_engine import (
    align_patch_indentation,
    apply_file_patch,
    canonical_patch,
    parse_unified_diff,
)
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


def test_indentation_mismatch_has_diagnostic(project_root: Path):
    text = """diff --git a/src/calculator.py b/src/calculator.py
--- a/src/calculator.py
+++ b/src/calculator.py
@@ -4,2 +4,2 @@
 def divide(left, right):
-    return left / right
+    return left / right + 1
"""
    patch = parse_one(text, project_root)
    with pytest.raises(AppError) as info:
        apply_file_patch(
            patch,
            b"def add(left, right):\n    return left + right\n\n  def divide(left, right):\n  return left / right\n",
        )
    diagnostic = info.value.details
    assert diagnostic["first_mismatch"]["kind"] == "indentation"
    assert diagnostic["first_mismatch"]["patch_indent"] == 0
    assert diagnostic["first_mismatch"]["file_indent"] == 2
    assert "缩进" in diagnostic["hint"]


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


def test_align_indentation_shifts_context_and_added_lines(project_root: Path):
    current = (
        b"  function foo() {\n"
        b"    const value = 1;\n"
        b"    return value;\n"
        b"  }\n"
    )
    text = """diff --git a/src/foo.js b/src/foo.js
--- a/src/foo.js
+++ b/src/foo.js
@@ -2,2 +2,2 @@
   const value = 1;
-  return value;
+  return value + 1;
"""
    patch = parse_one(text, project_root, known=("src/foo.js",))
    result = align_patch_indentation(patch, current)
    assert result.aligned is True, result.reason
    assert result.changes[0]["count"] == 2
    aligned_patch = parse_one(result.content, project_root, known=("src/foo.js",))
    applied = apply_file_patch(aligned_patch, current)
    assert "    return value + 1;" in applied.text


def test_align_indentation_ignores_blank_context_lines(project_root: Path):
    current = b"  function foo() {\n\n    return 1;\n  }\n"
    text = """diff --git a/src/foo.js b/src/foo.js
--- a/src/foo.js
+++ b/src/foo.js
@@ -1,3 +1,3 @@
 function foo() {
 
-  return 1;
+  return 2;
"""
    patch = parse_one(text, project_root, known=("src/foo.js",))
    result = align_patch_indentation(patch, current)
    assert result.aligned is True, result.reason
    assert result.changes[0]["count"] == 2


def test_align_indentation_can_leave_added_lines(project_root: Path):
    current = b"  function foo() {\n    const value = 1;\n  }\n"
    text = """diff --git a/src/foo.js b/src/foo.js
--- a/src/foo.js
+++ b/src/foo.js
@@ -2,1 +2,2 @@
   const value = 1;
+  return value;
"""
    patch = parse_one(text, project_root, known=("src/foo.js",))
    result = align_patch_indentation(patch, current, align_added=False)
    assert result.aligned is True, result.reason
    aligned_patch = parse_one(result.content, project_root, known=("src/foo.js",))
    applied = apply_file_patch(aligned_patch, current)
    assert "  return value;" in applied.text
    assert "    return value;" not in applied.text


def test_align_indentation_refuses_content_difference(project_root: Path):
    current = b"  function foo() {\n    const value = 1;\n    return value;\n  }\n"
    text = """diff --git a/src/foo.js b/src/foo.js
--- a/src/foo.js
+++ b/src/foo.js
@@ -2,2 +2,2 @@
   const value = 1;
-  return other;
+  return other + 1;
"""
    patch = parse_one(text, project_root, known=("src/foo.js",))
    result = align_patch_indentation(patch, current)
    assert result.aligned is False
    assert "无法" in result.reason


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
