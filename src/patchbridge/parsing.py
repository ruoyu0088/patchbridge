from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .diff_engine import FilePatch, canonical_patch, parse_unified_diff
from .errors import AppError
from .i18n import tr
from .fsutil import normalize_rel_path
from .diff_engine import resolve_patch_path

_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE_RE = re.compile(r"^\s*```([^\s`]*)\s*$")
_HUNK_RE = re.compile(r"^@@\s+-\d+", re.MULTILINE)
_DIFF_START_RE = re.compile(r"^(diff --git |---\s+\S)")
_SCRIPT_INFO = {"python", "py", "python3"}
_SCRIPT_API_RE = re.compile(
    r"\b(read_text|count|replace_text|replace_regex|insert_before|insert_after|"
    r"replace_between|create_file|assert_count|assert_contains|assert_not_contains|"
    r"assert_python_syntax)\s*\("
)


@dataclass
class ParsedPatch:
    id: str
    raw: str
    path: str
    added: int = 0
    removed: int = 0
    new_file: bool = False
    p_level: int = 1
    warnings: list[str] = field(default_factory=list)
    unsupported: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "path": self.path,
            "added": self.added,
            "removed": self.removed,
            "new_file": self.new_file,
            "p_level": self.p_level,
            "warnings": [tr(item) for item in self.warnings],
            "unsupported": tr(self.unsupported) if self.unsupported else None,
        }


@dataclass
class ParseResult:
    explanation: str = ""
    commit_message: str = ""
    patches: list[ParsedPatch] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    mode: str = "diff"
    script: str = ""
    script_result: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "mode": self.mode,
            "explanation": self.explanation,
            "commit_message": self.commit_message,
            "patches": [patch.to_dict() for patch in self.patches],
            "warnings": [tr(item) for item in self.warnings],
        }
        if self.script:
            data["script"] = self.script
        if self.script_result is not None:
            data["script_result"] = self.script_result
        return data


@dataclass
class _Block:
    start: int
    end: int
    body: str
    info: str = ""
    fenced: bool = False
    heading: str = ""


def _classify_heading(text: str) -> str | None:
    cleaned = re.sub(r"[*_`：:\s]+", " ", text).strip().lower()
    if not cleaned:
        return None
    if any(word in cleaned for word in ("commit", "提交")):
        return "commit"
    if any(
        word in cleaned
        for word in ("修改说明", "变更说明", "说明", "summary", "explanation", "overview", "摘要")
    ):
        return "explanation"
    if any(word in cleaned for word in ("python", "脚本", "script")):
        return "script"
    if any(word in cleaned for word in ("补丁", "patch", "diff", "文件修改", "代码修改")):
        return "patch"
    return None


def _strip_heading(line: str) -> str:
    match = _HEADING_RE.match(line)
    if match:
        return match.group(2).strip()
    return line.strip().strip("*_`：: ").strip()


def _looks_like_path(text: str) -> bool:
    text = text.strip().strip("`'\"")
    if not text or " " in text:
        return False
    return "/" in text or "\\" in text or bool(re.search(r"\.[A-Za-z0-9]{1,8}$", text))


_PLAIN_HEADINGS = {
    "修改说明": "explanation",
    "变更说明": "explanation",
    "说明": "explanation",
    "commit": "commit",
    "commit建议": "commit",
    "commitmessage": "commit",
    "提交": "commit",
    "提交建议": "commit",
    "提交信息": "commit",
    "提交说明": "commit",
    "python补丁脚本": "script",
    "python脚本": "script",
    "python代码": "script",
    "补丁脚本": "script",
    "脚本": "script",
    "script": "script",
    "补丁": "patch",
    "文件补丁": "patch",
    "代码修改": "patch",
    "文件修改": "patch",
    "改动说明": "explanation",
    "变更内容": "explanation",
    "patch": "patch",
    "diff": "patch",
    "summary": "explanation",
    "explanation": "explanation",
    "overview": "explanation",
    "摘要": "explanation",
}


def _find_headings(lines: list[str], fence_mask: list[bool]) -> list[tuple[int, str, str]]:
    result: list[tuple[int, str, str]] = []
    for index, line in enumerate(lines):
        if fence_mask[index]:
            continue
        match = _HEADING_RE.match(line)
        text = match.group(2) if match else line
        cleaned = _strip_heading(text)
        if match:
            kind = _classify_heading(cleaned)
        else:
            compact = re.sub(r"\s+", "", cleaned).lower().strip("：:")
            kind = _PLAIN_HEADINGS.get(compact)
        if kind is None and _looks_like_path(cleaned):
            kind = "path"
        if kind:
            result.append((index, kind, cleaned))
    return result


