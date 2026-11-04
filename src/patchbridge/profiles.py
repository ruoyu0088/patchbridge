from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from pathspec import GitIgnoreSpec

from .errors import AppError
from .fsutil import (
    atomic_write_json,
    atomic_write_text,
    ensure_dir,
    normalize_rel_path,
    read_text_file,
)

_SECTION_RE = re.compile(r"^\[([A-Za-z0-9_-]+)\]\s*$")
_KEY_RE = re.compile(r"^([A-Za-z0-9_-]+)\s*[:=]\s*(.*)$")


@dataclass
class RootStatus:
    accessible: bool
    exists: bool
    is_dir: bool
    error: str | None = None


@dataclass
class Profile:
    id: str
    name: str
    root: str
    mode: str = "exclude"
    rules: list[str] = field(default_factory=list)
    path: Path | None = None
    raw: str = ""
    warnings: list[str] = field(default_factory=list)
    _matcher: GitIgnoreSpec | None = field(default=None, init=False, repr=False)

    @property
    def root_path(self) -> Path:
        return Path(self.root).expanduser()

    def matcher(self) -> GitIgnoreSpec:
        if self._matcher is None:
            self._matcher = GitIgnoreSpec.from_lines(self.rules)
        return self._matcher

    def has_negations(self) -> bool:
        return any(not pattern.include for pattern in self.matcher().patterns)

    def _pattern_matches(self, pattern: Any, rel: str) -> bool:
        candidates = [rel]
        if rel.endswith("/"):
            candidates.append(rel.rstrip("/"))
        else:
            # A rule such as ``src/`` matches the directory and its descendants.
            parts = rel.split("/")
            for i in range(1, len(parts)):
                candidates.append("/".join(parts[:i]) + "/")
                candidates.append("/".join(parts[:i]))
        for candidate in candidates:
            if pattern.match_file(candidate) is not None:
                return True
        return False

    def is_visible(self, rel: str, *, is_dir: bool = False) -> bool:
        """Evaluate gitignore rules with last-match-wins semantics.

        exclude mode: visible means not ignored.
        include mode: visible means matched by the whitelist and not negated.
        """
        rel = normalize_rel_path(rel)
        if rel.split("/", 1)[0].lower() in {".git", ".hg", ".svn"}:
            return False
        test_rel = rel + "/" if is_dir else rel
        matched = False
        for pattern in self.matcher().patterns:
            if self._pattern_matches(pattern, test_rel):
                matched = bool(pattern.include)
        return matched if self.mode == "include" else not matched

    def root_status(self) -> RootStatus:
        try:
            p = self.root_path
        except OSError as exc:
            return RootStatus(False, False, False, str(exc))
        exists = p.exists()
        is_dir = p.is_dir()
        if not exists:
            return RootStatus(False, False, False, "根目录不存在")
        if not is_dir:
            return RootStatus(False, True, False, "根路径不是目录")
        try:
            with os.scandir(p) as it:
                next(it, None)
        except OSError as exc:
            return RootStatus(False, True, True, f"根目录不可访问：{exc}")
        return RootStatus(True, True, True, None)

    def to_dict(self) -> dict[str, Any]:
        status = self.root_status()
        return {
            "id": self.id,
            "name": self.name,
            "root": self.root,
            "mode": self.mode,
            "rules": list(self.rules),
            "raw": self.raw,
            "warnings": list(self.warnings),
            "root_status": {
                "accessible": status.accessible,
                "exists": status.exists,
                "is_dir": status.is_dir,
                "error": status.error,
            },
        }

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "root": self.root,
            "mode": self.mode,
            "rules": list(self.rules),
        }


