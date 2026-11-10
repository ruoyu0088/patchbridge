from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import threading
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from .archive import (
    create_zip,
    read_zip_text,
    safe_extract,
)
from .config import AppConfig
from .diff_engine import (
    FilePatch,
    apply_file_patch,
    canonical_patch,
    merge_file_patches,
    parse_unified_diff,
)
from .errors import AppError
from .fsutil import (
    atomic_write_json,
    atomic_write_text,
    ensure_dir,
    normalize_rel_path,
    read_json,
    read_text_file,
    safe_target,
    sha256_bytes,
    sha256_file,
)
from .parsing import ParseResult, ParsedPatch, parse_answer, parse_script_answer

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,100}$")
_PATCH_ID_RE = re.compile(r"^p[0-9]{4,}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def new_session_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(4)


class SessionStore:
    def __init__(self, config: AppConfig):
        self.config = config
        self.config.ensure_dirs()
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ paths
    def session_dir(self, session_id: str) -> Path:
        if not _SESSION_ID_RE.fullmatch(session_id):
            raise AppError("invalid_session_id", "会话 ID 不合法")
        return self.config.sessions_dir / session_id

    def zip_path(self, session_id: str) -> Path:
        return self.config.sessions_dir / f"{session_id}.zip"

    def is_archived(self, session_id: str) -> bool:
        return not self.session_dir(session_id).exists() and self.zip_path(session_id).exists()

    def _exists(self, session_id: str) -> bool:
        return self.session_dir(session_id).exists() or self.zip_path(session_id).exists()

    def _require(self, session_id: str) -> None:
        if not self._exists(session_id):
            raise AppError("session_not_found", f"会话不存在：{session_id}", status=404)

    def _safe_rel(self, rel: str) -> str:
        rel = normalize_rel_path(rel)
        return rel

    def read_bytes(self, session_id: str, rel: str) -> bytes:
        self._require(session_id)
        rel = self._safe_rel(rel)
        directory = self.session_dir(session_id)
        if directory.exists():
            target = safe_target(directory, rel)
            if not target.is_file():
                raise AppError("session_file_missing", f"会话文件不存在：{rel}", status=404)
            return target.read_bytes()
        from .archive import read_zip_bytes

        return read_zip_bytes(self.zip_path(session_id), rel)

    def read_text(self, session_id: str, rel: str, encoding: str = "utf-8") -> str:
        return self.read_bytes(session_id, rel).decode(encoding)

    def read_json(self, session_id: str, rel: str, default: Any = None) -> Any:
        try:
            text = self.read_text(session_id, rel)
        except AppError as exc:
            if exc.status == 404:
                return default
            raise
        try:
            return json.loads(text)
        except ValueError as exc:
            raise AppError(
                "invalid_json",
                f"会话文件不是合法 JSON：{rel}",
                details={"path": rel, "reason": str(exc)},
            ) from exc

    def write_text(self, session_id: str, rel: str, text: str) -> None:
        directory = self.ensure_dir(session_id)
        rel = self._safe_rel(rel)
        target = safe_target(directory, rel)
        atomic_write_text(target, text)

    def write_json(self, session_id: str, rel: str, data: Any) -> None:
        directory = self.ensure_dir(session_id)
        rel = self._safe_rel(rel)
        target = safe_target(directory, rel)
        atomic_write_json(target, data)

    # ---------------------------------------------------------------- metadata
    def meta(self, session_id: str) -> dict[str, Any]:
        self._require(session_id)
        data = self.read_json(session_id, "meta.json")
        if not isinstance(data, dict):
            raise AppError("session_corrupt", "会话 meta.json 损坏", status=500)
        return data

    def events(self, session_id: str) -> list[dict[str, Any]]:
        self._require(session_id)
        try:
            text = self.read_text(session_id, "events.jsonl")
        except AppError as exc:
            if exc.status == 404:
                return []
            raise
        result: list[dict[str, Any]] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                if isinstance(item, dict):
                    result.append(item)
            except ValueError:
                continue
        result.sort(key=lambda item: int(item.get("seq") or 0))
        return result

    def derived_status(self, session_id: str) -> str:
        events = self.events(session_id)
        applies = [
            event for event in events if event.get("type") == "apply"
        ]
        reverted = {
            event.get("data", {}).get("apply_id")
            for event in events
            if event.get("type") == "revert"
        }
        active = [
            event
            for event in applies
            if event.get("data", {}).get("apply_id") not in reverted
        ]
        if active:
            return "applied"
        if applies:
            return "reverted"
        if any(event.get("type") == "abandon" for event in events):
            return "abandoned"
        if self.read_json(session_id, "parsed.json") is not None:
            return "parsed"
        return "packed"

    def active_applies(self, session_id: str) -> list[dict[str, Any]]:
        events = self.events(session_id)
        reverted = {
            event.get("data", {}).get("apply_id")
            for event in events
            if event.get("type") == "revert"
        }
        return [
            event
            for event in events
            if event.get("type") == "apply"
            and event.get("data", {}).get("apply_id") not in reverted
        ]

    def has_any_apply(self, session_id: str) -> bool:
        return any(event.get("type") == "apply" for event in self.events(session_id))

    def has_unreverted_apply(self, session_id: str) -> bool:
        return bool(self.active_applies(session_id))

    def _summary(self, session_id: str) -> dict[str, Any]:
        try:
            meta = self.meta(session_id)
            events = self.events(session_id)
            parsed = self.read_json(session_id, "parsed.json") or {}
            status = self.derived_status(session_id)
            warnings = list(parsed.get("warnings") or [])
            patches = list(parsed.get("patches") or [])
            return {
                "id": session_id,
                "title": meta.get("title") or session_id,
                "project_id": meta.get("project_id") or "",
                "project_name": meta.get("project_name") or "",
                "root": meta.get("root") or "",
                "status": status,
                "archived": self.is_archived(session_id),
                "created_at": meta.get("created_at") or "",
                "updated_at": meta.get("updated_at") or "",
                "file_count": int(meta.get("file_count") or 0),
                "bundle_bytes": int(meta.get("bundle_bytes") or 0),
                "patches": len(patches),
                "warnings": len(warnings),
                "has_unreverted_apply": status == "applied",
                "event_count": len(events),
            }
        except Exception as exc:
            return {
                "id": session_id,
                "title": session_id,
                "project_id": "",
                "project_name": "",
                "root": "",
                "status": "corrupt",
                "archived": self.is_archived(session_id),
                "created_at": "",
                "updated_at": "",
                "file_count": 0,
                "bundle_bytes": 0,
                "patches": 0,
                "warnings": 0,
                "has_unreverted_apply": False,
                "event_count": 0,
                "error": str(exc),
            }

    # ------------------------------------------------------------------- index
    def _actual_ids(self) -> set[str]:
        ids: set[str] = set()
        if self.config.sessions_dir.exists():
            for child in self.config.sessions_dir.iterdir():
                if child.is_dir() and _SESSION_ID_RE.fullmatch(child.name):
                    ids.add(child.name)
                elif child.is_file() and child.suffix == ".zip":
                    sid = child.stem
                    if _SESSION_ID_RE.fullmatch(sid):
                        ids.add(sid)
        return ids

    def index_status(self) -> dict[str, Any]:
        actual = self._actual_ids()
        if not self.config.index_path.exists():
            return {
                "stale": True,
                "indexed": 0,
                "actual": len(actual),
                "missing": sorted(actual),
                "orphan": [],
                "message": "索引不存在",
            }
        try:
            index = read_json(self.config.index_path, {}) or {}
            indexed = {
                item.get("id")
                for item in index.get("sessions", [])
                if isinstance(item, dict)
            }
        except AppError:
            indexed = set()
        return {
            "stale": indexed != actual,
            "indexed": len(indexed),
            "actual": len(actual),
            "missing": sorted(actual - indexed),
            "orphan": sorted(indexed - actual),
            "message": "索引与实际会话不一致" if indexed != actual else "索引正常",
        }

    def rebuild_index(self) -> list[dict[str, Any]]:
        with self._lock:
            summaries = [self._summary(sid) for sid in sorted(self._actual_ids())]
            data = {
                "version": 1,
                "generated_at": utc_now(),
                "sessions": summaries,
            }
            atomic_write_json(self.config.index_path, data)
            return summaries

    def ensure_index(self) -> bool:
        status = self.index_status()
        if status["stale"]:
            self.rebuild_index()
            return True
        return False

    def _index_data(self) -> dict[str, Any]:
        if not self.config.index_path.exists():
            self.rebuild_index()
        try:
            data = read_json(self.config.index_path, {}) or {}
            if not isinstance(data, dict):
                raise ValueError("index is not an object")
            return data
        except (AppError, ValueError):
            self.rebuild_index()
            return read_json(self.config.index_path, {}) or {}

    def _update_index_entry(self, session_id: str) -> None:
        data = self._index_data()
        sessions = [
            item
            for item in data.get("sessions", [])
            if isinstance(item, dict) and item.get("id") != session_id
        ]
        sessions.append(self._summary(session_id))
        sessions.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        data["sessions"] = sessions
        data["generated_at"] = utc_now()
        data["version"] = 1
        atomic_write_json(self.config.index_path, data)

    # ------------------------------------------------------------------ events
    def append_event(self, session_id: str, event_type: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            self.ensure_dir(session_id)
            events = self.events(session_id)
            seq = max((int(event.get("seq") or 0) for event in events), default=0) + 1
            event = {
                "seq": seq,
                "id": "ev-" + secrets.token_hex(6),
                "type": event_type,
                "at": utc_now(),
                "data": data or {},
            }
            path = self.session_dir(session_id) / "events.jsonl"
            with open(path, "a", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps(event, ensure_ascii=False, sort_keys=False) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            meta = self.meta(session_id)
            meta["updated_at"] = event["at"]
            meta["status"] = self.derived_status(session_id)
            self.write_json(session_id, "meta.json", meta)
            self._update_index_entry(session_id)
            return event

    # --------------------------------------------------------------- lifecycle
    def create_session(
        self,
        *,
        project_id: str,
        project_name: str,
        root: str,
        profile: dict[str, Any],
        requirement: str,
        bundle_text: str,
        selection: dict[str, Any],
        mode: str = "diff",
        title: str | None = None,
        reloaded_from: str | None = None,
    ) -> str:
        with self._lock:
            session_id = new_session_id()
            if mode not in {"diff", "python"}:
                raise AppError("invalid_mode", "不支持的会话模式", details={"mode": mode})
            directory = self.ensure_dir(session_id)
            now = utc_now()
            title = (title or "").strip()
            if not title:
                first = requirement.strip().splitlines()[0] if requirement.strip() else ""
                title = (first[:80] or "未命名会话")
            meta = {
                "version": 1,
                "id": session_id,
                "project_id": project_id,
                "project_name": project_name,
                "root": root,
                "profile": profile,
                "mode": mode,
                "title": title,
                "created_at": now,
                "updated_at": now,
                "status": "packed",
                "file_count": len(selection.get("files") or []),
                "total_bytes": int(selection.get("total_bytes") or 0),
                "bundle_bytes": len(bundle_text.encode("utf-8")),
                "bundle_sha256": sha256_bytes(bundle_text.encode("utf-8")),
                "reloaded_from": reloaded_from,
            }
            atomic_write_text(directory / "requirement.md", requirement)
            atomic_write_text(directory / "bundle.txt", bundle_text)
            atomic_write_json(directory / "selection.json", selection)
            atomic_write_json(directory / "meta.json", meta)
            atomic_write_text(directory / "events.jsonl", "")
            ensure_dir(directory / "patches")
            self.append_event(
                session_id,
                "pack",
                {
                    "file_count": meta["file_count"],
                    "total_bytes": meta["total_bytes"],
                    "bundle_sha256": meta["bundle_sha256"],
                    "mode": mode,
                },
            )
            return session_id

    def ensure_dir(self, session_id: str) -> Path:
        directory = self.session_dir(session_id)
        if directory.exists():
            return directory
        if self.zip_path(session_id).exists():
            return self.unarchive(session_id)
        directory.mkdir(parents=True, exist_ok=False)
        return directory

    # --------------------------------------------------------------- answer/parse
    def save_answer(self, session_id: str, answer: str) -> dict[str, Any]:
        if self.has_any_apply(session_id):
            raise AppError("session_locked", "会话已应用补丁，不能再重新解析；请重新载入", status=409)
        if not answer or not answer.strip():
            raise AppError("answer_empty", "AI 回答为空")
        directory = self.ensure_dir(session_id)
        atomic_write_text(directory / "answer.md", answer)
        meta = self.meta(session_id)
        selection = self.read_json(session_id, "selection.json") or {}
        known = [item.get("path") for item in selection.get("files", []) if item.get("path")]
        mode = meta.get("mode") or selection.get("mode") or "diff"
        self.invalidate_script(session_id)
        if mode == "python":
            result = parse_script_answer(answer, root=Path(meta.get("root") or ""), known_paths=known)
            if not result.script:
                # A Python-mode session may still receive a legacy/plain diff
                # answer.  Fall back rather than silently discarding it.
                fallback = parse_answer(answer, root=Path(meta.get("root") or ""), known_paths=known)
                if fallback.patches:
                    fallback.warnings.append(
                        "会话为 Python 模式，但回答中没有可执行的 Python API 程序；已按 diff 格式解析"
                    )
                    result = fallback
        else:
            result = parse_answer(answer, root=Path(meta.get("root") or ""), known_paths=known)
        self.save_parsed(session_id, result)
        self.append_event(
            session_id,
            "parse",
            {
                "mode": mode,
                "patches": len(result.patches),
                "warnings": len(result.warnings),
                "answer_bytes": len(answer.encode("utf-8")),
            },
        )
        return self.get_parsed(session_id) or {}

    def save_parsed(self, session_id: str, result: ParseResult) -> None:
        directory = self.ensure_dir(session_id)
        patches_dir = ensure_dir(directory / "patches")
        manifest_entries: list[dict[str, Any]] = []
        used_files: set[str] = set()
        for patch in result.patches:
            safe_id = patch.id if _PATCH_ID_RE.fullmatch(patch.id) else "p0001"
            filename = f"{safe_id}.diff"
            used_files.add(filename)
            atomic_write_text(patches_dir / filename, patch.raw)
            manifest_entries.append(
                {
                    "id": safe_id,
                    "file": filename,
                    "path": patch.path,
                    "sha256": sha256_bytes(patch.raw.encode("utf-8")),
                    "added": patch.added,
                    "removed": patch.removed,
                    "new_file": patch.new_file,
                    "p_level": patch.p_level,
                    "warnings": list(patch.warnings),
                    "unsupported": patch.unsupported,
                }
            )
        manifest = {"version": 1, "patches": manifest_entries}
        atomic_write_json(patches_dir / "manifest.json", manifest)
        # Remove orphaned patch files only after the new manifest is durable.
        for child in patches_dir.glob("*.diff"):
            if child.name not in used_files:
                child.unlink(missing_ok=True)
        parsed = {
            "version": 1,
            "mode": result.mode or "diff",
            "parsed_at": utc_now(),
            "explanation": result.explanation,
            "commit_message": result.commit_message,
            "warnings": list(result.warnings),
            "patches": manifest_entries,
            "script": result.script,
            "script_result": result.script_result,
        }
        atomic_write_json(directory / "parsed.json", parsed)
        self.invalidate_mpatch(session_id)

    def save_script_result(
        self,
        session_id: str,
        result: ParseResult,
        report: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist a Python-mode run; patches are written by save_parsed."""
        result.mode = "python"
        result.script_result = report
        self.save_parsed(session_id, result)
        directory = ensure_dir(self.ensure_dir(session_id) / "script")
        atomic_write_text(directory / "script.py", result.script)
        atomic_write_json(directory / "report.json", report)
        self.append_event(
            session_id,
            "script_run",
            {
                "status": report.get("status"),
                "changes": len(result.patches),
                "warnings": len(result.warnings),
                "steps": len(report.get("steps") or []),
            },
        )
        return report

    def save_script_report(
        self, session_id: str, script: str, report: dict[str, Any]
    ) -> dict[str, Any]:
        """Persist a failed/timed-out run without replacing existing patches."""
        directory = ensure_dir(self.ensure_dir(session_id) / "script")
        atomic_write_text(directory / "script.py", script)
        atomic_write_json(directory / "report.json", report)
        parsed = self.get_parsed(session_id)
        if parsed is None:
            # The script API can be used with an explicit override before any
            # answer has been parsed.  Persist a minimal parsed document so the
            # script tab can still show the failure report.
            parsed = {
                "version": 1,
                "parsed_at": utc_now(),
                "explanation": "",
                "commit_message": "",
                "warnings": [],
                "patches": [],
            }
        parsed["mode"] = "python"
        parsed["script"] = script
        parsed["script_result"] = report
        self.write_json(session_id, "parsed.json", parsed)
        self.append_event(
            session_id,
            "script_run",
            {"status": report.get("status"), "patches_kept": True, "warnings": len(report.get("warnings") or [])},
        )
        return report

    def get_script(self, session_id: str) -> dict[str, Any] | None:
        parsed = self.get_parsed(session_id)
        if parsed is None:
            return None
        mode = parsed.get("mode") or self.meta(session_id).get("mode") or "diff"
        if mode != "python":
            return None
        report = self.read_json(session_id, "script/report.json")
        source = ""
        try:
            source = self.read_text(session_id, "script/script.py")
        except AppError as exc:
            if exc.status != 404:
                raise
        if not source:
            source = str(parsed.get("script") or "")
        if report is None and not source:
            return None
        return {"source": source, "report": report}

    def invalidate_script(self, session_id: str) -> None:
        directory = self.session_dir(session_id) / "script"
        if directory.is_dir():
            shutil.rmtree(directory, ignore_errors=True)

    def get_parsed(self, session_id: str) -> dict[str, Any] | None:
        data = self.read_json(session_id, "parsed.json")
        if data is None:
            return None
        if not isinstance(data, dict):
            raise AppError("session_corrupt", "parsed.json 损坏", status=500)
        return data

    def get_patches(self, session_id: str) -> list[dict[str, Any]]:
        manifest = self.read_json(session_id, "patches/manifest.json", {"patches": []})
        result: list[dict[str, Any]] = []
        for entry in manifest.get("patches", []) if isinstance(manifest, dict) else []:
            if not isinstance(entry, dict):
                continue
            filename = entry.get("file")
            if not filename:
                continue
            item = dict(entry)
            item["content"] = self.read_text(session_id, f"patches/{filename}")
            result.append(item)
        return result

    def get_patch(self, session_id: str, patch_id: str) -> dict[str, Any]:
        if not _PATCH_ID_RE.fullmatch(patch_id):
            raise AppError("invalid_patch_id", "补丁 ID 不合法")
        for patch in self.get_patches(session_id):
            if patch.get("id") == patch_id:
                return patch
        raise AppError("patch_not_found", f"补丁不存在：{patch_id}", status=404)

    # ------------------------------------------------------ mpatch artifacts
    def save_mpatch_artifact(
        self,
        session_id: str,
        patch_id: str,
        report: dict[str, Any],
        *,
        final_patch: str | None = None,
        repair: str | None = None,
    ) -> dict[str, Any]:
        """Persist a derived mpatch result without touching the original patch."""
        if not _PATCH_ID_RE.fullmatch(patch_id):
            raise AppError("invalid_patch_id", "补丁 ID 不合法")
        directory = ensure_dir(self.ensure_dir(session_id) / "mpatch")
        atomic_write_json(directory / f"{patch_id}.json", report)
        if final_patch:
            atomic_write_text(directory / f"{patch_id}.patch", final_patch)
        else:
            (directory / f"{patch_id}.patch").unlink(missing_ok=True)
        if repair:
            atomic_write_text(directory / f"{patch_id}.repair.md", repair)
        else:
            (directory / f"{patch_id}.repair.md").unlink(missing_ok=True)
        return report

    def get_mpatch_artifact(self, session_id: str, patch_id: str) -> dict[str, Any] | None:
        if not _PATCH_ID_RE.fullmatch(patch_id):
            raise AppError("invalid_patch_id", "补丁 ID 不合法")
        data = self.read_json(session_id, f"mpatch/{patch_id}.json")
        if data is None:
            return None
        if not isinstance(data, dict):
            raise AppError("session_corrupt", f"mpatch/{patch_id}.json 损坏", status=500)
        item = dict(data)

        def optional(rel: str) -> str | None:
            try:
                return self.read_text(session_id, rel)
            except AppError as exc:
                if exc.status == 404:
                    return None
                raise

        item["final_patch"] = optional(f"mpatch/{patch_id}.patch")
        item["repair"] = optional(f"mpatch/{patch_id}.repair.md")
        return item

    def mpatch_reports(self, session_id: str) -> dict[str, dict[str, Any]]:
        directory = self.session_dir(session_id) / "mpatch"
        names: list[str] = []
        if directory.is_dir():
            names = [child.name for child in directory.glob("*.json")]
        elif self.zip_path(session_id).exists():
            with zipfile.ZipFile(self.zip_path(session_id)) as archive:
                names = [
                    Path(name).name
                    for name in archive.namelist()
                    if name.startswith("mpatch/") and name.endswith(".json")
                ]
        reports: dict[str, dict[str, Any]] = {}
        for name in names:
            patch_id = Path(name).stem
            if not _PATCH_ID_RE.fullmatch(patch_id):
                continue
            data = self.read_json(session_id, f"mpatch/{patch_id}.json")
            if isinstance(data, dict):
                reports[patch_id] = data
        return reports

    def invalidate_mpatch(self, session_id: str, patch_id: str | None = None) -> None:
        """Drop derived results whenever the source patch or answer changes."""
        directory = self.session_dir(session_id) / "mpatch"
        if not directory.is_dir():
            return
        if patch_id is None:
            shutil.rmtree(directory, ignore_errors=True)
            return
        (directory / f"{patch_id}.json").unlink(missing_ok=True)
        (directory / f"{patch_id}.patch").unlink(missing_ok=True)
        (directory / f"{patch_id}.repair.md").unlink(missing_ok=True)

    def update_commit(self, session_id: str, commit_message: str) -> dict[str, Any]:
        if self.has_any_apply(session_id):
            raise AppError("session_locked", "会话已应用补丁，commit 文本已锁定；请重新载入", status=409)
        parsed = self.get_parsed(session_id)
        if parsed is None:
            raise AppError("answer_not_parsed", "还没有解析 AI 回答", status=409)
        parsed["commit_message"] = commit_message
        self.write_json(session_id, "parsed.json", parsed)
        self.append_event(session_id, "edit", {"field": "commit"})
        return parsed

    def update_patch(self, session_id: str, patch_id: str, content: str) -> dict[str, Any]:
        if self.has_any_apply(session_id):
            raise AppError("session_locked", "会话已应用补丁，补丁已锁定；请重新载入", status=409)
        entry = self.get_patch(session_id, patch_id)
        meta = self.meta(session_id)
        parsed = self.get_parsed(session_id) or {}
        selection = self.read_json(session_id, "selection.json") or {}
        known = [item.get("path") for item in selection.get("files", []) if item.get("path")]
        patches = parse_unified_diff(content, root=Path(meta.get("root") or ""), known_paths=known)
        if len(patches) != 1:
            raise AppError(
                "patch_invalid",
                "编辑后的补丁必须且只能包含一个文件",
                status=422,
                details={"found": len(patches)},
            )
        file_patch = patches[0]
        if not file_patch.path:
            file_patch.path = entry.get("path") or ""
        if not file_patch.path:
            raise AppError("patch_invalid", "编辑后的补丁缺少文件路径", status=422)
        raw = content
        try:
            raw = canonical_patch(file_patch)
        except AppError:
            raw = content
        directory = self.ensure_dir(session_id)
        manifest_path = directory / "patches" / "manifest.json"
        manifest = self.read_json(session_id, "patches/manifest.json", {"version": 1, "patches": []})
        new_entries: list[dict[str, Any]] = []
        for item in manifest.get("patches", []):
            if item.get("id") == patch_id:
                filename = item.get("file") or f"{patch_id}.diff"
                atomic_write_text(directory / "patches" / filename, raw)
                new_item = {
                    **item,
                    "path": file_patch.path,
                    "sha256": sha256_bytes(raw.encode("utf-8")),
                    "added": file_patch.added,
                    "removed": file_patch.removed,
                    "new_file": file_patch.new_file,
                    "p_level": file_patch.p_level,
                    "warnings": list(file_patch.warnings),
                    "unsupported": file_patch.unsupported,
                }
                new_entries.append(new_item)
                entry = new_item
            else:
                new_entries.append(item)
        manifest = {"version": 1, "patches": new_entries}
        atomic_write_json(manifest_path, manifest)
        parsed["patches"] = new_entries
        self.write_json(session_id, "parsed.json", parsed)
        self.invalidate_mpatch(session_id, patch_id)
        self.invalidate_script(session_id)
        self.append_event(session_id, "edit", {"field": "patch", "patch_id": patch_id})
        entry = dict(entry)
        entry["content"] = self.get_patch(session_id, patch_id)["content"]
        return entry

    def merge_patches(self, session_id: str, patch_ids: list[str]) -> dict[str, Any]:
        if self.has_any_apply(session_id):
            raise AppError("session_locked", "会话已应用补丁，不能再合并；请重新载入", status=409)
        ordered_ids = list(dict.fromkeys(patch_ids or []))
        if len(ordered_ids) < 2:
            raise AppError("merge_invalid", "至少需要两个不同的补丁才能合并", status=422)
        meta = self.meta(session_id)
        root = Path(meta.get("root") or "")
        selection = self.read_json(session_id, "selection.json") or {}
        known = [item.get("path") for item in selection.get("files", []) if item.get("path")]
        entries = self.get_patches(session_id)
        entry_map = {entry["id"]: entry for entry in entries}
        ordered: list[dict[str, Any]] = []
        for pid in ordered_ids:
            entry = entry_map.get(pid)
            if entry is None:
                raise AppError("patch_not_found", f"补丁不存在：{pid}", status=404)
            ordered.append(entry)
        file_patches: list[FilePatch] = []
        for entry in ordered:
            parsed = parse_unified_diff(
                entry.get("content") or "",
                root=root,
                known_paths=known,
            )
            if len(parsed) != 1:
                raise AppError(
                    "merge_invalid",
                    f"补丁无法解析为单文件补丁：{entry['id']}",
                    details={"patch_id": entry["id"]},
                )
            file_patches.append(parsed[0])
        paths = {fp.path for fp in file_patches if fp.path}
        if len(paths) != 1:
            raise AppError(
                "merge_path_mismatch",
                "只能合并指向同一文件的补丁",
                details={"paths": sorted(paths)},
            )
        target_path = paths.pop()
        merged, warnings = merge_file_patches(file_patches)
        merged_content = canonical_patch(merged)
        target = safe_target(root, target_path)
        if not target.exists():
            raise AppError(
                "file_missing",
                f"目标文件不存在，无法验证合并结果：{target_path}",
                status=409,
            )
        try:
            apply_file_patch(merged, target.read_bytes(), path=target_path)
        except AppError as exc:
            hint = ""
            if isinstance(exc.details, dict):
                hint = str(exc.details.get("hint") or "")
            raise AppError(
                "merge_conflict",
                f"合并后的补丁无法应用：{exc.message}",
                status=409,
                details={"path": target_path, "reason": exc.message, "hint": hint},
            ) from exc
        keeper = ordered[0]["id"]
        remove_ids = {entry["id"] for entry in ordered[1:]}
        directory = self.ensure_dir(session_id)
        manifest_path = directory / "patches" / "manifest.json"
        manifest = self.read_json(session_id, "patches/manifest.json", {"version": 1, "patches": []})
        new_entries: list[dict[str, Any]] = []
        for item in manifest.get("patches", []):
            if item.get("id") in remove_ids:
                filename = item.get("file")
                if filename:
                    (directory / "patches" / filename).unlink(missing_ok=True)
                continue
            if item.get("id") == keeper:
                filename = item.get("file") or f"{keeper}.diff"
                atomic_write_text(directory / "patches" / filename, merged_content)
                new_entries.append(
                    {
                        **item,
                        "path": target_path,
                        "sha256": sha256_bytes(merged_content.encode("utf-8")),
                        "added": merged.added,
                        "removed": merged.removed,
                        "new_file": False,
                        "p_level": merged.p_level,
                        "warnings": list(warnings),
                        "unsupported": None,
                        "merged_from": [entry["id"] for entry in ordered],
                    }
                )
            else:
                new_entries.append(item)
        manifest = {"version": 1, "patches": new_entries}
        atomic_write_json(manifest_path, manifest)
        parsed = self.get_parsed(session_id) or {}
        if "patches" in parsed:
            parsed["patches"] = new_entries
            self.write_json(session_id, "parsed.json", parsed)
        for entry in ordered:
            self.invalidate_mpatch(session_id, entry["id"])
        self.invalidate_script(session_id)
        self.append_event(
            session_id,
            "merge",
            {
                "path": target_path,
                "merged_patch_ids": [entry["id"] for entry in ordered],
                "keeper": keeper,
                "warnings": list(warnings),
            },
        )
        return {
            "path": target_path,
            "keeper": keeper,
            "merged_patch_ids": [entry["id"] for entry in ordered],
            "content": merged_content,
            "added": merged.added,
            "removed": merged.removed,
            "warnings": list(warnings),
            "applies": True,
        }

    # --------------------------------------------------------------- archive
    def archive(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            self._require(session_id)
            if self.is_archived(session_id):
                return self._summary(session_id)
            self.append_event(
                session_id,
                "archive",
                {"had_unreverted_apply": self.has_unreverted_apply(session_id)},
            )
            directory = self.session_dir(session_id)
            zip_path = self.zip_path(session_id)
            create_zip(directory, zip_path)
            shutil.rmtree(directory)
            self._update_index_entry(session_id)
            return self._summary(session_id)

    def unarchive(self, session_id: str) -> Path:
        with self._lock:
            directory = self.session_dir(session_id)
            if directory.exists():
                return directory
            zip_path = self.zip_path(session_id)
            if not zip_path.exists():
                raise AppError("session_not_found", f"会话不存在：{session_id}", status=404)
            temp = self.config.tmp_dir / f"unarchive-{session_id}-{secrets.token_hex(4)}"
            if temp.exists():
                shutil.rmtree(temp, ignore_errors=True)
            try:
                safe_extract(zip_path, temp)
                os.replace(temp, directory)
                zip_path.unlink(missing_ok=True)
            except BaseException:
                shutil.rmtree(temp, ignore_errors=True)
                raise
            self._update_index_entry(session_id)
            return directory

    def delete(self, session_id: str, *, confirm_active: bool = False) -> None:
        with self._lock:
            self._require(session_id)
            if self.has_unreverted_apply(session_id) and not confirm_active:
                raise AppError(
                    "active_apply",
                    "会话仍有未撤回的补丁应用。删除会话不会还原磁盘文件。",
                    status=409,
                    details={"has_unreverted_apply": True},
                )
            directory = self.session_dir(session_id)
            zip_path = self.zip_path(session_id)
            if directory.exists():
                shutil.rmtree(directory)
            if zip_path.exists():
                zip_path.unlink()
            self.rebuild_index()

    def reload(self, session_id: str) -> str:
        self._require(session_id)
        meta = self.meta(session_id)
        requirement = self.read_text(session_id, "requirement.md")
        selection = self.read_json(session_id, "selection.json") or {}
        bundle = self.read_text(session_id, "bundle.txt")
        answer = None
        try:
            answer = self.read_text(session_id, "answer.md")
        except AppError as exc:
            if exc.status != 404:
                raise
        parsed = self.read_json(session_id, "parsed.json")
        new_id = self.create_session(
            project_id=meta.get("project_id") or "",
            project_name=meta.get("project_name") or "",
            root=meta.get("root") or "",
            profile=meta.get("profile") or {},
            requirement=requirement,
            bundle_text=bundle,
            selection=selection,
            mode=str(meta.get("mode") or "diff"),
            title=f"重新载入 - {meta.get('title') or session_id}",
            reloaded_from=session_id,
        )
        if answer is not None:
            self.write_text(new_id, "answer.md", answer)
        if parsed is not None:
            result = ParseResult(
                explanation=parsed.get("explanation") or "",
                commit_message=parsed.get("commit_message") or "",
                warnings=list(parsed.get("warnings") or []),
                mode=parsed.get("mode") or str(meta.get("mode") or "diff"),
                script=parsed.get("script") or "",
                script_result=parsed.get("script_result"),
            )
            for entry in self.get_patches(session_id):
                result.patches.append(
                    ParsedPatch(
                        id=entry.get("id") or "p0001",
                        raw=entry.get("content") or "",
                        path=entry.get("path") or "",
                        added=int(entry.get("added") or 0),
                        removed=int(entry.get("removed") or 0),
                        new_file=bool(entry.get("new_file")),
                        p_level=int(entry.get("p_level") or 1),
                        warnings=list(entry.get("warnings") or []),
                        unsupported=entry.get("unsupported"),
                    )
                )
            self.save_parsed(new_id, result)
            self.append_event(new_id, "reload", {"source_session": session_id, "patches": len(result.patches)})
        return new_id

    def cleanup_backups(self) -> list[str]:
        """Remove expired backup sets that are not needed by an active apply."""
        settings = self.config.load_settings()
        days = int(settings.get("backup_retention_days") or 30)
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        removed: list[str] = []
        if not self.config.backups_dir.exists():
            return removed
        for session_backup in self.config.backups_dir.iterdir():
            if not session_backup.is_dir():
                continue
            session_id = session_backup.name
            if not self._exists(session_id):
                # Do not guess about a deleted session's recovery state.
                continue
            try:
                active_ids = {
                    event.get("data", {}).get("apply_id")
                    for event in self.active_applies(session_id)
                }
            except Exception:
                continue
            for apply_dir in session_backup.iterdir():
                if not apply_dir.is_dir():
                    continue
                if apply_dir.name in active_ids:
                    continue
                if (apply_dir / "journal.json").exists():
                    continue
                try:
                    stamp = datetime.fromtimestamp(apply_dir.stat().st_mtime, timezone.utc)
                except OSError:
                    continue
                if stamp > cutoff:
                    continue
                try:
                    shutil.rmtree(apply_dir)
                    removed.append(f"{session_id}/{apply_dir.name}")
                except OSError:
                    continue
        return removed

    def auto_archive(self) -> list[str]:
        settings = self.config.load_settings()
        if not settings.get("auto_archive_enabled"):
            return []
        days = int(settings.get("auto_archive_days") or 30)
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        archived: list[str] = []
        for session_id in sorted(self._actual_ids()):
            if self.is_archived(session_id):
                continue
            try:
                summary = self._summary(session_id)
                if summary.get("status") not in {"reverted", "abandoned"}:
                    continue
                if summary.get("has_unreverted_apply"):
                    continue
                updated = datetime.fromisoformat(
                    str(summary.get("updated_at") or "").replace("Z", "+00:00")
                )
                if updated >= cutoff:
                    continue
                self.archive(session_id)
                archived.append(session_id)
            except Exception:
                continue
        return archived

    # ------------------------------------------------------------------- views
    def list_sessions(
        self,
        *,
        project_id: str | None = None,
        status: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        query: str | None = None,
        archived: bool | None = None,
    ) -> dict[str, Any]:
        rebuilt = self.ensure_index()
        data = self._index_data()
        items = [
            item
            for item in data.get("sessions", [])
            if isinstance(item, dict)
        ]
        if project_id:
            items = [item for item in items if item.get("project_id") == project_id]
        if status:
            items = [item for item in items if item.get("status") == status]
        if archived is not None:
            items = [item for item in items if bool(item.get("archived")) is archived]
        if query:
            q = query.lower()
            items = [
                item
                for item in items
                if q in str(item.get("title", "")).lower()
                or q in str(item.get("project_name", "")).lower()
                or q in str(item.get("id", "")).lower()
            ]
        if date_from:
            items = [item for item in items if str(item.get("created_at", "")) >= date_from]
        if date_to:
            items = [
                item
                for item in items
                if str(item.get("created_at", ""))[: len(date_to)] <= date_to
            ]
        items.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return {
            "sessions": items,
            "index": {
                "rebuilt": rebuilt,
                "status": self.index_status(),
            },
        }

    def details(self, session_id: str) -> dict[str, Any]:
        self._require(session_id)
        meta = self.meta(session_id)
        parsed = self.get_parsed(session_id)
        patches = self.get_patches(session_id)
        events = self.events(session_id)
        selection = self.read_json(session_id, "selection.json") or {}
        archived = self.is_archived(session_id)
        directory = self.session_dir(session_id)
        bundle_path = None if archived else str(directory / "bundle.txt")
        answer = None
        try:
            answer = self.read_text(session_id, "answer.md")
        except AppError as exc:
            if exc.status != 404:
                raise
        return {
            "meta": meta,
            "status": self.derived_status(session_id),
            "archived": archived,
            "bundle_path": bundle_path,
            "archive_path": str(self.zip_path(session_id)) if archived else None,
            "bundle_size": int(meta.get("bundle_bytes") or 0),
            "requirement": self.read_text(session_id, "requirement.md"),
            "answer": answer,
            "selection": selection,
            "parsed": parsed,
            "patches": patches,
            "script": self.get_script(session_id),
            "mpatch": self.mpatch_reports(session_id),
            "events": events,
            "has_any_apply": self.has_any_apply(session_id),
            "has_unreverted_apply": self.has_unreverted_apply(session_id),
            "patch_locked": self.has_any_apply(session_id),
        }
