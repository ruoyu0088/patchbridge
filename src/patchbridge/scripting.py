from __future__ import annotations

import ast
import builtins
import difflib
import inspect
import io
import re
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import CodeType
from typing import Any

from .config import AppConfig
from .diff_engine import canonical_patch, parse_unified_diff
from .errors import AppError
from .i18n import tr
from .fsutil import (
    TextFileInfo,
    decode_text_file,
    encode_text_file,
    normalize_rel_path,
    read_bytes,
    safe_target,
)
from .parsing import ParseResult, ParsedPatch
from .profiles import Profile

SCRIPT_FILENAME = "<patchbridge-ai>"

ALLOWED_IMPORTS = {
    "re",
    "collections",
    "itertools",
    "functools",
    "math",
    "json",
    "textwrap",
    "string",
    "difflib",
    "typing",
    "dataclasses",
}

_ALLOWED_BUILTINS = {
    "abs",
    "all",
    "any",
    "ascii",
    "bin",
    "bool",
    "bytearray",
    "bytes",
    "callable",
    "chr",
    "classmethod",
    "complex",
    "dict",
    "dir",
    "divmod",
    "enumerate",
    "filter",
    "float",
    "format",
    "frozenset",
    "getattr",
    "hasattr",
    "hash",
    "hex",
    "id",
    "int",
    "isinstance",
    "issubclass",
    "iter",
    "len",
    "list",
    "map",
    "max",
    "min",
    "next",
    "object",
    "oct",
    "ord",
    "pow",
    "property",
    "range",
    "repr",
    "reversed",
    "round",
    "set",
    "slice",
    "sorted",
    "staticmethod",
    "str",
    "sum",
    "super",
    "tuple",
    "type",
    "zip",
    "__build_class__",
    "BaseException",
    "Exception",
    "ValueError",
    "TypeError",
    "KeyError",
    "IndexError",
    "RuntimeError",
    "StopIteration",
    "AttributeError",
    "ImportError",
    "AssertionError",
    "ZeroDivisionError",
}


class ScriptTimeout(RuntimeError):
    pass


class ScriptApiError(AppError):
    def __init__(self, message: str, *, code: str = "script_api_error") -> None:
        super().__init__(code, message, status=422)


@dataclass
class ScriptStep:
    index: int
    api: str
    path: str
    status: str
    message: str = ""
    expected: int | None = None
    matched: int | None = None
    line: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "api": self.api,
            "path": self.path,
            "status": self.status,
            "message": tr(self.message),
            "expected": self.expected,
            "matched": self.matched,
            "line": self.line,
        }


@dataclass
class WorkspaceFile:
    path: str
    info: TextFileInfo | None
    original_raw_text: str
    original_text: str
    current_text: str
    new_file: bool = False
    missing: bool = False

    @property
    def changed(self) -> bool:
        return self.current_text != self.original_text

    def final_text(self) -> str:
        text = self.current_text
        if self.info is not None and self.info.eol != "\n":
            text = text.replace("\n", self.info.eol)
        return text

    def final_bytes(self) -> bytes:
        if self.new_file or self.info is None:
            return self.current_text.encode("utf-8")
        return encode_text_file(self.info, self.final_text())


@dataclass
class ScriptResult:
    status: str
    reason: str = ""
    warnings: list[str] = field(default_factory=list)
    steps: list[ScriptStep] = field(default_factory=list)
    stdout: str = ""
    error: str = ""
    changes: list[dict[str, Any]] = field(default_factory=list)
    elapsed_ms: int = 0
    error_line: int = 0
    script: str = ""
    patches: list[ParsedPatch] = field(default_factory=list)

    def to_dict(self, *, include_script: bool = False) -> dict[str, Any]:
        data = {
            "status": self.status,
            "reason": tr(self.reason),
            "warnings": [tr(item) for item in self.warnings],
            "steps": [step.to_dict() for step in self.steps],
            "stdout": self.stdout,
            "error": tr(self.error),
            "error_line": self.error_line,
            "changes": list(self.changes),
            "elapsed_ms": self.elapsed_ms,
        }
        if include_script:
            data["script"] = self.script
        return data