def parse_profile_text(
    text: str,
    *,
    profile_id: str = "profile",
    path: Path | None = None,
) -> Profile:
    if text.startswith("\ufeff"):
        text = text[1:]
    name = ""
    root = ""
    mode = "exclude"
    rules: list[str] = []
    warnings: list[str] = []
    section = ""
    seen_rules = False

    for line_no, raw_line in enumerate(text.splitlines(), 1):
        stripped = raw_line.strip()
        if section == "rules":
            if not stripped or stripped.startswith("#"):
                continue
            rules.append(raw_line.rstrip("\r"))
            seen_rules = True
            continue
        if not stripped or stripped.startswith("#"):
            continue
        match = _SECTION_RE.match(stripped)
        if match:
            section = match.group(1).lower()
            if section not in {"rules", "profile", "settings"}:
                warnings.append(f"第 {line_no} 行：未知小节 [{section}]，已忽略")
            continue
        match = _KEY_RE.match(stripped)
        if not match:
            warnings.append(f"第 {line_no} 行：无法识别的配置行")
            continue
        key = match.group(1).lower()
        value = match.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key == "name":
            name = value
        elif key == "root":
            root = value
        elif key == "mode":
            mode = value.lower()
        else:
            warnings.append(f"第 {line_no} 行：未知配置项 {key}")

    if not root:
        raise AppError("profile_invalid", "profile 缺少 root 配置")
    if mode not in {"exclude", "include"}:
        raise AppError("profile_invalid", "mode 只能是 exclude 或 include")
    root_path = Path(os.path.expanduser(root))
    if not root_path.is_absolute():
        raise AppError("profile_invalid", "root 必须是绝对路径")
    if not name:
        name = root_path.name or profile_id
    if not seen_rules and not rules:
        warnings.append("profile 没有规则，将按默认模式扫描全部文件")

    normalized_rules = [rule for rule in rules if rule.strip()]
    return Profile(
        id=profile_id,
        name=name,
        root=str(root_path),
        mode=mode,
        rules=normalized_rules,
        path=path,
        raw=text,
        warnings=warnings,
    )


def profile_from_dict(data: dict[str, Any], *, profile_id: str, path: Path | None = None) -> Profile:
    raw = str(data.get("raw") or "")
    if raw.strip():
        return parse_profile_text(raw, profile_id=profile_id, path=path)
    name = str(data.get("name") or "").strip()
    root = str(data.get("root") or "").strip()
    mode = str(data.get("mode") or "exclude").strip().lower()
    rules_raw = data.get("rules") or []
    if isinstance(rules_raw, str):
        rules = rules_raw.splitlines()
    elif isinstance(rules_raw, list):
        rules = [str(item) for item in rules_raw]
    else:
        rules = []
    return serialize_profile(
        profile_id=profile_id,
        name=name,
        root=root,
        mode=mode,
        rules=rules,
        path=path,
    )


def serialize_profile(
    *,
    profile_id: str,
    name: str,
    root: str,
    mode: str,
    rules: Iterable[str],
    path: Path | None = None,
) -> Profile:
    if not root:
        raise AppError("profile_invalid", "root 不能为空")
    if mode not in {"exclude", "include"}:
        raise AppError("profile_invalid", "mode 只能是 exclude 或 include")
    clean_rules = [str(rule).rstrip("\r\n") for rule in rules if str(rule).strip()]
    name = name.strip() or Path(root).name or profile_id
    lines = [
        "# PatchBridge profile v1",
        f"name: {name}",
        f"root: {root}",
        f"mode: {mode}",
        "",
        "[rules]",
        *clean_rules,
        "",
    ]
    text = "\n".join(lines)
    profile = parse_profile_text(text, profile_id=profile_id, path=path)
    profile.name = name
    return profile


def profile_file_for(profiles_dir: Path, profile_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,80}", profile_id):
        raise AppError("invalid_profile_id", "profile ID 不合法")
    return profiles_dir / f"{profile_id}.profile"


def selection_file_for(selections_dir: Path, profile_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,80}", profile_id):
        raise AppError("invalid_profile_id", "profile ID 不合法")
    return selections_dir / f"{profile_id}.json"


