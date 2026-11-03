from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Any

from .diff_engine import DiffLine, canonical_patch, parse_unified_diff
from .errors import AppError
from .fsutil import decode_text_file, safe_target, sha256_bytes, split_lines_keep_eol
from .sessions import SessionStore


def _expand_trailing_context(file_patch, data: bytes) -> None:
    """Add one existing line after a trailing-context-less hunk.

    Git's ``apply`` is stricter than PatchBridge's internal line matcher: a
    hunk that ends immediately after an added/removed line can fail when the
    file has more lines.  Adding one unchanged line makes the exported patch
    work with plain ``git apply`` without changing what the patch does.
    """
    if file_patch.new_file:
        return
    try:
        lines = split_lines_keep_eol(decode_text_file(data).text)
    except Exception:
        return
    hunks = file_patch.hunks
    for index, hunk in enumerate(hunks):
        if not hunk.new_lines or hunk.new_lines[-1].tag == " ":
            continue
        old_end = hunk.old_start - 1 + len(hunk.old_lines)
        if old_end >= len(lines):
            continue
        if index + 1 < len(hunks) and hunks[index + 1].old_start - 1 <= old_end:
            continue
        hunk.lines.append(DiffLine(" ", lines[old_end].content))


def combined_patch(
    store: SessionStore,
    session_id: str,
    *,
    expand_context: bool = True,
) -> str:
    meta = store.meta(session_id)
    patches = store.get_patches(session_id)
    if not patches:
        raise AppError("no_patches", "会话没有补丁", status=409)
    selection = store.read_json(session_id, "selection.json") or {}
    selection_map = {
        item.get("path"): item
        for item in selection.get("files", [])
        if isinstance(item, dict) and item.get("path")
    }
    known = list(selection_map)
    root = Path(meta.get("root") or "")
    parts: list[str] = []
    for entry in patches:
        parsed = parse_unified_diff(
            entry.get("content") or "",
            root=root,
            known_paths=known,
        )
        if len(parsed) != 1:
            raise AppError(
                "patch_invalid",
                f"补丁无法导出：{entry.get('path')}",
                details={"patch_id": entry.get("id")},
            )
        file_patch = parsed[0]
        if expand_context and not file_patch.new_file:
            try:
                target = safe_target(root, file_patch.path)
                if target.is_file():
                    current = target.read_bytes()
                    expected = (selection_map.get(file_patch.path) or {}).get("sha256")
                    if not expected or sha256_bytes(current) == expected:
                        _expand_trailing_context(file_patch, current)
            except Exception:
                pass
        parts.append(canonical_patch(file_patch))
    return "".join(parts)


def export_markdown(store: SessionStore, session_id: str) -> str:
    details = store.details(session_id)
    meta = details["meta"]
    parsed = details.get("parsed") or {}
    selection = details.get("selection") or {}
    lines: list[str] = [
        f"# {meta.get('title') or session_id}",
        "",
        f"- 会话 ID：`{session_id}`",
        f"- 工程：{meta.get('project_name') or ''} (`{meta.get('root') or ''}`)",
        f"- 创建时间：{meta.get('created_at') or ''}",
        f"- 状态：{details.get('status') or ''}",
        f"- 打包文件数：{meta.get('file_count') or 0}",
        f"- 打包字节数：{meta.get('total_bytes') or 0}",
        "",
        "## 需求",
        "",
        details.get("requirement") or "",
        "",
        "## 选中文件",
        "",
    ]
    for item in selection.get("files") or []:
        lines.append(f"- `{item.get('path')}` ({item.get('size', 0)} bytes, sha256 `{item.get('sha256', '')}`)")
    lines.extend(["", "## 修改说明", "", parsed.get("explanation") or "", ""])
    if details.get("answer"):
        lines.extend(
            [
                "## AI 回答原文",
                "",
                "```text",
                details.get("answer").rstrip("\n"),
                "```",
                "",
            ]
        )
    lines.extend(["## Commit 建议", "", "```text", parsed.get("commit_message") or "", "```", ""])
    warnings = parsed.get("warnings") or []
    if warnings:
        lines.extend(["## 警告", ""])
        lines.extend(f"- {warning}" for warning in warnings)
        lines.append("")
    lines.extend(["## 文件补丁", ""])
    for patch in details.get("patches") or []:
        lines.extend(
            [
                f"### `{patch.get('path')}`",
                "",
                f"新增 {patch.get('added', 0)} 行，删除 {patch.get('removed', 0)} 行"
                + ("，新增文件" if patch.get("new_file") else ""),
                "",
                "```diff",
                (patch.get("content") or "").rstrip("\n"),
                "```",
                "",
            ]
        )
    lines.extend(["## 操作事件", ""])
    for event in details.get("events") or []:
        lines.append(
            f"- `{event.get('at')}` **{event.get('type')}** "
            f"`{json.dumps(event.get('data') or {}, ensure_ascii=False)}`"
        )
    lines.append("")
    return "\n".join(lines)