class Workspace:
    def __init__(
        self,
        *,
        store: Any,
        session_id: str,
        profile: Profile,
        root: Path,
        selection: dict[str, Any],
    ) -> None:
        self.store = store
        self.session_id = session_id
        self.profile = profile
        self.root = root
        self.files: dict[str, WorkspaceFile] = {}
        self.warnings: list[str] = []
        self.steps: list[ScriptStep] = []
        self.discarded = False
        self._load(selection)

    def _load(self, selection: dict[str, Any]) -> None:
        for item in selection.get("files") or []:
            if not isinstance(item, dict):
                continue
            rel = str(item.get("path") or "").replace("\\", "/")
            if not rel:
                continue
            try:
                target = safe_target(self.root, rel)
                if not target.is_file():
                    self.files[rel] = WorkspaceFile(
                        path=rel,
                        info=None,
                        original_raw_text="",
                        original_text="",
                        current_text="",
                        missing=True,
                    )
                    self.warnings.append(f"{rel}: 文件已不存在，读取时会失败")
                    continue
                info = decode_text_file(read_bytes(target))
                self.files[rel] = WorkspaceFile(
                    path=rel,
                    info=info,
                    original_raw_text=info.text,
                    original_text=_normalize_newlines(info.text),
                    current_text=_normalize_newlines(info.text),
                )
            except Exception as exc:
                self.files[rel] = WorkspaceFile(
                    path=rel,
                    info=None,
                    original_raw_text="",
                    original_text="",
                    current_text="",
                    missing=True,
                )
                self.warnings.append(f"{rel}: 无法读取为文本（{exc}）")

    def _check(self) -> None:
        if self.discarded:
            raise ScriptTimeout("脚本已超时，工作区已丢弃")

    def _file(self, path: str) -> WorkspaceFile:
        self._check()
        rel = normalize_rel_path(path)
        item = self.files.get(rel)
        if item is None:
            raise ScriptApiError(
                f"文件未包含在本次会话中：{rel}。只能修改打包时选中的文件，或使用 create_file 新建文件。",
                code="script_file_not_selected",
            )
        if item.missing:
            raise ScriptApiError(f"文件不存在：{rel}", code="script_file_missing")
        return item

    @staticmethod
    def _caller_line() -> int:
        """Return the line in the AI script that called the current API."""
        frame = inspect.currentframe()
        while frame is not None:
            if frame.f_code.co_filename == SCRIPT_FILENAME:
                return int(frame.f_lineno)
            frame = frame.f_back
        return 0

    def _record(
        self,
        api: str,
        path: str,
        status: str,
        message: str = "",
        *,
        expected: int | None = None,
        matched: int | None = None,
    ) -> None:
        self.steps.append(
            ScriptStep(
                index=len(self.steps) + 1,
                api=api,
                path=path,
                status=status,
                message=message,
                expected=expected,
                matched=matched,
                line=self._caller_line(),
            )
        )
        if status == "warning":
            self.warnings.append(f"{path}: {message}")

    @staticmethod
    def _expected(expected: int) -> int:
        if isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:
            raise ScriptApiError("expected 必须是非负整数")
        return expected

    def _mismatch(
        self, api: str, path: str, expected: int, actual: int, message: str = ""
    ) -> None:
        if expected == actual:
            return
        detail = f"{api} 预期 {expected} 处，实际匹配 {actual} 处"
        if message:
            detail += f"；{message}"
        self._record(api, path, "warning", detail, expected=expected, matched=actual)

    # ------------------------------------------------------------ read/stat API
    def read_text(self, path: str) -> str:
        item = self._file(path)
        self._record("read_text", item.path, "ok")
        return item.current_text

    def count(self, path: str, needle: str) -> int:
        item = self._file(path)
        if not isinstance(needle, str) or not needle:
            raise ScriptApiError("count 的 needle 不能为空")
        value = item.current_text.count(needle)
        self._record("count", item.path, "ok", matched=value)
        return value

    # --------------------------------------------------------------- edit API
    def replace_text(
        self,
        path: str,
        old: str,
        new: str,
        expected: int,
        limit: int | None = None,
    ) -> int:
        item = self._file(path)
        expected = self._expected(expected)
        if not isinstance(old, str) or not old:
            raise ScriptApiError("replace_text 的 old 不能为空")
        if not isinstance(new, str):
            raise ScriptApiError("replace_text 的 new 必须是字符串")
        if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit < 0):
            raise ScriptApiError("limit 必须是非负整数或 None")
        actual = item.current_text.count(old)
        applied = actual if limit is None else min(actual, limit)
        self._mismatch("replace_text", item.path, expected, actual)
        if applied:
            item.current_text = item.current_text.replace(old, new, applied)
        if expected == actual:
            self._record(
                "replace_text", item.path, "ok", f"替换 {applied} 处", expected=expected, matched=actual
            )
        return applied

    def replace_regex(
        self,
        path: str,
        pattern: str,
        replacement: str,
        expected: int,
        limit: int | None = None,
        flags: str = "",
    ) -> int:
        item = self._file(path)
        expected = self._expected(expected)
        if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit < 0):
            raise ScriptApiError("limit 必须是非负整数或 None")
        flag_value = 0
        for char in flags or "":
            if char == "i":
                flag_value |= re.IGNORECASE
            elif char == "m":
                flag_value |= re.MULTILINE
            elif char == "s":
                flag_value |= re.DOTALL
            elif char == "x":
                flag_value |= re.VERBOSE
            else:
                raise ScriptApiError(f"不支持的正则 flag：{char}")
        try:
            compiled = re.compile(pattern, flag_value)
        except re.error as exc:
            raise ScriptApiError(f"正则表达式无效：{exc}") from exc
        actual = sum(1 for _ in compiled.finditer(item.current_text))
        applied = actual if limit is None else min(actual, limit)
        self._mismatch("replace_regex", item.path, expected, actual)
        if applied:
            item.current_text = compiled.sub(replacement, item.current_text, count=applied)
        if expected == actual:
            self._record(
                "replace_regex", item.path, "ok", f"替换 {applied} 处", expected=expected, matched=actual
            )
        return applied

    def insert_before(self, path: str, anchor: str, text: str, expected: int) -> int:
        return self._insert(path, anchor, text, expected, before=True)

    def insert_after(self, path: str, anchor: str, text: str, expected: int) -> int:
        return self._insert(path, anchor, text, expected, before=False)

    def _insert(self, path: str, anchor: str, text: str, expected: int, *, before: bool) -> int:
        item = self._file(path)
        expected = self._expected(expected)
        if not isinstance(anchor, str) or not anchor:
            raise ScriptApiError("插入操作的 anchor 不能为空")
        if not isinstance(text, str):
            raise ScriptApiError("插入的 text 必须是字符串")
        actual = item.current_text.count(anchor)
        self._mismatch("insert_before" if before else "insert_after", item.path, expected, actual)
        if actual:
            replacement = text + anchor if before else anchor + text
            item.current_text = item.current_text.replace(anchor, replacement)
        if expected == actual:
            self._record(
                "insert_before" if before else "insert_after",
                item.path,
                "ok",
                f"插入 {actual} 处",
                expected=expected,
                matched=actual,
            )
        return actual

    def replace_between(
        self,
        path: str,
        start: str,
        end: str,
        text: str,
        expected: int,
        include_start: bool = False,
        include_end: bool = False,
    ) -> int:
        item = self._file(path)
        expected = self._expected(expected)
        if not isinstance(start, str) or not start or not isinstance(end, str) or not end:
            raise ScriptApiError("replace_between 的 start/end 不能为空")
        if not isinstance(text, str):
            raise ScriptApiError("replace_between 的 text 必须是字符串")
        pairs: list[tuple[int, int]] = []
        cursor = 0
        while True:
            left = item.current_text.find(start, cursor)
            if left < 0:
                break
            right = item.current_text.find(end, left + len(start))
            if right < 0:
                break
            pairs.append((left, right))
            cursor = right + len(end)
        actual = len(pairs)
        self._mismatch("replace_between", item.path, expected, actual)
        if actual != 1:
            if actual > 1:
                self._record(
                    "replace_between",
                    item.path,
                    "warning",
                    f"锚点区间匹配 {actual} 处，位置不唯一，已跳过修改",
                    expected=expected,
                    matched=actual,
                )
            elif expected == 0:
                self._record("replace_between", item.path, "ok", "没有匹配区间", expected=expected, matched=0)
            return 0
        left, right = pairs[0]
        prefix_end = left if include_start else left + len(start)
        suffix_start = right + len(end) if include_end else right
        item.current_text = item.current_text[:prefix_end] + text + item.current_text[suffix_start:]
        self._record(
            "replace_between", item.path, "ok", "替换 1 个区间", expected=expected, matched=actual
        )
        return 1

    def create_file(self, path: str, text: str) -> None:
        self._check()
        rel = normalize_rel_path(path)
        if not isinstance(text, str):
            raise ScriptApiError("create_file 的 text 必须是字符串")
        if rel in self.files:
            raise ScriptApiError(f"文件已存在或已选中：{rel}", code="script_file_exists")
        if not self.profile.is_visible(rel):
            raise ScriptApiError(f"新文件不在 profile 可见范围内：{rel}", code="script_file_out_of_scope")
        target = safe_target(self.root, rel)
        if target.exists():
            raise ScriptApiError(f"文件已存在于磁盘：{rel}", code="script_file_exists")
        normalized = _normalize_newlines(text)
        self.files[rel] = WorkspaceFile(
            path=rel,
            info=None,
            original_raw_text="",
            original_text="",
            current_text=normalized,
            new_file=True,
        )
        self._record("create_file", rel, "ok", f"新建文件，{len(normalized)} 字符")

    # ----------------------------------------------------------------- asserts
    def assert_count(self, path: str, needle: str, expected: int) -> bool:
        item = self._file(path)
        expected = self._expected(expected)
        actual = item.current_text.count(needle)
        ok = actual == expected
        self._record(
            "assert_count",
            item.path,
            "ok" if ok else "warning",
            f"断言 count={expected}，实际 {actual}",
            expected=expected,
            matched=actual,
        )
        return ok

    def assert_contains(self, path: str, needle: str) -> bool:
        item = self._file(path)
        ok = needle in item.current_text
        self._record(
            "assert_contains",
            item.path,
            "ok" if ok else "warning",
            "包含目标文本" if ok else "未包含目标文本",
        )
        return ok

    def assert_not_contains(self, path: str, needle: str) -> bool:
        item = self._file(path)
        ok = needle not in item.current_text
        self._record(
            "assert_not_contains",
            item.path,
            "ok" if ok else "warning",
            "未包含目标文本" if ok else "仍然包含目标文本",
        )
        return ok

    def assert_python_syntax(self, path: str) -> bool:
        item = self._file(path)
        try:
            ast.parse(item.current_text)
        except SyntaxError as exc:
            self._record(
                "assert_python_syntax",
                item.path,
                "warning",
                f"Python 语法错误：第 {exc.lineno} 行：{exc.msg}",
            )
            return False
        self._record("assert_python_syntax", item.path, "ok", "语法检查通过")
        return True

    # --------------------------------------------------------------- execution
    def execute(self, code: CodeType, timeout_seconds: int) -> dict[str, Any]:
        output = io.StringIO()
        deadline = time.monotonic() + max(1, timeout_seconds)
        state: dict[str, Any] = {
            "status": "ok",
            "error": "",
            "stdout": "",
            "elapsed_ms": 0,
            "line": 0,
        }

        def _print(*args: Any, sep: str = " ", end: str = "\n", file: Any = None, flush: bool = False) -> None:
            if file is not None and file is not output:
                raise ScriptApiError("print 只允许输出到捕获缓冲区")
            output.write(sep.join(str(arg) for arg in args) + end)

        allowed = {name: getattr(builtins, name) for name in _ALLOWED_BUILTINS if hasattr(builtins, name)}
        allowed["print"] = _print

        def _restricted_import(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0) -> Any:
            root = name.split(".", 1)[0]
            if root not in ALLOWED_IMPORTS:
                raise ImportError(f"import {name} 不在允许列表中")
            return __import__(name, globals, locals, fromlist, level)

        allowed["__import__"] = _restricted_import
        env: dict[str, Any] = {
            "__name__": "__patchbridge__",
            "__builtins__": allowed,
        }
        for name in (
            "read_text",
            "count",
            "replace_text",
            "replace_regex",
            "insert_before",
            "insert_after",
            "replace_between",
            "create_file",
            "assert_count",
            "assert_contains",
            "assert_not_contains",
            "assert_python_syntax",
        ):
            env[name] = getattr(self, name)

        def trace(frame: Any, event: str, arg: Any) -> Any:
            if frame.f_code.co_filename == SCRIPT_FILENAME:
                state["line"] = int(frame.f_lineno)
            if time.monotonic() > deadline:
                raise ScriptTimeout("脚本执行超时")
            return trace

        def target() -> None:
            started = time.monotonic()
            try:
                sys.settrace(trace)
                exec(code, env, env)
            except ScriptTimeout:
                state["status"] = "timeout"
                state["error"] = "脚本执行超时，已丢弃本次运行的工作区"
            except BaseException as exc:
                state["status"] = "partial"
                state["error"] = f"{type(exc).__name__}: {exc}"
                state["line"] = _exception_line(exc)
                state["traceback"] = traceback.format_exc(limit=8)
            finally:
                sys.settrace(None)
                state["elapsed_ms"] = int((time.monotonic() - started) * 1000)
                state["stdout"] = output.getvalue()

        thread = threading.Thread(target=target, name="patchbridge-script", daemon=True)
        thread.start()
        thread.join(max(0.1, timeout_seconds) + 0.5)
        if thread.is_alive():
            self.discarded = True
            state["status"] = "timeout"
            state["error"] = "脚本执行超时，已丢弃本次运行的工作区"
        if state["status"] == "timeout":
            self.discarded = True
        return state