def _find_fences(lines: list[str]) -> tuple[list[_Block], list[bool]]:
    blocks: list[_Block] = []
    mask = [False] * len(lines)
    index = 0
    while index < len(lines):
        match = _FENCE_RE.match(lines[index])
        if not match:
            index += 1
            continue
        info = match.group(1).strip()
        start = index
        index += 1
        body_lines: list[str] = []
        while index < len(lines) and not _FENCE_RE.match(lines[index]):
            body_lines.append(lines[index])
            mask[index] = True
            index += 1
        if index < len(lines):
            mask[index] = True
            end = index
            index += 1
        else:
            end = len(lines) - 1
        blocks.append(
            _Block(
                start=start,
                end=end,
                body="\n".join(body_lines),
                info=info,
                fenced=True,
            )
        )
        mask[start] = True
    return blocks, mask


def _nearest_heading(
    headings: list[tuple[int, str, str]],
    line_no: int,
    *,
    max_distance: int = 6,
) -> tuple[str, str] | None:
    best: tuple[int, str, str] | None = None
    for heading in headings:
        if heading[0] >= line_no:
            break
        best = heading
    if best is None:
        return None
    if line_no - best[0] > max_distance:
        return None
    return best[1], best[2]


def _section_text(
    lines: list[str],
    headings: list[tuple[int, str, str]],
    kind: str,
) -> str:
    for pos, (index, heading_kind, _) in enumerate(headings):
        if heading_kind != kind:
            continue
        end = headings[pos + 1][0] if pos + 1 < len(headings) else len(lines)
        body = "\n".join(lines[index + 1 : end]).strip()
        return body
    return ""


def _prose_before(
    lines: list[str],
    mask: list[bool],
    headings: list[tuple[int, str, str]],
    cutoff: int,
) -> str:
    """Collect free prose before the first section heading (or cutoff)."""
    section_start = cutoff
    for index, kind, _ in headings:
        if index >= cutoff:
            break
        if kind in {"commit", "patch", "script"}:
            section_start = index
            break
    prose: list[str] = []
    for index in range(max(0, section_start)):
        if mask[index]:
            continue
        line = lines[index]
        if _HEADING_RE.match(line):
            continue
        prose.append(line)
    return "\n".join(prose).strip()


def _unfenced_diff_blocks(
    lines: list[str],
    fence_mask: list[bool],
    headings: list[tuple[int, str, str]],
) -> list[_Block]:
    blocks: list[_Block] = []
    heading_lines = {item[0] for item in headings}
    index = 0
    while index < len(lines):
        if fence_mask[index] or index in heading_lines:
            index += 1
            continue
        line = lines[index]
        starts = line.startswith("diff --git ")
        if not starts and line.startswith("--- "):
            if index + 1 < len(lines) and lines[index + 1].startswith("+++ "):
                starts = True
        if not starts:
            index += 1
            continue
        start = index
        body: list[str] = []
        while index < len(lines):
            if fence_mask[index] or index in heading_lines:
                break
            if index > start and lines[index].startswith("diff --git "):
                break
            if index > start and not lines[index].strip():
                break
            body.append(lines[index])
            index += 1
        block = _Block(
            start=start,
            end=index - 1,
            body="\n".join(body),
            info="",
            fenced=False,
        )
        blocks.append(block)
    return blocks


def _extract_block_text(block: _Block) -> str:
    return block.body.strip("\n")


