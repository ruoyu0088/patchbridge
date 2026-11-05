from __future__ import annotations

import os
import secrets
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import AppConfig
from .diff_engine import (
    AlignResult,
    FilePatch,
    align_patch_indentation,
    apply_file_patch,
    canonical_patch,
    parse_unified_diff,
)
from .errors import AppError
from .fsutil import (
    atomic_write_bytes,
    atomic_write_json,
    ensure_dir,
    is_git_repo,
    normalize_rel_path,
    read_bytes,
    safe_target,
    sha256_bytes,
)
from .profiles import Profile
from .sessions import SessionStore, utc_now

STATUS_OK = "ok"
STATUS_CHANGED = "changed"
STATUS_MISSING = "missing"
STATUS_NEW = "new"
STATUS_UNSELECTED = "unselected"


@dataclass
class Evaluation:
    patch_id: str
    path: str
    new_file: bool
    added: int
    removed: int
    hash_status: str
    scope_status: str
    apply_status: str
    reason: str = ""
    warnings: list[str] | None = None
    current_sha256: str | None = None
    after_sha256: str | None = None
    new_bytes: bytes | None = None
    file_patch: FilePatch | None = None
    diagnostics: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "patch_id": self.patch_id,
            "path": self.path,
            "new_file": self.new_file,
            "added": self.added,
            "removed": self.removed,
            "hash_status": self.hash_status,
            "scope_status": self.scope_status,
            "apply_status": self.apply_status,
            "reason": self.reason,
            "warnings": list(self.warnings or []),
            "current_sha256": self.current_sha256,
            "after_sha256": self.after_sha256,
            "diagnostics": self.diagnostics,
        }


def _profile_for(meta: dict[str, Any]) -> Profile:
    profile = meta.get("profile") or {}
    return Profile(
        id=str(profile.get("id") or ""),
        name=str(profile.get("name") or meta.get("project_name") or ""),
        root=str(profile.get("root") or meta.get("root") or ""),
        mode=str(profile.get("mode") or "exclude"),
        rules=list(profile.get("rules") or []),
    )