def _read_after(backup_dir: Path, rel: str | None) -> bytes | None:
    if not rel:
        return None
    target = (backup_dir / rel).resolve()
    try:
        target.relative_to(backup_dir.resolve())
    except ValueError:
        return None
    if not target.exists():
        return None
    return target.read_bytes()


def disk_diff(store: SessionStore, session_id: str) -> dict[str, Any]:
    active = [
        event for event in store.events(session_id) if event.get("type") == "apply"
    ]
    if not active:
        return {
            "available": False,
            "message": "会话尚未应用补丁，没有“应用后”快照可比较",
            "files": [],
        }
    latest = active[-1]
    data = latest.get("data") or {}
    manifest_rel = data.get("backup_manifest")
    if not manifest_rel:
        return {"available": False, "message": "缺少备份清单", "files": []}
    manifest_path = (store.config.data_dir / Path(*str(manifest_rel).split("/"))).resolve()
    try:
        manifest_path.relative_to(store.config.data_dir.resolve())
    except ValueError:
        raise AppError("backup_invalid", "备份路径越界", status=500)
    if not manifest_path.exists():
        return {"available": False, "message": "备份已被清理，无法生成内容差异", "files": []}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    backup_dir = manifest_path.parent
    root = Path(store.meta(session_id).get("root") or "")
    result: list[dict[str, Any]] = []
    for item in manifest.get("files") or []:
        path = item.get("path") or ""
        expected = _read_after(backup_dir, item.get("after"))
        try:
            target = safe_target(root, path)
        except Exception:
            result.append(
                {
                    "path": path,
                    "status": "unsafe_path",
                    "added": 0,
                    "removed": 0,
                    "expected_sha256": None,
                    "current_sha256": None,
                    "diff": "",
                }
            )
            continue
        current = target.read_bytes() if target.exists() else None
        if expected == current:
            continue
        status = "modified"
        if expected is None:
            status = "unavailable"
        elif current is None:
            status = "missing"
        diff_text = ""
        added = removed = 0
        if expected is not None and current is not None:
            try:
                old = decode_text_file(expected).text.splitlines(keepends=True)
                new = decode_text_file(current).text.splitlines(keepends=True)
                diff_lines = list(
                    difflib.unified_diff(
                        old,
                        new,
                        fromfile=f"session/{path}",
                        tofile=f"disk/{path}",
                        lineterm="",
                    )
                )
                diff_text = "\n".join(diff_lines)
                added = sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
                removed = sum(1 for line in diff_lines if line.startswith("-") and not line.startswith("---"))
            except Exception as exc:
                status = f"error: {exc}"
        result.append(
            {
                "path": path,
                "status": status,
                "added": added,
                "removed": removed,
                "expected_sha256": sha256_bytes(expected) if expected is not None else None,
                "current_sha256": sha256_bytes(current) if current is not None else None,
                "diff": diff_text,
            }
        )
    return {
        "available": True,
        "apply_id": data.get("apply_id"),
        "files": result,
        "message": "没有差异" if not result else f"{len(result)} 个文件与“应用后”不同",
    }