def parse_answer(
    answer: str,
    *,
    root: Path,
    known_paths: Iterable[str] = (),
) -> ParseResult:
    if not answer or not answer.strip():
        raise AppError("answer_empty", "AI 回答为空")
    normalized = answer.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    fenced, mask = _find_fences(lines)
    headings = _find_headings(lines, mask)
    result = ParseResult()

    patch_blocks: list[_Block] = []
    commit_blocks: list[_Block] = []
    for block in fenced:
        heading = _nearest_heading(headings, block.start)
        body = block.body
        looks_diff = (
            "diff --git " in body
            or (body.lstrip().startswith("--- ") and "\n+++ " in body)
            or bool(_HUNK_RE.search(body))
        )
        if looks_diff:
            block.heading = heading[1] if heading else ""
            patch_blocks.append(block)
            if not block.info:
                result.warnings.append("补丁代码块缺少 diff 语言标记，已按 diff 解析")
        elif heading and heading[0] == "commit":
            commit_blocks.append(block)
        elif heading and heading[0] == "patch":
            # A patch heading followed by a non-diff block is suspicious, but
            # keep the warning and let the normal parser try it.
            result.warnings.append("补丁标题下的代码块不是有效的 unified diff")

    patch_blocks.extend(_unfenced_diff_blocks(lines, mask, headings))
    # De-duplicate overlapping blocks (a fenced block and the unfenced scanner
    # cannot overlap, but be defensive).
    seen_ranges: set[tuple[int, int]] = set()
    unique_blocks: list[_Block] = []
    for block in patch_blocks:
        key = (block.start, block.end)
        if key in seen_ranges:
            continue
        seen_ranges.add(key)
        unique_blocks.append(block)
    patch_blocks = sorted(unique_blocks, key=lambda block: block.start)

    known = [normalize_rel_path(path) for path in known_paths]
    used_paths: set[str] = set()
    patch_number = 0
    for block in patch_blocks:
        body = block.body
        heading = _nearest_heading(headings, block.start)
        if (
            heading
            and heading[0] in {"path", "patch"}
            and _looks_like_path(heading[1])
            and not body.lstrip().startswith(("diff --git ", "--- "))
            and _HUNK_RE.search(body)
        ):
            body = (
                f"diff --git a/{heading[1].strip().strip('`')} "
                f"b/{heading[1].strip().strip('`')}\n"
                f"--- a/{heading[1].strip().strip('`')}\n"
                f"+++ b/{heading[1].strip().strip('`')}\n"
                + body
            )
            result.warnings.append("补丁缺少文件头，已根据上方标题补全")
        try:
            parsed = parse_unified_diff(body, root=root, known_paths=known)
        except AppError as exc:
            result.warnings.append(f"补丁解析失败：{exc.message}")
            continue
        if not parsed:
            result.warnings.append("发现疑似补丁的代码块，但未能解析出文件")
            continue
        for file_patch in parsed:
            if not file_patch.path:
                heading = _nearest_heading(headings, block.start)
                if heading and _looks_like_path(heading[1]):
                    try:
                        file_patch.path, file_patch.p_level = resolve_patch_path(
                            heading[1], root=root, known_paths=known
                        )
                        file_patch.warnings.append("文件路径来自补丁上方的标题")
                    except AppError:
                        pass
            if not file_patch.path:
                result.warnings.append("有补丁无法确定文件路径，请手工编辑")
                continue
            try:
                file_patch.path = normalize_rel_path(file_patch.path)
            except AppError as exc:
                result.warnings.append(f"补丁路径无效：{exc.message}")
                continue
            if file_patch.path in used_paths:
                result.warnings.append(f"同一文件出现多个补丁：{file_patch.path}")
            used_paths.add(file_patch.path)
            patch_number += 1
            raw = block.body.strip() + "\n"
            try:
                raw = canonical_patch(file_patch)
            except AppError:
                # Keep the user's raw patch so it can be manually repaired.
                pass
            entry = ParsedPatch(
                id=f"p{patch_number:04d}",
                raw=raw,
                path=file_patch.path,
                added=file_patch.added,
                removed=file_patch.removed,
                new_file=file_patch.new_file,
                p_level=file_patch.p_level,
                warnings=list(file_patch.warnings),
                unsupported=file_patch.unsupported,
            )
            if file_patch.p_level != 1:
                entry.warnings.append(
                    f"识别到原始 -p{file_patch.p_level}，已规范化为标准 a/ b/ 路径"
                )
            result.patches.append(entry)

    if not result.patches:
        result.warnings.append("没有从回答中提取到任何文件补丁")

    explanation = _section_text(lines, headings, "explanation")
    if not explanation:
        first_patch_line = min(
            (block.start for block in patch_blocks), default=len(lines)
        )
        explanation = _prose_before(lines, mask, headings, first_patch_line)
    result.explanation = _clean_text(explanation)

    commit = _section_text(lines, headings, "commit")
    if not commit:
        for block in commit_blocks:
            commit = block.body
            break
    if not commit:
        match = re.search(
            r"(?im)^\s*(?:commit|提交)(?:\s*(?:建议|message|信息))?\s*[:：]\s*(.+)$",
            normalized,
        )
        if match:
            commit = match.group(1).strip()
    if not commit:
        # Heading-only line, e.g. "Commit 建议" with no colon, followed by text.
        match = re.search(
            r"(?im)^\s*(?:commit|提交)(?:\s*(?:建议|message|信息|说明))?\s*[:：]?\s*$\n+\s*([^\n]+)",
            normalized,
        )
        if match:
            commit = match.group(1).strip()
    result.commit_message = _clean_text(commit).strip()

    if not result.explanation:
        result.warnings.append("未找到修改说明")
    if not result.commit_message:
        result.warnings.append("未找到 commit 建议")
    if not result.patches:
        result.warnings.append("未能提取 patch；请检查回答格式或手工粘贴补丁")

    # Stable de-duplication while preserving order.
    result.warnings = list(dict.fromkeys(result.warnings))
    return result


