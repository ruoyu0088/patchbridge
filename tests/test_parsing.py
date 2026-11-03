from __future__ import annotations

from pathlib import Path

from patchbridge.parsing import parse_answer


NORMAL = """## 修改说明
Increase the return value.

## Commit 建议
feat: change add

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
"""


def test_normal_answer(project_root: Path):
    result = parse_answer(
        NORMAL,
        root=project_root,
        known_paths=["src/calculator.py"],
    )
    assert result.explanation == "Increase the return value."
    assert result.commit_message == "feat: change add"
    assert len(result.patches) == 1
    patch = result.patches[0]
    assert patch.path == "src/calculator.py"
    assert patch.p_level == 1
    assert patch.added == 1
    assert patch.removed == 1
    assert result.warnings == []


def test_malformed_answer_without_headings_or_language(project_root: Path):
    answer = """Here is the change.

```
diff --git a/src/calculator.py b/src/calculator.py
--- a/src/calculator.py
+++ b/src/calculator.py
@@ -1,2 +1,2 @@
 def add(left, right):
-    return left + right
+    return left + right + 1
```
"""
    result = parse_answer(answer, root=project_root, known_paths=["src/calculator.py"])
    assert len(result.patches) == 1
    assert result.patches[0].path == "src/calculator.py"
    assert any("语言标记" in warning for warning in result.warnings)
    assert any("commit" in warning.lower() for warning in result.warnings)


def test_missing_diff_header_uses_heading_path(project_root: Path):
    answer = """## 文件补丁
### src/calculator.py
```
@@ -1,2 +1,2 @@
 def add(left, right):
-    return left + right
+    return left + right + 1
```
"""
    result = parse_answer(answer, root=project_root, known_paths=["src/calculator.py"])
    assert len(result.patches) == 1
    assert result.patches[0].path == "src/calculator.py"
    assert any("补全" in warning for warning in result.warnings)


def test_absolute_path_and_prefixed_paths(project_root: Path):
    absolute = str(project_root / "src" / "calculator.py").replace("\\", "/")
    answer = f"""## 文件补丁
```diff
--- {absolute}
+++ {absolute}
@@ -1,2 +1,2 @@
 def add(left, right):
-    return left + right
+    return left + right + 1
```
"""
    result = parse_answer(answer, root=project_root, known_paths=["src/calculator.py"])
    assert len(result.patches) == 1
    assert result.patches[0].path == "src/calculator.py"


def test_multiple_patches_and_p_level(project_root: Path):
    answer = """## 文件补丁
### one
```diff
diff --git a/src/calculator.py b/src/calculator.py
--- x/y/z/src/calculator.py
+++ x/y/z/src/calculator.py
@@ -1,1 +1,1 @@
-def add(left, right):
+def add(a, b):
```
### two
```diff
diff --git a/README.md b/README.md
--- a/README.md
+++ b/README.md
@@ -1,1 +1,1 @@
-# Demo
+# Demo Project
```
"""
    result = parse_answer(
        answer,
        root=project_root,
        known_paths=["src/calculator.py", "README.md"],
    )
    assert [patch.path for patch in result.patches] == ["src/calculator.py", "README.md"]
    assert result.patches[0].p_level == 3  # x/y/z/ stripped


def test_commit_without_heading(project_root: Path):
    answer = """I changed the file.

commit: fix(core): handle empty values

```diff
diff --git a/src/calculator.py b/src/calculator.py
--- a/src/calculator.py
+++ b/src/calculator.py
@@ -1,1 +1,1 @@
-def add(left, right):
+def add(a, b):
```
"""
    result = parse_answer(answer, root=project_root, known_paths=["src/calculator.py"])
    assert result.commit_message == "fix(core): handle empty values"


def test_deletion_is_marked_unsupported(project_root: Path):
    answer = """## 文件补丁
```diff
diff --git a/README.md b/README.md
deleted file mode 100644
--- a/README.md
+++ /dev/null
@@ -1,1 +0,0 @@
-# Demo
```
"""
    result = parse_answer(answer, root=project_root, known_paths=["README.md"])
    assert len(result.patches) == 1
    assert result.patches[0].unsupported


def test_two_plain_header_patches_in_one_block(project_root: Path):
    answer = """## 文件补丁
```
--- a/src/calculator.py
+++ b/src/calculator.py
@@ -1,1 +1,1 @@
-def add(left, right):
+def add(a, b):
--- a/README.md
+++ b/README.md
@@ -1,1 +1,1 @@
-# Demo
+# Demo Project
```
"""
    result = parse_answer(
        answer,
        root=project_root,
        known_paths=["src/calculator.py", "README.md"],
    )
    assert [patch.path for patch in result.patches] == ["src/calculator.py", "README.md"]


def test_path_traversal_is_rejected(project_root: Path):
    answer = """## 文件补丁
```diff
diff --git a/../../etc/passwd b/../../etc/passwd
--- a/../../etc/passwd
+++ b/../../etc/passwd
@@ -1,1 +1,1 @@
-a
+b
```
"""
    result = parse_answer(answer, root=project_root, known_paths=[])
    assert result.patches == []
    assert result.warnings