def _exception_line(exc: BaseException) -> int:
    line = 0
    tb = exc.__traceback__
    while tb is not None:
        if tb.tb_frame.f_code.co_filename == SCRIPT_FILENAME:
            line = int(tb.tb_lineno)
        tb = tb.tb_next
    return line


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _profile_from_meta(meta: dict[str, Any]) -> Profile:
    snapshot = meta.get("profile") or {}
    return Profile(
        id=str(snapshot.get("id") or ""),
        name=str(snapshot.get("name") or ""),
        root=str(snapshot.get("root") or meta.get("root") or ""),
        mode=str(snapshot.get("mode") or "exclude"),
        rules=list(snapshot.get("rules") or []),
    )


def _unified_diff(path: str, old: str, new: str, *, new_file: bool) -> str:
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    fromfile = "/dev/null" if new_file else f"a/{path}"
    tofile = f"b/{path}"
    raw = list(
        difflib.unified_diff(
            [] if new_file else old_lines,
            new_lines,
            fromfile=fromfile,
            tofile=tofile,
            lineterm="",
        )
    )
    output: list[str] = []
    for line in raw:
        output.append(line if line.endswith("\n") else line + "\n")

    def insert_marker(after_tags: set[str]) -> None:
        index = -1
        for pos, line in enumerate(output):
            if line[:1] in after_tags:
                index = pos
        if index >= 0:
            output.insert(index + 1, "\\ No newline at end of file\n")

    if not new.endswith("\n"):
        insert_marker({" ", "+"})
    if not new_file and not old.endswith("\n"):
        insert_marker({" ", "-"})
    return "".join(output)