def _selection_map(selection: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in selection.get("files") or []:
        if isinstance(item, dict) and item.get("path"):
            result[str(item["path"])] = item
    return result


def _patch_map(store: SessionStore, session_id: str) -> dict[str, dict[str, Any]]:
    return {str(item.get("id")): item for item in store.get_patches(session_id)}


def _parse_patch_entry(entry: dict[str, Any], root: Path, known: list[str]) -> FilePatch:
    patches = parse_unified_diff(entry.get("content") or "", root=root, known_paths=known)
    if not patches:
        raise AppError("patch_invalid", "补丁无法解析", details={"patch_id": entry.get("id")})
    if len(patches) != 1:
        raise AppError(
            "patch_invalid",
            "一个补丁条目只能包含一个文件",
            details={"patch_id": entry.get("id"), "files": len(patches)},
        )
    return patches[0]


def evaluate_patch(
    store: SessionStore,
    session_id: str,
    entry: dict[str, Any],
    *,
    selection: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
) -> Evaluation:
    meta = meta or store.meta(session_id)
    selection = selection or store.read_json(session_id, "selection.json") or {}
    selected = _selection_map(selection)
    root = Path(meta.get("root") or "")
    profile = _profile_for(meta)
    known = list(selected)
    patch_id = str(entry.get("id") or "")
    eval_result = Evaluation(
        patch_id=patch_id,
        path=str(entry.get("path") or ""),
        new_file=bool(entry.get("new_file")),
        added=int(entry.get("added") or 0),
        removed=int(entry.get("removed") or 0),
        hash_status=STATUS_OK,
        scope_status=STATUS_OK,
        apply_status=STATUS_OK,
        warnings=list(entry.get("warnings") or []),
    )
    try:
        file_patch = _parse_patch_entry(entry, root, known)
    except AppError as exc:
        eval_result.apply_status = "conflict"
        eval_result.reason = exc.message
        return eval_result
    eval_result.file_patch = file_patch
    eval_result.new_file = file_patch.new_file
    eval_result.added = file_patch.added
    eval_result.removed = file_patch.removed
    if file_patch.unsupported:
        eval_result.apply_status = "unsupported"
        eval_result.reason = file_patch.unsupported
        return eval_result
    try:
        path = normalize_rel_path(file_patch.path)
    except AppError as exc:
        eval_result.apply_status = "conflict"
        eval_result.reason = exc.message
        return eval_result
    eval_result.path = path
    if not path:
        eval_result.apply_status = "conflict"
        eval_result.reason = "补丁缺少文件路径"
        return eval_result
    try:
        target = safe_target(root, path)
    except AppError as exc:
        eval_result.scope_status = "outside"
        eval_result.apply_status = "conflict"
        eval_result.reason = exc.message
        return eval_result
    if not profile.is_visible(path):
        eval_result.scope_status = "excluded"
        eval_result.apply_status = "conflict"
        eval_result.reason = "目标路径不在 profile 允许的工程范围内"
        return eval_result

    exists = target.exists()
    if file_patch.new_file:
        eval_result.hash_status = STATUS_NEW
        if exists:
            eval_result.apply_status = "conflict"
            eval_result.reason = "补丁要新增文件，但目标已存在"
            eval_result.current_sha256 = sha256_bytes(target.read_bytes())
            return eval_result
    else:
        if not exists:
            eval_result.hash_status = STATUS_MISSING
            eval_result.apply_status = "conflict"
            eval_result.reason = "目标文件不存在"
            return eval_result
        current = target.read_bytes()
        eval_result.current_sha256 = sha256_bytes(current)
        selected_entry = selected.get(path)
        if selected_entry is None:
            eval_result.hash_status = STATUS_UNSELECTED
            eval_result.apply_status = "conflict"
            eval_result.reason = "目标文件不在打包时选中的文件范围内"
            return eval_result
        if str(selected_entry.get("sha256") or "") != eval_result.current_sha256:
            eval_result.hash_status = STATUS_CHANGED

    current = None if not exists else target.read_bytes()
    try:
        result = apply_file_patch(file_patch, current, path=path)
    except AppError as exc:
        eval_result.apply_status = "conflict"
        eval_result.reason = exc.message
        if exc.code == "patch_context_mismatch" and isinstance(exc.details, dict):
            eval_result.diagnostics = exc.details
            if exc.details.get("hint"):
                eval_result.reason = f"{exc.message}：{exc.details['hint']}"
        return eval_result
    eval_result.new_bytes = result.data
    eval_result.after_sha256 = sha256_bytes(result.data)
    eval_result.warnings = list(eval_result.warnings or []) + list(result.warnings)
    return eval_result


def dry_run(
    store: SessionStore,
    session_id: str,
    patch_ids: list[str] | None = None,
    *,
    persist: bool = True,
) -> dict[str, Any]:
    meta = store.meta(session_id)
    selection = store.read_json(session_id, "selection.json") or {}
    entries = store.get_patches(session_id)
    if patch_ids:
        wanted = set(patch_ids)
        entries = [entry for entry in entries if entry.get("id") in wanted]
        if len(entries) != len(wanted):
            found = {entry.get("id") for entry in entries}
            raise AppError(
                "patch_not_found",
                "部分补丁不存在",
                status=404,
                details={"missing": sorted(wanted - found)},
            )
    results = [
        evaluate_patch(store, session_id, entry, selection=selection, meta=meta).as_dict()
        for entry in entries
    ]
    summary = {
        "ok": all(item["apply_status"] == "ok" for item in results),
        "conflicts": sum(1 for item in results if item["apply_status"] != "ok"),
        "hash_changed": sum(1 for item in results if item["hash_status"] == "changed"),
        "results": results,
    }
    if persist:
        store.append_event(
            session_id,
            "dry_run",
            {
                "patch_ids": [entry.get("id") for entry in entries],
                "ok": summary["ok"],
                "conflicts": summary["conflicts"],
                "hash_changed": summary["hash_changed"],
            },
        )
    return summary


def align_session_patch(
    store: SessionStore,
    session_id: str,
    patch_id: str,
    *,
    align_added: bool = True,
) -> dict[str, Any]:
    """Return an indentation-aligned patch without saving it.

    The caller can inspect the proposed content, edit it further, and only then
    use the normal update_patch endpoint.  This keeps a one-click operation from
    silently changing a session.
    """
    if store.has_any_apply(session_id):
        raise AppError("session_locked", "会话已应用补丁，不能再编辑补丁；请重新载入", status=409)
    entry = store.get_patch(session_id, patch_id)
    meta = store.meta(session_id)
    root = Path(meta.get("root") or "")
    selection = store.read_json(session_id, "selection.json") or {}
    known = [item.get("path") for item in selection.get("files", []) if item.get("path")]
    parsed = parse_unified_diff(
        entry.get("content") or "",
        root=root,
        known_paths=known,
    )
    if len(parsed) != 1:
        raise AppError(
            "patch_invalid",
            "一个补丁条目只能包含一个文件，无法自动对齐",
            status=422,
            details={"patch_id": patch_id, "files": len(parsed)},
        )
    file_patch = parsed[0]
    if file_patch.new_file:
        raise AppError(
            "align_new_file",
            f"新增文件没有原文件可对齐：{file_patch.path}",
            status=409,
        )
    target = safe_target(root, file_patch.path)
    if not target.is_file():
        raise AppError("file_missing", f"目标文件不存在：{file_patch.path}", status=409)
    result: AlignResult = align_patch_indentation(
        file_patch,
        target.read_bytes(),
        align_added=align_added,
    )
    return {
        "aligned": result.aligned,
        "content": result.content,
        "changes": result.changes,
        "warnings": result.warnings,
        "reason": result.reason,
        "align_added": align_added,
    }


def _backup_rel(apply_id: str) -> str:
    return f"{apply_id}/manifest.json"


def _data_rel(config: AppConfig, path: Path) -> str:
    return path.resolve().relative_to(config.data_dir.resolve()).as_posix()


def _resolve_data_path(config: AppConfig, rel: str) -> Path:
    return safe_target(config.data_dir, rel)


def _check_patch_lock(store: SessionStore, session_id: str, entries: list[dict[str, Any]]) -> None:
    events = store.events(session_id)
    first_apply = next((event for event in events if event.get("type") == "apply"), None)
    if not first_apply:
        return
    locked_hashes = first_apply.get("data", {}).get("patch_hashes") or {}
    current = {str(entry.get("id")): entry.get("sha256") for entry in entries}
    changed = [
        patch_id
        for patch_id, digest in locked_hashes.items()
        if current.get(str(patch_id)) != digest
    ]
    if changed:
        raise AppError(
            "patch_locked",
            "会话已应用过补丁，补丁内容已锁定；如需修改请重新载入生成新会话",
            status=409,
            details={"changed_patch_ids": changed},
        )


def apply_session(
    store: SessionStore,
    session_id: str,
    patch_ids: list[str],
    *,
    confirm_hash_changes: list[str] | None = None,
) -> dict[str, Any]:
    # Apply is a mutation; an archived session is unpacked first so the
    # backup journal can be recovered even if the process dies mid-write.
    store.ensure_dir(session_id)
    meta = store.meta(session_id)
    root = Path(meta.get("root") or "")
    if not is_git_repo(root):
        raise AppError(
            "not_git_repo",
            "工程不是 git 仓库，拒绝应用补丁。请先在工程根目录执行 git init",
            status=409,
            details={"root": str(root)},
        )
    entries_all = store.get_patches(session_id)
    if not entries_all:
        raise AppError("no_patches", "会话没有可应用的补丁", status=409)
    entry_map = {str(entry.get("id")): entry for entry in entries_all}
    wanted = list(dict.fromkeys(patch_ids or list(entry_map)))
    missing = [patch_id for patch_id in wanted if patch_id not in entry_map]
    if missing:
        raise AppError("patch_not_found", "部分补丁不存在", status=404, details={"missing": missing})
    selected_entries = [entry_map[patch_id] for patch_id in wanted]
    if not selected_entries:
        raise AppError("no_patches_selected", "请至少勾选一个补丁")

    _check_patch_lock(store, session_id, entries_all)

    already_applied: set[str] = set()
    for event in store.events(session_id):
        if event.get("type") == "apply":
            already_applied.update(event.get("data", {}).get("patch_ids") or [])
    consumed = [patch_id for patch_id in wanted if patch_id in already_applied]
    if consumed:
        raise AppError(
            "patch_already_applied",
            "选中的补丁已经应用过，不能再次应用；如需重做请重新载入",
            status=409,
            details={"patch_ids": consumed},
        )

    confirm = {normalize_rel_path(path) for path in (confirm_hash_changes or [])}
    selection = store.read_json(session_id, "selection.json") or {}
    evaluations = [
        evaluate_patch(store, session_id, entry, selection=selection, meta=meta)
        for entry in selected_entries
    ]
    conflicts = [
        {
            "patch_id": item.patch_id,
            "path": item.path,
            "reason": item.reason,
            "apply_status": item.apply_status,
        }
        for item in evaluations
        if item.apply_status != "ok"
    ]
    if conflicts:
        raise AppError(
            "dry_run_failed",
            "选中的补丁未通过应用前检查，已取消应用",
            status=409,
            details={"conflicts": conflicts},
        )
    unconfirmed = [
        item.path
        for item in evaluations
        if item.hash_status == STATUS_CHANGED and item.path not in confirm
    ]
    if unconfirmed:
        raise AppError(
            "hash_changed",
            "以下文件在打包后发生了变化，必须显式确认后才能应用",
            status=409,
            details={"paths": unconfirmed},
        )
    duplicate_paths = {
        item.path for item in evaluations if sum(1 for other in evaluations if other.path == item.path) > 1
    }
    if duplicate_paths:
        raise AppError(
            "duplicate_patch_paths",
            "多个补丁指向同一个文件",
            status=409,
            details={"paths": sorted(duplicate_paths)},
        )

    # Build one canonical patch for the audit trail.
    combined = "".join(
        canonical_patch(item.file_patch)
        for item in evaluations
        if item.file_patch is not None
    )

    apply_id = "apply-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + secrets.token_hex(4)
    backup_dir = store.config.backups_dir / session_id / apply_id
    before_dir = ensure_dir(backup_dir / "before")
    after_dir = ensure_dir(backup_dir / "after")
    manifest_files: list[dict[str, Any]] = []
    for index, item in enumerate(evaluations):
        target = safe_target(root, item.path)
        if item.new_file and target.exists():
            raise AppError(
                "new_file_exists",
                f"补丁要新增文件，但目标在检查后出现：{item.path}",
                status=409,
                details={"path": item.path},
            )
        existed = target.exists()
        before = target.read_bytes() if existed else None
        if existed and item.current_sha256 and sha256_bytes(before) != item.current_sha256:
            raise AppError(
                "hash_changed_during_apply",
                f"文件在 dry-run 后再次变化，请重新检查：{item.path}",
                status=409,
                details={"path": item.path},
            )
        before_name = f"{index:04d}.bin"
        after_name = f"{index:04d}.bin"
        if before is not None:
            atomic_write_bytes(before_dir / before_name, before)
        if item.new_bytes is not None:
            atomic_write_bytes(after_dir / after_name, item.new_bytes)
        mode = None
        if existed:
            try:
                mode = os.stat(target).st_mode & 0o777
            except OSError:
                mode = None
        manifest_files.append(
            {
                "path": item.path,
                "patch_id": item.patch_id,
                "existed": existed,
                "backup": f"before/{before_name}" if existed else None,
                "after": f"after/{after_name}",
                "before_sha256": sha256_bytes(before) if before is not None else None,
                "after_sha256": item.after_sha256,
                "mode": mode,
            }
        )
    combined_path = backup_dir / "combined.patch"
    atomic_write_bytes(combined_path, combined.encode("utf-8"))
    manifest = {
        "version": 1,
        "session_id": session_id,
        "apply_id": apply_id,
        "created_at": utc_now(),
        "files": manifest_files,
    }
    manifest_path = backup_dir / "manifest.json"
    atomic_write_json(manifest_path, manifest)
    journal_path = backup_dir / "journal.json"
    atomic_write_json(
        journal_path,
        {"phase": "writing", "apply_id": apply_id, "created_at": utc_now()},
    )

    written: list[Path] = []
    try:
        for item in evaluations:
            target = safe_target(root, item.path)
            if item.new_bytes is None:
                raise AppError("internal", "补丁没有计算结果")
            mode = None
            if target.exists():
                try:
                    mode = os.stat(target).st_mode & 0o777
                except OSError:
                    mode = None
            atomic_write_bytes(target, item.new_bytes, mode=mode)
            written.append(target)
        for item in evaluations:
            target = safe_target(root, item.path)
            actual = sha256_bytes(target.read_bytes())
            if item.after_sha256 and actual != item.after_sha256:
                raise AppError(
                    "apply_verify_failed",
                    f"写入后校验失败：{item.path}",
                    details={"path": item.path},
                )
    except BaseException as exc:
        rollback_manifest(store.config, manifest)
        journal_path.unlink(missing_ok=True)
        raise AppError(
            "apply_failed",
            f"应用失败，已按备份回滚：{exc}",
            status=500,
            details={"rollback": True},
        ) from exc

    event_data = {
        "apply_id": apply_id,
        "patch_ids": wanted,
        "paths": [item.path for item in evaluations],
        "before": {item.path: item.current_sha256 for item in evaluations},
        "after": {item.path: item.after_sha256 for item in evaluations},
        "backup_manifest": _data_rel(store.config, manifest_path),
        "backup_dir": _data_rel(store.config, backup_dir),
        "combined_patch": _data_rel(store.config, combined_path),
        "patch_hashes": {
            str(entry.get("id")): entry.get("sha256") for entry in entries_all
        },
        "hash_changed_confirmed": sorted(confirm),
    }
    store.append_event(session_id, "apply", event_data)
    journal_path.unlink(missing_ok=True)
    return {
        "apply_id": apply_id,
        "patch_ids": wanted,
        "paths": [item.path for item in evaluations],
        "backup_manifest": event_data["backup_manifest"],
        "combined_patch": event_data["combined_patch"],
        "results": [item.as_dict() for item in evaluations],
    }


def rollback_manifest(config: AppConfig, manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    session_id = manifest.get("session_id") or ""
    apply_id = manifest.get("apply_id") or ""
    root = None
    # The project root is recorded in the session meta; load it without relying
    # on the session store to keep this function usable during crash recovery.
    meta_path = config.sessions_dir / session_id / "meta.json"
    if meta_path.exists():
        try:
            import json

            root = Path(json.loads(meta_path.read_text(encoding="utf-8")).get("root") or "")
        except Exception:
            root = None
    if root is None:
        return ["无法读取会话根目录"]
    backup_dir = config.backups_dir / session_id / apply_id
    for item in reversed(manifest.get("files") or []):
        try:
            target = safe_target(root, item["path"])
            if item.get("existed"):
                backup_rel = item.get("backup")
                if not backup_rel:
                    raise ValueError("missing backup path")
                source = safe_target(backup_dir, backup_rel)
                atomic_write_bytes(target, source.read_bytes(), mode=item.get("mode"))
            else:
                if target.exists():
                    target.unlink()
        except Exception as exc:
            errors.append(f"{item.get('path')}: {exc}")
    if errors:
        raise AppError(
            "rollback_failed",
            "回滚未能完整恢复所有文件，请检查备份",
            status=500,
            details={"errors": errors},
        )
    return []


def _active_apply_events(store: SessionStore, session_id: str) -> list[dict[str, Any]]:
    events = store.events(session_id)
    reverted = {
        event.get("data", {}).get("apply_id")
        for event in events
        if event.get("type") == "revert"
    }
    result = [
        event
        for event in events
        if event.get("type") == "apply"
        and event.get("data", {}).get("apply_id") not in reverted
    ]
    result.sort(key=lambda item: int(item.get("seq") or 0))
    return result


def revert_session(
    store: SessionStore,
    session_id: str,
    *,
    confirm_hash_changes: bool = False,
) -> dict[str, Any]:
    # Requirement 3.9: reverting an archived session unpackages it first.
    store.ensure_dir(session_id)
    active = _active_apply_events(store, session_id)
    if not active:
        raise AppError("nothing_to_revert", "没有可撤回的补丁应用", status=409)
    latest = active[-1]
    apply_id = latest.get("data", {}).get("apply_id")
    if not apply_id:
        raise AppError("session_corrupt", "apply 事件缺少 apply_id", status=500)
    config = store.config
    backup_rel = latest.get("data", {}).get("backup_manifest")
    if not backup_rel:
        raise AppError("backup_missing", "apply 事件缺少备份清单", status=500)
    manifest_path = _resolve_data_path(config, backup_rel)
    if not manifest_path.exists():
        raise AppError("backup_missing", "备份清单已被清理", status=409)
    import json

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    root = Path(store.meta(session_id).get("root") or "")
    changed: list[str] = []
    for item in manifest.get("files") or []:
        target = safe_target(root, item["path"])
        current = sha256_bytes(target.read_bytes()) if target.exists() else None
        if current != item.get("after_sha256"):
            changed.append(item["path"])
    if changed and not confirm_hash_changes:
        raise AppError(
            "revert_hash_changed",
            "以下文件在应用后又发生了变化，撤回会覆盖这些改动；请确认后重试",
            status=409,
            details={"paths": changed},
        )
    backup_dir = config.backups_dir / session_id / apply_id
    restored: list[str] = []
    deleted: list[str] = []
    try:
        for item in reversed(manifest.get("files") or []):
            target = safe_target(root, item["path"])
            if item.get("existed"):
                source = safe_target(backup_dir, item.get("backup") or "")
                mode = item.get("mode")
                atomic_write_bytes(target, source.read_bytes(), mode=mode)
                restored.append(item["path"])
            else:
                if target.exists():
                    target.unlink()
                deleted.append(item["path"])
    except Exception as exc:
        raise AppError(
            "revert_failed",
            f"撤回过程中发生错误，备份仍然保留：{exc}",
            status=500,
        ) from exc
    store.append_event(
        session_id,
        "revert",
        {
            "apply_id": apply_id,
            "paths": [item["path"] for item in manifest.get("files") or []],
            "restored": restored,
            "deleted": deleted,
            "confirmed_hash_changes": changed,
        },
    )
    return {
        "apply_id": apply_id,
        "paths": [item["path"] for item in manifest.get("files") or []],
        "restored": restored,
        "deleted": deleted,
        "confirmed_hash_changes": changed,
    }


def recover_incomplete(store: SessionStore) -> list[dict[str, Any]]:
    """Roll back apply transactions that were interrupted before an event."""
    recovered: list[dict[str, Any]] = []
    backups = store.config.backups_dir
    if not backups.exists():
        return recovered
    for journal in backups.glob("*/*/journal.json"):
        try:
            import json

            data = json.loads(journal.read_text(encoding="utf-8"))
            if data.get("phase") != "writing":
                journal.unlink(missing_ok=True)
                continue
            apply_id = data.get("apply_id")
            session_id = journal.parent.parent.name
            manifest_path = journal.parent / "manifest.json"
            if apply_id and manifest_path.exists():
                # If the apply event was already durable, the transaction
                # committed and only the journal cleanup was interrupted.
                committed = any(
                    event.get("type") == "apply"
                    and event.get("data", {}).get("apply_id") == apply_id
                    for event in store.events(session_id)
                )
                if committed:
                    journal.unlink(missing_ok=True)
                    continue
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                try:
                    rollback_manifest(store.config, manifest)
                except AppError:
                    continue
                recovered.append({"session_id": session_id, "apply_id": apply_id})
                try:
                    store.append_event(
                        session_id,
                        "apply_failed",
                        {"apply_id": apply_id, "recovered": True},
                    )
                except Exception:
                    pass
            journal.unlink(missing_ok=True)
        except Exception:
            continue
    return recovered
