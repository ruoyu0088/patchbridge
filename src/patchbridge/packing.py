from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import AppError
from .fsutil import (
    decode_text_file,
    normalize_rel_path,
    read_bytes,
    safe_target,
    sha256_bytes,
)
from .profiles import Profile

BUNDLE_VERSION = "PATCHBRIDGE BUNDLE v1"
FILE_BEGIN = "===== PATCHBRIDGE FILE BEGIN:"
FILE_END = "===== PATCHBRIDGE FILE END:"
TREE_BEGIN = "===== PATCHBRIDGE TREE BEGIN ====="
TREE_END = "===== PATCHBRIDGE TREE END ====="
REQ_BEGIN = "===== PATCHBRIDGE REQUIREMENT BEGIN ====="
REQ_END = "===== PATCHBRIDGE REQUIREMENT END ====="
INSTR_BEGIN = "===== PATCHBRIDGE INSTRUCTIONS BEGIN ====="
INSTR_END = "===== PATCHBRIDGE INSTRUCTIONS END ====="

RESERVED_PREFIX = "===== PATCHBRIDGE "


@dataclass
class BundleResult:
    text: str
    selection: dict[str, Any]
    tree: str
    file_count: int
    total_bytes: int
    token_estimate: int
    conflicts: list[str] = field(default_factory=list)


def estimate_tokens(text: str) -> int:
    """A deliberately rough estimate, only shown as a hint.

    CJK characters are counted as roughly one token, ASCII as one per four
    characters.  This is not a model tokenizer and never blocks packing.
    """
    ascii_count = sum(1 for ch in text if ord(ch) < 128)
    other = len(text) - ascii_count
    return max(1, math.ceil(ascii_count / 4 + other))


def render_tree(paths: list[str], root_name: str = "") -> str:
    tree: dict[str, Any] = {}
    for path in sorted(set(paths)):
        node = tree
        for part in path.split("/"):
            node = node.setdefault(part, {})
    lines: list[str] = []
    if root_name:
        lines.append(root_name.rstrip("/") + "/")

    def walk(node: dict[str, Any], prefix: str) -> None:
        names = sorted(node)
        for name in names:
            child = node[name]
            is_dir = bool(child)
            lines.append(prefix + name + ("/" if is_dir else ""))
            if is_dir:
                walk(child, prefix + "  ")

    walk(tree, "  " if root_name else "")
    return "\n".join(lines)


def _find_reserved(text: str) -> list[str]:
    found: list[str] = []
    for token in (
        RESERVED_PREFIX,
        "PATCHBRIDGE FILE BEGIN:",
        "PATCHBRIDGE FILE END:",
        "PATCHBRIDGE TREE BEGIN",
        "PATCHBRIDGE TREE END",
        "PATCHBRIDGE REQUIREMENT BEGIN",
        "PATCHBRIDGE REQUIREMENT END",
        "PATCHBRIDGE INSTRUCTIONS BEGIN",
        "PATCHBRIDGE INSTRUCTIONS END",
    ):
        if token in text:
            found.append(token)
    return found


def render_prompt(template: str, values: dict[str, Any]) -> str:
    result = template
    for key, value in values.items():
        result = result.replace("{{" + key + "}}", str(value))
    return result


