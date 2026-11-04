from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .fsutil import atomic_write_json, ensure_dir

DEFAULT_PORTS = (8765, 8766, 8767, 8768, 8769, 8770)

DEFAULT_SETTINGS: dict[str, Any] = {
    "large_file_bytes": 1024 * 1024,
    "auto_archive_enabled": False,
    "auto_archive_days": 30,
    "prompt_template_path": "",
    "backup_retention_days": 30,
    "max_files": 50000,
    "max_bundle_bytes": 80 * 1024 * 1024,
}


@dataclass
class AppConfig:
    data_dir: Path
    host: str = "127.0.0.1"
    port: int = 8765
    project_root: Path = field(default_factory=lambda: Path.cwd())

    @property
    def sessions_dir(self) -> Path:
        return self.data_dir / "sessions"

    @property
    def profiles_dir(self) -> Path:
        return self.data_dir / "profiles"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def selections_dir(self) -> Path:
        return self.data_dir / "selections"

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def settings_path(self) -> Path:
        return self.data_dir / "settings.json"

    @property
    def index_path(self) -> Path:
        return self.data_dir / "index.json"

    @property
    def default_prompt_path(self) -> Path:
        return Path(__file__).resolve().parent / "prompts" / "default.md"

    def ensure_dirs(self) -> None:
        for path in (
            self.data_dir,
            self.sessions_dir,
            self.profiles_dir,
            self.backups_dir,
            self.selections_dir,
            self.tmp_dir,
            self.logs_dir,
        ):
            ensure_dir(path)

    def load_settings(self) -> dict[str, Any]:
        self.ensure_dirs()
        if not self.settings_path.exists():
            atomic_write_json(self.settings_path, DEFAULT_SETTINGS)
            return dict(DEFAULT_SETTINGS)
        try:
            raw = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        settings = dict(DEFAULT_SETTINGS)
        if isinstance(raw, dict):
            for key in DEFAULT_SETTINGS:
                if key in raw:
                    settings[key] = raw[key]
        return settings

    def save_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        merged = dict(DEFAULT_SETTINGS)
        for key in DEFAULT_SETTINGS:
            if key in settings:
                merged[key] = settings[key]
        # Validate a few values so a malformed settings file cannot break scans.
        merged["large_file_bytes"] = max(1024, int(merged["large_file_bytes"]))
        merged["max_files"] = max(1, int(merged["max_files"]))
        merged["auto_archive_days"] = max(1, int(merged["auto_archive_days"]))
        merged["backup_retention_days"] = max(1, int(merged["backup_retention_days"]))
        merged["auto_archive_enabled"] = bool(merged["auto_archive_enabled"])
        atomic_write_json(self.settings_path, merged)
        return merged

    def resolve_prompt_path(self, settings: dict[str, Any] | None = None) -> Path:
        settings = settings or self.load_settings()
        configured = str(settings.get("prompt_template_path") or "").strip()
        if not configured:
            return self.default_prompt_path
        path = Path(os.path.expanduser(configured))
        if not path.is_absolute():
            path = self.project_root / path
        return path


def load_config(data_dir: str | Path | None = None) -> AppConfig:
    if data_dir is None:
        data_dir = os.environ.get("PATCHBRIDGE_DATA_DIR") or (Path.cwd() / "data")
    root = Path(data_dir).expanduser().resolve()
    config = AppConfig(data_dir=root, project_root=Path.cwd().resolve())
    config.ensure_dirs()
    config.load_settings()
    return config