def _looks_like_diff(body: str) -> bool:
    return (
        "diff --git " in body
        or (body.lstrip().startswith("--- ") and "\n+++ " in body)
        or bool(_HUNK_RE.search(body))
    )


def parse_script_answer(
    answer: str,
    *,
    root: Path | None = None,
    known_paths: Iterable[str] = (),
) -> ParseResult:
    """Extract a Python patch script with the same tolerance as diff parsing."""
    if not answer or not answer.strip():
        raise AppError("answer_empty", "AI 回答为空")
    normalized = answer.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    fenced, mask = _find_fences(lines)
    headings = _find_headings(lines, mask)
    result = ParseResult(mode="python")

    candidates: list[_Block] = []
    for block in fenced:
        heading = _nearest_heading(headings, block.start)
        if heading and heading[0] == "commit":
            continue
        if _looks_like_diff(block.body):
            continue
        if block.info.strip().lower().lstrip(".") in _SCRIPT_INFO:
            candidates.append(block)
        elif _SCRIPT_API_RE.search(block.body):
            candidates.append(block)
            result.warnings.append("Python 代码块缺少 python 语言标记，已按脚本解析")
    if not candidates:
        # Last resort: a plain python block whose heading mentions Python/脚本.
        for block in fenced:
            heading = _nearest_heading(headings, block.start)
            if heading and heading[0] == "commit":
                continue
            if not _looks_like_diff(block.body) and (
                (heading and any(word in heading[1] for word in ("python", "脚本", "script")))
                or block.info.strip().lower().lstrip(".") in _SCRIPT_INFO
            ):
                candidates.append(block)

    chosen: _Block | None = None
    if candidates:
        candidates.sort(key=lambda block: block.start)
        chosen = candidates[0]
        if len(candidates) > 1:
            result.warnings.append("发现多个 Python 代码块，已采用第一个")
        if not chosen.info.strip():
            result.warnings.append("Python 代码块缺少语言标记")
        result.script = chosen.body.strip("\n")
    elif _SCRIPT_API_RE.search(normalized):
        result.script = normalized.strip()
        result.warnings.append("未找到 Python 代码块，已按整段回答作为脚本解析")

    if not result.script:
        result.warnings.append("没有从回答中提取到 Python 补丁脚本")
    elif _HUNK_RE.search(result.script) or "diff --git " in result.script:
        result.warnings.append("脚本中包含疑似 unified diff 的内容，请检查回答格式")

    explanation = _section_text(lines, headings, "explanation")
    if not explanation:
        cutoff = chosen.start if chosen is not None else len(lines)
        explanation = _prose_before(lines, mask, headings, cutoff)
    result.explanation = _clean_text(explanation)

    commit = _section_text(lines, headings, "commit")
    if not commit:
        match = re.search(
            r"(?im)^\s*(?:commit|提交)(?:\s*(?:建议|message|信息))?\s*[:：]\s*(.+)$",
            normalized,
        )
        if match:
            commit = match.group(1).strip()
    if not commit:
        # Heading-only line, e.g. "Commit 建议" with no colon, followed by text.
        match = re.search(
            r"(?im)^\s*(?:commit|提交)(?:\s*(?:建议|message|信息|说明))?\s*[:：]?\s*$\n+\s*([^\n]+)",
            normalized,
        )
        if match:
            commit = match.group(1).strip()
    result.commit_message = _clean_text(commit).strip()

    if not result.explanation:
        result.warnings.append("未找到修改说明")
    if not result.commit_message:
        result.warnings.append("未找到 commit 建议")
    result.warnings = list(dict.fromkeys(result.warnings))
    return result


def _clean_text(value: str) -> str:
    value = value.strip()
    value = re.sub(r"^\s*```[^\n]*\n", "", value)
    value = re.sub(r"\n```\s*$", "", value)
    return value.strip()