def load_selection(selections_dir: Path, profile_id: str) -> list[str]:
    """Return the file-tree selection that was saved for a project."""
    path = selection_file_for(selections_dir, profile_id)
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(raw, dict):
        return []
    files = raw.get("files")
    if not isinstance(files, list):
        return []
    result: list[str] = []
    for item in files:
        if not isinstance(item, str):
            continue
        try:
            result.append(normalize_rel_path(item))
        except AppError:
            continue
    return list(dict.fromkeys(result))


def save_selection(selections_dir: Path, profile_id: str, files: Iterable[str]) -> list[str]:
    """Persist the file-tree selection for a project, dropping unsafe paths."""
    path = selection_file_for(selections_dir, profile_id)
    ensure_dir(selections_dir)
    cleaned: list[str] = []
    for item in files or []:
        if not isinstance(item, str):
            continue
        try:
            cleaned.append(normalize_rel_path(item))
        except AppError:
            continue
    cleaned = list(dict.fromkeys(cleaned))
    atomic_write_json(
        path,
        {
            "version": 1,
            "project_id": profile_id,
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "files": cleaned,
        },
    )
    return cleaned


def delete_selection(selections_dir: Path, profile_id: str) -> None:
    try:
        selection_file_for(selections_dir, profile_id).unlink(missing_ok=True)
    except (AppError, OSError):
        pass


def list_profiles(profiles_dir: Path) -> list[dict[str, Any]]:
    ensure_dir(profiles_dir)
    result: list[dict[str, Any]] = []
    for path in sorted(profiles_dir.glob("*.profile")):
        try:
            info = read_text_file(path)
            profile = parse_profile_text(
                info.text,
                profile_id=path.stem,
                path=path,
            )
            result.append(profile.to_dict())
        except Exception as exc:  # a broken profile must remain visible
            result.append(
                {
                    "id": path.stem,
                    "name": path.stem,
                    "root": "",
                    "mode": "exclude",
                    "rules": [],
                    "raw": "",
                    "read_error": str(exc),
                    "warnings": [],
                    "error": str(exc),
                    "root_status": {
                        "accessible": False,
                        "exists": False,
                        "is_dir": False,
                        "error": str(exc),
                    },
                }
            )
    return result


def load_profile(profiles_dir: Path, profile_id: str) -> Profile:
    path = profile_file_for(profiles_dir, profile_id)
    if not path.exists():
        raise AppError("profile_not_found", f"工程不存在：{profile_id}", status=404)
    info = read_text_file(path)
    profile = parse_profile_text(info.text, profile_id=profile_id, path=path)
    return profile


def save_profile(profiles_dir: Path, profile: Profile) -> None:
    ensure_dir(profiles_dir)
    path = profile_file_for(profiles_dir, profile.id)
    atomic_write_text(path, profile.raw, encoding="utf-8")
    profile.path = path


def create_profile(profiles_dir: Path, data: dict[str, Any]) -> Profile:
    profile_id = str(data.get("id") or "").strip()
    if not profile_id:
        import secrets

        profile_id = "proj-" + secrets.token_hex(4)
    path = profile_file_for(profiles_dir, profile_id)
    if path.exists():
        raise AppError("profile_exists", f"工程 ID 已存在：{profile_id}", status=409)
    profile = profile_from_dict(data, profile_id=profile_id, path=path)
    save_profile(profiles_dir, profile)
    return profile


def update_profile(profiles_dir: Path, profile_id: str, data: dict[str, Any]) -> Profile:
    path = profile_file_for(profiles_dir, profile_id)
    if not path.exists():
        raise AppError("profile_not_found", f"工程不存在：{profile_id}", status=404)
    profile = profile_from_dict(data, profile_id=profile_id, path=path)
    save_profile(profiles_dir, profile)
    return profile


def delete_profile(profiles_dir: Path, profile_id: str) -> None:
    path = profile_file_for(profiles_dir, profile_id)
    if not path.exists():
        raise AppError("profile_not_found", f"工程不存在：{profile_id}", status=404)
    path.unlink()
