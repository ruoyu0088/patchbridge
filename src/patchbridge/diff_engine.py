from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from .errors import AppError
from .fsutil import (
    Line,
    TextFileInfo,
    decode_text_file,
    encode_text_file,
    join_lines,
    normalize_rel_path,
    split_lines_keep_eol,
)

_HUNK_RE = re.compile(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@")
_HEADER_RE = re.compile(r"^(---|\+\+\+)\s+(.*)$")


@dataclass
class DiffLine:
    tag: str  # ' ', '+', '-', '\\'
    content: str
    no_newline: bool = False


@dataclass
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[DiffLine] = field(default_factory=list)

    @property
    def old_lines(self) -> list[DiffLine]:
        return [line for line in self.lines if line.tag in {" ", "-"}]

    @property
    def new_lines(self) -> list[DiffLine]:
        return [line for line in self.lines if line.tag in {" ", "+"}]

    @property
    def added(self) -> int:
        return sum(1 for line in self.lines if line.tag == "+")

    @property
    def removed(self) -> int:
        return sum(1 for line in self.lines if line.tag == "-")


@dataclass
class FilePatch:
    raw: str
    path: str = ""
    old_path: str = ""
    new_path: str = ""
    p_level: int = 1
    new_file: bool = False
    deleted: bool = False
    added: int = 0
    removed: int = 0
    hunks: list[Hunk] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    unsupported: str | None = None

    def canonical(self) -> str:
        return canonical_patch(self)


@dataclass
class ApplyResult:
    data: bytes
    text: str
    added: int
    removed: int
    warnings: list[str] = field(default_factory=list)
    new_file: bool = False


def _strip_path_token(value: str) -> str:
    value = value.strip()
    if "\t" in value:
        value = value.split("\t", 1)[0].strip()
    if value.startswith('"'):
        try:
            parts = shlex.split(value)
            if parts:
                return parts[0]
        except ValueError:
            pass
    return value


def _strip_prefixes(value: str) -> list[tuple[str, int]]:
    """Return (candidate, number_of_components_stripped)."""
    value = value.replace("\\", "/").strip()
    if value.startswith("./"):
        value = value[2:]
    result: list[tuple[str, int]] = [(value, 0)]
    parts = [p for p in value.split("/") if p not in ("", ".")]
    for count in range(1, min(6, len(parts))):
        result.append(("/".join(parts[count:]), count))
    return result


def _absolute_to_relative(value: str, root: Path, known: set[str]) -> tuple[str, int] | None:
    try:
        p = Path(value)
        if not p.is_absolute():
            return None
        try:
            rel = p.resolve().relative_to(root.resolve()).as_posix()
            return rel, 0
        except (OSError, ValueError):
            pass
    except OSError:
        pass
    # Fall back to suffix matching for paths copied from another machine.
    value = value.replace("\\", "/")
    best: str | None = None
    for known_path in known:
        if value.endswith("/" + known_path):
            if best is None or len(known_path) > len(best):
                best = known_path
    if best:
        return best, 0
    return None


def resolve_patch_path(
    value: str,
    *,
    root: Path,
    known_paths: Iterable[str] = (),
) -> tuple[str, int]:
    if not value or value == "/dev/null":
        raise AppError("invalid_path", "补丁路径为空")
    known = {normalize_rel_path(p) for p in known_paths}
    value = _strip_path_token(value)
    if value == "/dev/null":
        raise AppError("invalid_path", "补丁路径为 /dev/null")
    if any(part == ".." for part in value.replace("\\", "/").split("/")):
        raise AppError("path_traversal", f"补丁路径包含上级目录：{value}")
    absolute = _absolute_to_relative(value, root, known)
    if absolute:
        return absolute
    for candidate, stripped in _strip_prefixes(value):
        try:
            rel = normalize_rel_path(candidate)
        except AppError:
            continue
        if rel in known:
            return rel, stripped
    if not known:
        for candidate, stripped in _strip_prefixes(value):
            try:
                return normalize_rel_path(candidate), stripped
            except AppError:
                continue
    # Unknown path: strip one conventional a/ or b/ prefix.
    parts = [p for p in value.replace("\\", "/").split("/") if p not in ("", ".")]
    if parts and parts[0] in {"a", "b"} and len(parts) > 1:
        return normalize_rel_path("/".join(parts[1:])), 1
    for candidate, stripped in _strip_prefixes(value):
        try:
            return normalize_rel_path(candidate), stripped
        except AppError:
            continue
    raise AppError("invalid_path", f"无法归一化补丁路径：{value}")


def _parse_git_header(line: str) -> tuple[str, str] | None:
    rest = line[len("diff --git ") :].strip()
    try:
        parts = shlex.split(rest)
        if len(parts) == 2:
            return parts[0], parts[1]
    except ValueError:
        pass
    # Unquoted paths containing spaces: split at the last " b/" marker.
    match = re.match(r"^(a/.+)\s+(b/.+)$", rest)
    if match:
        return match.group(1), match.group(2)
    match = re.match(r"^(\S+)\s+(\S+)$", rest)
    if match:
        return match.group(1), match.group(2)
    return None


def _split_sections(lines: list[str]) -> list[tuple[int, int, str]]:
    starts: list[int] = []
    for index, line in enumerate(lines):
        if line.startswith("diff --git "):
            starts.append(index)
    if not starts:
        # Un-fenced diff with only ---/+++ headers.  A single code block can
        # contain several files in this style, so collect every header pair.
        for index, line in enumerate(lines):
            if (
                line.startswith("--- ")
                and index + 1 < len(lines)
                and lines[index + 1].startswith("+++ ")
            ):
                starts.append(index)
    if not starts:
        return []
    sections: list[tuple[int, int, str]] = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(lines)
        sections.append((start, end, "\n".join(lines[start:end])))
    return sections


def parse_unified_diff(
    text: str,
    *,
    root: Path,
    known_paths: Iterable[str] = (),
) -> list[FilePatch]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    sections = _split_sections(lines)
    if not sections:
        return []
    known = list(known_paths)
    patches: list[FilePatch] = []
    for _, _, raw_section in sections:
        patch = _parse_one_section(raw_section, root=root, known_paths=known)
        if patch is not None:
            patches.append(patch)
    return patches


def _parse_one_section(
    section: str,
    *,
    root: Path,
    known_paths: list[str],
) -> FilePatch | None:
    lines = section.split("\n")
    patch = FilePatch(raw=section)
    if not lines:
        return None
    index = 0
    if lines[0].startswith("diff --git "):
        pair = _parse_git_header(lines[0])
        if pair:
            patch.old_path, patch.new_path = pair
        index = 1
    old_header: str | None = None
    new_header: str | None = None
    while index < len(lines):
        line = lines[index]
        if line.startswith("new file mode"):
            patch.new_file = True
        elif line.startswith("deleted file mode"):
            patch.deleted = True
        elif line.startswith("rename from") or line.startswith("rename to"):
            patch.unsupported = "不支持重命名补丁"
        elif line.startswith("copy from") or line.startswith("copy to"):
            patch.unsupported = "不支持复制文件补丁"
        elif line.startswith("GIT binary patch") or line.startswith("Binary files"):
            patch.unsupported = "不支持二进制补丁"
        match = _HEADER_RE.match(line)
        if match:
            token = _strip_path_token(match.group(2))
            if match.group(1) == "---":
                old_header = token
            else:
                new_header = token
            index += 1
            continue
        if line.startswith("@@"):
            break
        index += 1

    if old_header == "/dev/null":
        patch.new_file = True
    if new_header == "/dev/null":
        patch.deleted = True

    candidates: list[tuple[str, int]] = []
    for header in (new_header, old_header):
        if header and header != "/dev/null":
            try:
                candidates.append(
                    resolve_patch_path(header, root=root, known_paths=known_paths)
                )
            except AppError:
                pass
    if candidates:
        # Prefer the new path when both exist.
        patch.path, patch.p_level = candidates[0]
    elif patch.new_path and patch.new_path != "/dev/null":
        try:
            patch.path, patch.p_level = resolve_patch_path(
                patch.new_path, root=root, known_paths=known_paths
            )
        except AppError:
            pass
    elif patch.old_path and patch.old_path != "/dev/null":
        try:
            patch.path, patch.p_level = resolve_patch_path(
                patch.old_path, root=root, known_paths=known_paths
            )
        except AppError:
            pass

    if patch.deleted:
        patch.unsupported = "不支持删除文件补丁"
    if not patch.path:
        patch.warnings.append("无法从补丁头确定文件路径")

    # Parse hunks.
    current: Hunk | None = None
    while index < len(lines):
        line = lines[index]
        match = _HUNK_RE.match(line)
        if match:
            if current is not None:
                patch.hunks.append(current)
            current = Hunk(
                old_start=int(match.group(1)),
                old_count=int(match.group(2) or 1),
                new_start=int(match.group(3)),
                new_count=int(match.group(4) or 1),
            )
            index += 1
            continue
        if current is None:
            index += 1
            continue
        if line.startswith("diff --git "):
            break
        if line.startswith("\\ No newline at end of file"):
            if current.lines:
                current.lines[-1].no_newline = True
            index += 1
            continue
        if not line:
            # A bare blank normally separates the diff from the next section.
            # A true empty context line is written as a single space.
            break
        tag = line[0]
        if tag not in {" ", "+", "-"}:
            # A heading or unrelated prose ends the current hunk.
            break
        current.lines.append(DiffLine(tag, line[1:]))
        index += 1
    if current is not None:
        patch.hunks.append(current)

    if not patch.hunks and not patch.unsupported:
        patch.unsupported = "补丁没有可解析的 hunk"

    patch.added = sum(hunk.added for hunk in patch.hunks)
    patch.removed = sum(hunk.removed for hunk in patch.hunks)
    for hunk in patch.hunks:
        actual_old = len(hunk.old_lines)
        actual_new = len(hunk.new_lines)
        if actual_old != hunk.old_count:
            patch.warnings.append(
                f"hunk 旧行数头写 {hunk.old_count}，实际 {actual_old}"
            )
        if actual_new != hunk.new_count:
            patch.warnings.append(
                f"hunk 新行数头写 {hunk.new_count}，实际 {actual_new}"
            )
    return patch


def canonical_patch(patch: FilePatch) -> str:
    if patch.unsupported:
        raise AppError(
            "unsupported_patch",
            patch.unsupported,
            status=422,
            details={"path": patch.path},
        )
    if not patch.path:
        raise AppError("invalid_patch", "补丁缺少文件路径")
    path = normalize_rel_path(patch.path)
    lines: list[str] = [f"diff --git a/{path} b/{path}"]
    if patch.new_file:
        lines.append("new file mode 100644")
        lines.append("--- /dev/null")
        lines.append(f"+++ b/{path}")
    else:
        lines.append(f"--- a/{path}")
        lines.append(f"+++ b/{path}")
    for hunk in patch.hunks:
        old_count = len(hunk.old_lines)
        new_count = len(hunk.new_lines)
        lines.append(
            f"@@ -{hunk.old_start},{old_count} +{hunk.new_start},{new_count} @@"
        )
        for line in hunk.lines:
            if line.tag == "\\":
                lines.append("\\ No newline at end of file")
            else:
                lines.append(line.tag + line.content)
                if line.no_newline:
                    lines.append("\\ No newline at end of file")
    return "\n".join(lines) + "\n"


@dataclass
class AlignResult:
    aligned: bool
    content: str | None = None
    changes: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    reason: str = ""


def _leading_ws(value: str) -> str:
    return value[: len(value) - len(value.lstrip(" \t"))]


def _ws_delta(patch_ws: str, file_ws: str) -> tuple[str, int, str] | None:
    """Return (add/remove, count, unit) or None when the difference is mixed.

    The common case is a whole hunk that was pasted two spaces to the left.
    We deliberately accept only a uniform run of spaces or tabs; mixed
    tab/space indentation needs manual work.
    """
    if patch_ws == file_ws:
        return ("", 0, "")
    if file_ws.startswith(patch_ws):
        extra = file_ws[len(patch_ws) :]
        if extra and all(char == " " for char in extra):
            return ("add", len(extra), " ")
        if extra and all(char == "\t" for char in extra):
            return ("add", len(extra), "\t")
    if patch_ws.startswith(file_ws):
        extra = patch_ws[len(file_ws) :]
        if extra and all(char == " " for char in extra):
            return ("remove", len(extra), " ")
        if extra and all(char == "\t" for char in extra):
            return ("remove", len(extra), "\t")
    return None


def _find_hunk_position(
    work: list[Line],
    hunk: Hunk,
) -> tuple[int, bool] | None:
    old_lines = hunk.old_lines
    if not old_lines:
        return None
    needle = [line.content.lstrip(" \t") for line in old_lines]
    hay = [line.content.lstrip(" \t") for line in work]

    def matches_at(position: int) -> bool:
        if position < 0 or position + len(needle) > len(hay):
            return False
        return hay[position : position + len(needle)] == needle

    expected = max(0, hunk.old_start - 1)
    if matches_at(expected):
        return expected, False
    positions = [
        index
        for index in range(0, len(hay) - len(needle) + 1)
        if hay[index : index + len(needle)] == needle
    ]
    if not positions:
        return None
    if len(positions) > 1:
        return None
    return positions[0], True


def align_patch_indentation(
    patch: FilePatch,
    current: bytes,
    *,
    align_added: bool = True,
) -> AlignResult:
    """Align pure indentation differences against the current file.

    Existing/context lines are matched by content after their leading
    whitespace.  A hunk is only changed when every old line requires the same
    uniform whitespace delta and every added line can receive that delta.
    The result is always re-dry-run; if it still fails, no content is returned.
    """
    if patch.unsupported:
        return AlignResult(False, reason=patch.unsupported or "不支持的补丁")
    if patch.new_file:
        return AlignResult(False, reason="新增文件没有原文件可对齐")
    try:
        info = decode_text_file(current)
    except Exception as exc:
        return AlignResult(False, reason=f"当前文件不是可编辑文本：{exc}")
    work = split_lines_keep_eol(info.text)
    changes: list[dict[str, Any]] = []
    warnings: list[str] = []
    changed_any = False

    for hunk_index, hunk in enumerate(patch.hunks):
        old_lines = hunk.old_lines
        if not old_lines:
            warnings.append(f"第 {hunk_index + 1} 个 hunk 没有上下文，无法推断缩进")
            continue
        located = _find_hunk_position(work, hunk)
        if located is None:
            return AlignResult(
                False,
                warnings=warnings,
                reason=(
                    f"第 {hunk_index + 1} 个 hunk 无法在原文中唯一定位，"
                    "可能存在内容差异或重复上下文"
                ),
            )
        position, shifted = located
        if shifted:
            warnings.append(
                f"第 {hunk_index + 1} 个 hunk 在原文中定位到第 {position + 1} 行"
            )

        delta: tuple[str, int, str] | None = None
        aligned_old: list[tuple[DiffLine, str]] = []
        for offset, line in enumerate(old_lines):
            file_line = work[position + offset]
            if not line.content.strip():
                # Empty/whitespace-only lines carry no indentation signal.
                aligned_old.append((line, file_line.content))
                continue
            patch_ws = _leading_ws(line.content)
            file_ws = _leading_ws(file_line.content)
            if line.content[len(patch_ws) :] != file_line.content[len(file_ws) :]:
                return AlignResult(
                    False,
                    warnings=warnings,
                    reason=(
                        f"第 {hunk_index + 1} 个 hunk 的第 {line.content!r} "
                        "并不只是缩进不同，无法自动对齐"
                    ),
                )
            line_delta = _ws_delta(patch_ws, file_ws)
            if line_delta is None:
                return AlignResult(
                    False,
                    warnings=warnings,
                    reason=(
                        f"第 {hunk_index + 1} 个 hunk 混合使用了空格和 Tab，"
                        "无法自动推断统一偏移"
                    ),
                )
            if delta is None:
                delta = line_delta
            elif delta != line_delta:
                return AlignResult(
                    False,
                    warnings=warnings,
                    reason=(
                        f"第 {hunk_index + 1} 个 hunk 内不同行需要不同的缩进偏移，"
                        "无法用统一偏移修复"
                    ),
                )
            aligned_old.append((line, file_line.content))

        if delta is None or delta[0] == "":
            continue
        mode, count, unit = delta
        added_lines = hunk.new_lines
        if align_added:
            for line in added_lines:
                if line.tag != "+" or not line.content.strip():
                    continue
                if mode == "add":
                    line.content = unit * count + line.content
                else:
                    prefix = unit * count
                    if not line.content.startswith(prefix):
                        return AlignResult(
                            False,
                            warnings=warnings,
                            reason=(
                                f"第 {hunk_index + 1} 个 hunk 的新增行缩进不足，"
                                "无法整体左移"
                            ),
                        )
                    line.content = line.content[len(prefix) :]
        for line, file_content in aligned_old:
            line.content = file_content
        changed_any = True
        changes.append(
            {
                "hunk_index": hunk_index,
                "hunk_header": (
                    f"@@ -{hunk.old_start},{hunk.old_count} "
                    f"+{hunk.new_start},{hunk.new_count} @@"
                ),
                "mode": mode,
                "count": count,
                "unit": "tab" if unit == "\t" else "space",
                "context_lines": len(old_lines),
                "added_lines": len([line for line in hunk.new_lines if line.tag == "+"]),
            }
        )

    if not changed_any:
        return AlignResult(
            False,
            warnings=warnings,
            reason="没有找到可自动对齐的纯缩进差异；补丁可能已经对齐，或包含内容差异",
        )

    content = canonical_patch(patch)
    try:
        apply_file_patch(patch, current, path=patch.path)
    except AppError as exc:
        return AlignResult(
            False,
            warnings=warnings,
            reason=f"对齐后仍无法应用：{exc.message}",
        )
    return AlignResult(True, content=content, changes=changes, warnings=warnings)


def _leading_indent(value: str) -> int:
    return len(value) - len(value.lstrip(" \t"))


def diagnose_hunk_mismatch(
    hunk: Hunk,
    hunk_index: int,
    work: list[Line],
    expected: int,
) -> dict[str, Any]:
    """Describe where a hunk stops matching the current file.

    The editor uses this to show the expected patch lines next to the real file
    lines.  It intentionally reports only the first mismatch: fixing indentation
    or a stale context line is usually an iterative process, and a concise
    pointer is more useful than a wall of red.
    """
    patch_rows: list[dict[str, Any]] = []
    old_line = hunk.old_start
    for line in hunk.lines:
        row: dict[str, Any] = {
            "tag": line.tag,
            "text": line.content,
            "no_newline": line.no_newline,
        }
        if line.tag in {" ", "-"}:
            row["old_line"] = old_line
            old_line += 1
        else:
            row["old_line"] = None
        patch_rows.append(row)

    old_rows = [
        (index, row)
        for index, row in enumerate(patch_rows)
        if row["tag"] in {" ", "-"}
    ]
    window_start = max(0, expected - 3)
    window_end = min(len(work), expected + max(12, len(old_rows) + 3))
    if expected >= len(work) and work:
        window_start = max(0, len(work) - 10)
        window_end = len(work)
    file_rows = [
        {"line": index + 1, "text": work[index].content}
        for index in range(window_start, window_end)
    ]

    first: dict[str, Any] | None = None
    hint = ""
    if expected >= len(work):
        hint = f"补丁期望从第 {hunk.old_start} 行开始，但当前文件只有 {len(work)} 行。"
    else:
        for offset, (patch_index, row) in enumerate(old_rows):
            file_index = expected + offset
            if file_index >= len(work):
                first = {
                    "kind": "eof",
                    "patch_row_index": patch_index,
                    "patch_line": row.get("old_line"),
                    "patch_text": row["text"],
                    "file_line": None,
                    "file_text": None,
                }
                hint = f"补丁上下文在第 {row.get('old_line')} 行之后超出了文件末尾。"
                break
            patch_text = row["text"]
            file_text = work[file_index].content
            if patch_text == file_text:
                continue
            patch_indent = _leading_indent(patch_text)
            file_indent = _leading_indent(file_text)
            kind = "indentation" if patch_text.strip() == file_text.strip() else "content"
            first = {
                "kind": kind,
                "patch_row_index": patch_index,
                "patch_line": row.get("old_line"),
                "patch_text": patch_text,
                "file_line": file_index + 1,
                "file_text": file_text,
                "patch_indent": patch_indent,
                "file_indent": file_indent,
            }
            if kind == "indentation":
                delta = file_indent - patch_indent
                direction = "少" if delta > 0 else "多"
                hint = (
                    f"补丁上下文第 {row.get('old_line')} 行（当前文件第 {file_index + 1} 行）"
                    f"的缩进不一致：补丁为 {patch_indent} 个前导空格，文件为 {file_indent} 个；"
                    f"这一行在补丁中{direction}了 {abs(delta)} 个空格。"
                )
            else:
                hint = (
                    f"补丁上下文第 {row.get('old_line')} 行与当前文件第 {file_index + 1} 行内容不同。"
                )
            break
    if first is None:
        hint = "补丁上下文没有找到可对齐的位置。"

    return {
        "hunk_index": hunk_index,
        "hunk_header": (
            f"@@ -{hunk.old_start},{hunk.old_count} "
            f"+{hunk.new_start},{hunk.new_count} @@"
        ),
        "old_start": hunk.old_start,
        "expected_line": expected + 1,
        "patch_rows": patch_rows,
        "file_rows": file_rows,
        "first_mismatch": first,
        "hint": hint,
    }


def _find_sequence(haystack: list[str], needle: list[str], expected: int) -> tuple[int, bool]:
    if not needle:
        return max(0, min(expected, len(haystack))), False
    if 0 <= expected <= len(haystack) - len(needle):
        if haystack[expected : expected + len(needle)] == needle:
            return expected, False
    matches = [
        i
        for i in range(0, len(haystack) - len(needle) + 1)
        if haystack[i : i + len(needle)] == needle
    ]
    if not matches:
        raise AppError(
            "patch_context_mismatch",
            "补丁上下文与当前文件不匹配",
            details={"expected_line": expected + 1},
        )
    matches.sort(key=lambda value: abs(value - expected))
    return matches[0], True


def apply_file_patch(
    patch: FilePatch,
    current: bytes | None,
    *,
    path: str | None = None,
) -> ApplyResult:
    if patch.unsupported:
        raise AppError("unsupported_patch", patch.unsupported, details={"path": patch.path})
    if patch.deleted:
        raise AppError("unsupported_patch", "不支持删除文件补丁", details={"path": patch.path})
    path = path or patch.path
    if patch.new_file:
        if current is not None:
            raise AppError(
                "new_file_exists",
                f"补丁要新增文件，但目标已存在：{path}",
                details={"path": path},
            )
        return _apply_new_file(patch)
    if current is None:
        raise AppError(
            "file_missing",
            f"目标文件不存在：{path}",
            details={"path": path},
        )
    try:
        info = decode_text_file(current)
    except Exception as exc:
        raise AppError(
            "unsupported_text",
            f"目标文件不是受支持的文本：{path}",
            details={"path": path, "reason": str(exc)},
        ) from exc
    work = split_lines_keep_eol(info.text)
    offset = 0
    warnings: list[str] = []
    for hunk_index, hunk in enumerate(patch.hunks):
        old_lines = hunk.old_lines
        new_lines = hunk.new_lines
        expected = max(0, hunk.old_start - 1 + offset)
        old_seq = [line.content for line in old_lines]
        try:
            index, shifted = _find_sequence(
                [line.content for line in work], old_seq, expected
            )
        except AppError as exc:
            if exc.code != "patch_context_mismatch":
                raise
            diagnostic = diagnose_hunk_mismatch(hunk, hunk_index, work, expected)
            raise AppError(
                "patch_context_mismatch",
                "补丁上下文与当前文件不匹配",
                details=diagnostic,
            ) from exc
        if shifted:
            warnings.append(
                f"hunk 在文件中偏移到第 {index + 1} 行应用（原期望第 {expected + 1} 行）"
            )
        touches_eof = index + len(old_lines) >= len(work)
        rebuilt: list[Line] = []
        old_index = 0
        for line in new_lines:
            if line.tag == " ":
                original_pos = index + old_index
                if 0 <= original_pos < len(work):
                    rebuilt.append(Line(line.content, work[original_pos].eol))
                else:
                    rebuilt.append(Line(line.content, info.eol))
                old_index += 1
            elif line.tag == "+":
                rebuilt.append(Line(line.content, info.eol))
            elif line.tag == "-":
                old_index += 1
        if touches_eof and hunk_index == len(patch.hunks) - 1 and rebuilt:
            last = new_lines[-1] if new_lines else None
            if last is not None and last.no_newline:
                rebuilt[-1] = Line(rebuilt[-1].content, "")
            else:
                rebuilt[-1] = Line(rebuilt[-1].content, rebuilt[-1].eol or info.eol)
        work[index : index + len(old_lines)] = rebuilt
        offset += len(new_lines) - len(old_lines)

    text = join_lines(work)
    data = encode_text_file(info, text)
    return ApplyResult(
        data=data,
        text=text,
        added=sum(hunk.added for hunk in patch.hunks),
        removed=sum(hunk.removed for hunk in patch.hunks),
        warnings=warnings,
        new_file=False,
    )


def _apply_new_file(patch: FilePatch) -> ApplyResult:
    contents: list[tuple[str, bool]] = []
    for hunk in patch.hunks:
        for line in hunk.new_lines:
            contents.append((line.content, line.no_newline))
    if not contents:
        text = ""
    else:
        final_newline = not contents[-1][1]
        text = "\n".join(content for content, _ in contents)
        if final_newline:
            text += "\n"
    data = text.encode("utf-8")
    return ApplyResult(
        data=data,
        text=text,
        added=sum(hunk.added for hunk in patch.hunks),
        removed=0,
        warnings=[],
        new_file=True,
    )


def summarize_patch(patch: FilePatch) -> dict[str, Any]:
    return {
        "path": patch.path,
        "old_path": patch.old_path,
        "new_path": patch.new_path,
        "p_level": patch.p_level,
        "new_file": patch.new_file,
        "deleted": patch.deleted,
        "added": patch.added,
        "removed": patch.removed,
        "warnings": list(patch.warnings),
        "unsupported": patch.unsupported,
    }


def find_file_patch(
    patches: list[FilePatch],
    path: str,
) -> FilePatch | None:
    normalized = normalize_rel_path(path)
    for patch in patches:
        if normalize_rel_path(patch.path) == normalized:
            return patch
    return None


def paths_overlap(a: str, b: str) -> bool:
    pa = PurePosixPath(normalize_rel_path(a))
    pb = PurePosixPath(normalize_rel_path(b))
    return pa == pb
