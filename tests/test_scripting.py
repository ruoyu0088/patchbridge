from __future__ import annotations

from pathlib import Path

from patchbridge.applying import apply_session, evaluate_patch
from patchbridge.config import AppConfig
from patchbridge.exporting import export_markdown
from patchbridge.packing import build_bundle
from patchbridge.parsing import parse_script_answer
from patchbridge.scripting import run_session_script
from patchbridge.sessions import SessionStore


def _session(store: SessionStore, profile, *, files=None, answer: str) -> str:
    selected = files or ["src/calculator.py"]
    bundle = build_bundle(
        profile=profile,
        requirement="python mode",
        selected_paths=selected,
        prompt_template="Return a Python script.\n",
        mode="python",
    )
    session_id = store.create_session(
        project_id=profile.id,
        project_name=profile.name,
        root=profile.root,
        profile=profile.to_snapshot(),
        requirement="python mode",
        bundle_text=bundle.text,
        selection=bundle.selection,
        mode="python",
    )
    store.save_answer(session_id, answer)
    return session_id


PY_ANSWER = """## 修改说明
在 add 的返回值后加注释。

## Commit 建议
feat: annotate add

## Python 补丁脚本
```python
text = read_text("src/calculator.py")
replace_text(
    "src/calculator.py",
    "    return left + right\\n",
    "    return left + right  # sum\\n",
    expected=1,
)
assert_count("src/calculator.py", "# sum", 1)
print("done")
```
"""


def test_python_bundle_header_and_mode(project_root: Path, profile, store: SessionStore):
    session_id = _session(store, profile, answer=PY_ANSWER)
    meta = store.meta(session_id)
    assert meta["mode"] == "python"
    assert "MODE: python" in (store.session_dir(session_id) / "bundle.txt").read_text(encoding="utf-8")
    parsed = store.get_parsed(session_id)
    assert parsed["mode"] == "python"
    assert "replace_text" in parsed["script"]


def test_script_runs_in_memory_and_generates_patch(
    project_root: Path, profile, store: SessionStore, config: AppConfig
):
    session_id = _session(store, profile, answer=PY_ANSWER)
    original = (project_root / "src" / "calculator.py").read_text(encoding="utf-8")
    result = run_session_script(store, config, session_id)
    assert result["report"]["status"] == "ok"
    assert result["report"]["stdout"].strip() == "done"
    assert len(result["patches"]) == 1
    # The real file must not change until the normal apply step.
    assert (project_root / "src" / "calculator.py").read_text(encoding="utf-8") == original

    patch_id = result["patches"][0]["id"]
    evaluation = evaluate_patch(store, session_id, result["patches"][0])
    assert evaluation.apply_status == "ok"
    apply_session(store, session_id, [patch_id])
    assert "# sum" in (project_root / "src" / "calculator.py").read_text(encoding="utf-8")


def test_export_markdown_contains_python_script(
    project_root: Path, profile, store: SessionStore, config: AppConfig
):
    session_id = _session(store, profile, answer=PY_ANSWER)
    run_session_script(store, config, session_id)
    markdown = export_markdown(store, session_id)
    assert "回答格式：python" in markdown
    assert "## Python 补丁脚本" in markdown
    assert "replace_text" in markdown


def test_expected_mismatch_applies_actual_and_warns(
    project_root: Path, profile, store: SessionStore, config: AppConfig
):
    answer = """## Python 补丁脚本
```python
replace_text("src/calculator.py", "return left + right", "return left + right  # x", expected=9)
```
"""
    session_id = _session(store, profile, answer=answer)
    result = run_session_script(store, config, session_id)
    assert result["report"]["status"] == "ok"
    assert any("预期 9" in warning for warning in result["report"]["warnings"])
    assert "return left + right  # x" in result["patches"][0]["content"]


def test_out_of_scope_path_is_partial_without_patch(
    project_root: Path, profile, store: SessionStore, config: AppConfig
):
    answer = """## Python 补丁脚本
```python
replace_text("README.md", "Demo", "Changed", expected=1)
```
"""
    session_id = _session(store, profile, answer=answer)
    result = run_session_script(store, config, session_id)
    assert result["report"]["status"] == "partial"
    assert result["patches"] == []


