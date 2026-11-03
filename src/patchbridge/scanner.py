from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import AppError
from .fsutil import is_relative_to, looks_binary
from .profiles import Profile

_VCS_DIRS = {".git", ".hg", ".svn"}


@dataclass
class FileEntry:
    path: str
    size: int
    mtime: float


@dataclass
class ScanResult:
    files: list[FileEntry] = field(default_factory=list)
    skipped: dict[str, int] = field(default_factory=lambda: {
        "ignored": 0,
        "binary": 0,
        "large": 0,
        "symlink": 0,
        "error": 0,
    })
    errors: list[dict[str, str]] = field(default_factory=list)
    root: str = ""

    @property
    def total_bytes(self) -> int:
        return sum(file.size for file in self.files)

    def as_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "files": [
                {"path": file.path, "size": file.size} for file in self.files
            ],
            "summary": {
                "count": len(self.files),
                "bytes": self.total_bytes,
                "skipped": self.skipped,
            },
            "errors": self.errors[:50],
        }


def _is_ignored_dir(profile: Profile, rel: str) -> bool:
    if profile.mode != "exclude":
        return False
    # Keep walking when negations exist; a child may be re-included.
    if profile.has_negations():
        return False
    return not profile.is_visible(rel, is_dir=True)


def scan_project(
    profile: Profile,
    settings: dict[str, Any],
    *,
    data_dir: Path | None = None,
) -> ScanResult:
    status = profile.root_status()
    if not status.accessible:
        raise AppError(
            "project_unavailable",
            status.error or "工程根目录不可访问",
            status=409,
            details={"root": profile.root, "profile_id": profile.id},
        )
    root = profile.root_path
    large_limit = int(settings.get("large_file_bytes", 1024 * 1024))
    max_files = int(settings.get("max_files", 50000))
    result = ScanResult(root=str(root))
    data_dir_resolved = data_dir.resolve() if data_dir else None

    for current, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        rel_dir = current_path.relative_to(root).as_posix()
        if rel_dir == ".":
            rel_dir = ""

        kept_dirs: list[str] = []
        for dirname in sorted(dirnames):
            child = current_path / dirname
            child_rel = f"{rel_dir}/{dirname}".strip("/")
            if dirname.lower() in _VCS_DIRS:
                result.skipped["ignored"] += 1
                continue
            if child.is_symlink():
                result.skipped["symlink"] += 1
                continue
            if data_dir_resolved and is_relative_to(child, data_dir_resolved):
                result.skipped["ignored"] += 1
                continue
            if _is_ignored_dir(profile, child_rel):
                result.skipped["ignored"] += 1
                continue
            kept_dirs.append(dirname)
        dirnames[:] = kept_dirs

        for filename in sorted(filenames):
            path = current_path / filename
            rel = f"{rel_dir}/{filename}".strip("/")
            try:
                if path.is_symlink():
                    result.skipped["symlink"] += 1
                    continue
                if data_dir_resolved and is_relative_to(path, data_dir_resolved):
                    result.skipped["ignored"] += 1
                    continue
                if not profile.is_visible(rel):
                    result.skipped["ignored"] += 1
                    continue
                stat = path.stat()
                if stat.st_size > large_limit:
                    result.skipped["large"] += 1
                    continue
                if stat.st_size:
                    with open(path, "rb") as fh:
                        sample = fh.read(min(stat.st_size, 1024 * 1024))
                    if looks_binary(sample):
                        result.skipped["binary"] += 1
                        continue
                else:
                    sample = b""
                result.files.append(
                    FileEntry(path=rel, size=stat.st_size, mtime=stat.st_mtime)
                )
                if len(result.files) > max_files:
                    raise AppError(
                        "too_many_files",
                        f"文件数量超过上限 {max_files}，请收窄 profile 规则",
                        details={"max_files": max_files},
                    )
            except AppError:
                raise
            except OSError as exc:
                result.skipped["error"] += 1
                if len(result.errors) < 50:
                    result.errors.append({"path": rel, "error": str(exc)})

    result.files.sort(key=lambda file: file.path)
    return result