def build_bundle(
    *,
    profile: Profile,
    requirement: str,
    selected_paths: list[str],
    prompt_template: str,
    generated_at: datetime | None = None,
    max_bundle_bytes: int = 80 * 1024 * 1024,
) -> BundleResult:
    if not requirement or not requirement.strip():
        raise AppError("requirement_empty", "需求不能为空")
    if not selected_paths:
        raise AppError("no_files_selected", "请至少勾选一个文件")

    root = profile.root_path
    unique = sorted({normalize_rel_path(path) for path in selected_paths})
    if len(unique) > 20000:
        raise AppError("too_many_files", "单次打包文件数量过多，请收窄选择")

    marker_conflicts: list[str] = []
    if _find_reserved(requirement):
        marker_conflicts.append("__requirement__")

    files: list[dict[str, Any]] = []
    contents: list[tuple[str, str]] = []
    total = 0
    for rel in unique:
        if "\n" in rel or "\r" in rel or _find_reserved(rel):
            marker_conflicts.append(rel)
            continue
        target = safe_target(root, rel)
        if not target.is_file():
            raise AppError(
                "file_missing",
                f"选中的文件不存在：{rel}",
                details={"path": rel},
            )
        raw = read_bytes(target)
        try:
            info = decode_text_file(raw)
        except Exception as exc:
            raise AppError(
                "unsupported_text",
                f"文件不是受支持的文本：{rel}",
                details={"path": rel, "reason": str(exc)},
            ) from exc
        conflicts = _find_reserved(info.text)
        if conflicts:
            marker_conflicts.append(rel)
        digest = sha256_bytes(raw)
        total += len(raw)
        files.append(
            {
                "path": rel,
                "size": len(raw),
                "sha256": digest,
                "encoding": info.encoding,
                "bom": info.bom_present,
                "eol": "crlf" if info.eol == "\r\n" else ("cr" if info.eol == "\r" else "lf"),
                "final_newline": info.final_newline,
            }
        )
        contents.append((rel, info.text))

    if marker_conflicts:
        raise AppError(
            "bundle_marker_conflict",
            "以下内容包含 PatchBridge 保留分隔符，拒绝打包",
            status=422,
            details={"conflicts": marker_conflicts},
        )

    now = generated_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    generated = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    tree = render_tree(unique, root.name)

    prompt = render_prompt(
        prompt_template,
        {
            "PROJECT_NAME": profile.name,
            "ROOT": str(root),
            "FILE_COUNT": len(unique),
            "TOTAL_BYTES": total,
            "GENERATED_AT": generated,
        },
    )
    for token in _find_reserved(prompt):
        # The prompt is generated by us; it should not accidentally contain a
        # section marker.  Treat it as a configuration error rather than
        # producing an ambiguous bundle.
        raise AppError(
            "prompt_marker_conflict",
            "提示词模板包含 PatchBridge 保留分隔符",
            status=422,
            details={"token": token},
        )

    parts: list[str] = [
        f"# {BUNDLE_VERSION}\n",
        f"project: {profile.name}\n",
        f"root: {root}\n",
        f"generated_at: {generated}\n",
        f"files: {len(unique)}\n",
        f"bytes: {total}\n",
        "\n",
        INSTR_BEGIN + "\n",
        prompt.rstrip("\n") + "\n",
        INSTR_END + "\n\n",
        TREE_BEGIN + "\n",
        tree + "\n",
        TREE_END + "\n\n",
        REQ_BEGIN + "\n",
        requirement.rstrip("\r\n") + "\n",
        REQ_END + "\n\n",
    ]

    for (rel, text), meta in zip(contents, files):
        parts.append(f"{FILE_BEGIN} {rel} =====\n")
        # Content is not escaped or re-indented.  A structural newline is
        # inserted only when the file has no final newline, so the end marker
        # can be a line of its own; selection.json records the original fact.
        parts.append(text)
        if not text.endswith(("\n", "\r")):
            parts.append("\n")
        parts.append(f"{FILE_END} {rel} =====\n\n")

    bundle_text = "".join(parts).rstrip("\n") + "\n"
    encoded = bundle_text.encode("utf-8")
    if len(encoded) > max_bundle_bytes:
        raise AppError(
            "bundle_too_large",
            "打包文本超过大小上限，请减少选中文件",
            details={"bytes": len(encoded), "limit": max_bundle_bytes},
        )

    selection = {
        "version": 1,
        "root": str(root),
        "profile": profile.to_snapshot(),
        "total_bytes": total,
        "files": files,
    }
    return BundleResult(
        text=bundle_text,
        selection=selection,
        tree=tree,
        file_count=len(unique),
        total_bytes=total,
        token_estimate=estimate_tokens(bundle_text),
    )