def generate_patches(
    *,
    workspace: Workspace,
    root: Path,
    known_paths: list[str],
) -> tuple[list[ParsedPatch], list[str]]:
    warnings: list[str] = []
    patches: list[ParsedPatch] = []
    for path in sorted(workspace.files):
        item = workspace.files[path]
        if not item.changed:
            continue
        try:
            diff_text = _unified_diff(
                path, item.original_raw_text, item.final_text(), new_file=item.new_file
            )
            parsed = parse_unified_diff(diff_text, root=root, known_paths=known_paths)
            if len(parsed) != 1:
                warnings.append(f"{path}: 生成的补丁无法解析为单文件补丁")
                continue
            file_patch = parsed[0]
            file_patch.path = path
            file_patch.p_level = 1
            if item.new_file:
                file_patch.new_file = True
            raw = canonical_patch(file_patch)
            patches.append(
                ParsedPatch(
                    id=f"p{len(patches) + 1:04d}",
                    raw=raw,
                    path=path,
                    added=file_patch.added,
                    removed=file_patch.removed,
                    new_file=file_patch.new_file,
                    p_level=1,
                    warnings=list(file_patch.warnings),
                )
            )
        except Exception as exc:
            warnings.append(f"{path}: 生成补丁失败（{exc}）")
    return patches, warnings