def test_bom_and_crlf_survive_script_patch(
    project_root: Path, profile, store: SessionStore, config: AppConfig
):
    target = project_root / "src" / "bom.txt"
    target.write_bytes(b"\xef\xbb\xbfone\r\ntwo\r\n")
    answer = """## Python 补丁脚本
```python
replace_text("src/bom.txt", "two", "TWO", expected=1)
```
"""
    session_id = _session(store, profile, files=["src/bom.txt"], answer=answer)
    result = run_session_script(store, config, session_id)
    assert result["report"]["status"] == "ok"
    apply_session(store, session_id, [result["patches"][0]["id"]])
    assert target.read_bytes() == b"\xef\xbb\xbfone\r\nTWO\r\n"


def test_sequential_edits_see_previous_changes(
    project_root: Path, profile, store: SessionStore, config: AppConfig
):
    answer = """## Python 补丁脚本
```python
replace_text("src/calculator.py", "return left + right", "return left + right  # first", expected=1)
replace_text("src/calculator.py", "# first", "# second", expected=1)
assert_count("src/calculator.py", "# second", 1)
```
"""
    session_id = _session(store, profile, answer=answer)
    result = run_session_script(store, config, session_id)
    assert result["report"]["status"] == "ok"
    assert "# second" in result["patches"][0]["content"]
    assert "# first" not in result["patches"][0]["content"]


def test_no_final_newline_is_preserved(
    project_root: Path, profile, store: SessionStore, config: AppConfig
):
    target = project_root / "src" / "noeol.txt"
    target.write_bytes(b"one\ntwo")
    answer = """## Python 补丁脚本
```python
replace_text("src/noeol.txt", "two", "TWO", expected=1)
```
"""
    session_id = _session(store, profile, files=["src/noeol.txt"], answer=answer)
    result = run_session_script(store, config, session_id)
    assert result["report"]["status"] == "ok"
    apply_session(store, session_id, [result["patches"][0]["id"]])
    assert target.read_bytes() == b"one\nTWO"


def test_create_file_patch_applies_and_reverts(
    project_root: Path, profile, store: SessionStore, config: AppConfig
):
    answer = """## Python 补丁脚本
```python
create_file("src/created.py", "value = 1\\n")
```
"""
    session_id = _session(store, profile, answer=answer)
    result = run_session_script(store, config, session_id)
    assert result["report"]["status"] == "ok"
    assert len(result["patches"]) == 1
    assert result["patches"][0]["new_file"] is True

    created = project_root / "src" / "created.py"
    assert not created.exists()
    apply_session(store, session_id, [result["patches"][0]["id"]])
    assert created.read_text(encoding="utf-8") == "value = 1\n"

    from patchbridge.applying import revert_session

    reverted = revert_session(store, session_id)
    assert reverted["deleted"] == ["src/created.py"]
    assert not created.exists()


def test_invalid_script_keeps_existing_patches(
    project_root: Path, profile, store: SessionStore, config: AppConfig
):
    session_id = _session(store, profile, answer=PY_ANSWER)
    run_session_script(store, config, session_id)
    before = store.get_patches(session_id)
    result = run_session_script(
        store,
        config,
        session_id,
        script_override="def broken(:\n",
    )
    assert result["report"]["status"] == "invalid"
    assert store.get_patches(session_id) == before


def test_parse_script_without_language_fence():
    answer = """## Python 补丁脚本
```
replace_text("a.py", "x", "y", expected=1)
```
"""
    parsed = parse_script_answer(answer, root=Path("."))
    assert "replace_text" in parsed.script
    assert any("语言标记" in warning for warning in parsed.warnings)


def test_script_steps_and_runtime_errors_carry_source_lines(
    project_root: Path, profile, store: SessionStore, config: AppConfig
):
    answer = """## Python 补丁脚本
```python
replace_text(
    "src/calculator.py",
    "    return left + right\\n",
    "    return left + right  # line link\\n",
    expected=1,
)
raise ValueError("boom")
```
"""
    session_id = _session(store, profile, answer=answer)
    result = run_session_script(store, config, session_id)
    report = result["report"]
    assert report["status"] == "partial"
    assert report["steps"], report
    assert report["steps"][0]["line"] >= 1
    assert report["error_line"] == 7, report
    assert "boom" in report["error"]


def test_syntax_error_reports_line(
    project_root: Path, profile, store: SessionStore, config: AppConfig
):
    session_id = _session(store, profile, answer=PY_ANSWER)
    result = run_session_script(
        store,
        config,
        session_id,
        script_override="x = 1\nif True print(x)\n",
    )
    assert result["report"]["status"] == "invalid"
    assert result["report"]["error_line"] == 2