def run_session_script(
    store: Any,
    config: AppConfig,
    session_id: str,
    *,
    script_override: str | None = None,
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    if store.has_any_apply(session_id):
        raise AppError("session_locked", "会话已应用补丁，不能再执行脚本；请重新载入", status=409)
    meta = store.meta(session_id)
    mode = str(meta.get("mode") or "diff")
    if mode != "python":
        raise AppError("wrong_mode", "该会话不是 Python 模式", status=409)
    parsed = store.get_parsed(session_id) or {}
    script = (script_override if script_override is not None else parsed.get("script") or "").strip()
    if not script:
        raise AppError("script_empty", "没有可执行的 Python 脚本", status=422)
    selection = store.read_json(session_id, "selection.json") or {}
    profile = _profile_from_meta(meta)
    root = Path(str(meta.get("root") or profile.root))
    settings = config.load_settings()
    timeout = int(timeout_seconds or settings.get("script_timeout_seconds") or 20)
    started = time.monotonic()

    result = ScriptResult(status="ok", script=script)
    try:
        code = compile(script, SCRIPT_FILENAME, "exec")
    except SyntaxError as exc:
        result.status = "invalid"
        result.error_line = int(exc.lineno or 0)
        result.reason = f"脚本语法错误：第 {exc.lineno} 行：{exc.msg}"
        report = result.to_dict()
        store.save_script_report(session_id, script, report)
        return {"report": report, "parsed": store.get_parsed(session_id), "patches": store.get_patches(session_id)}

    workspace = Workspace(
        store=store,
        session_id=session_id,
        profile=profile,
        root=root,
        selection=selection,
    )
    state = workspace.execute(code, timeout)
    result.elapsed_ms = int((time.monotonic() - started) * 1000)
    result.stdout = str(state.get("stdout") or "")[: int(settings.get("script_max_output_chars") or 20000)]
    result.steps = workspace.steps
    result.warnings = list(dict.fromkeys(workspace.warnings))
    result.status = str(state.get("status") or "ok")
    result.error = str(state.get("error") or "")
    result.error_line = int(state.get("line") or 0)
    if result.status == "timeout":
        result.reason = result.error
        report = result.to_dict()
        store.save_script_report(session_id, script, report)
        return {"report": report, "parsed": store.get_parsed(session_id), "patches": store.get_patches(session_id)}

    patches, warnings = generate_patches(
        workspace=workspace,
        root=root,
        known_paths=[item.get("path") for item in selection.get("files", []) if item.get("path")],
    )
    result.patches = patches
    result.warnings = list(dict.fromkeys(result.warnings + warnings))
    if result.status == "partial":
        result.reason = result.error
    elif not patches:
        result.reason = "脚本执行完成，但没有文件发生变化"
    result.changes = [
        {
            "path": patch.path,
            "added": patch.added,
            "removed": patch.removed,
            "new_file": patch.new_file,
        }
        for patch in patches
    ]
    report = result.to_dict()
    parse_result = ParseResult(
        mode="python",
        explanation=str(parsed.get("explanation") or result.reason),
        commit_message=str(parsed.get("commit_message") or ""),
        warnings=list(result.warnings),
        patches=patches,
        script=script,
        script_result=report,
    )
    if result.status == "ok" or result.status == "partial":
        store.save_script_result(session_id, parse_result, report)
    else:
        store.save_script_report(session_id, script, report)
    return {
        "report": report,
        "parsed": store.get_parsed(session_id),
        "patches": store.get_patches(session_id),
    }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
