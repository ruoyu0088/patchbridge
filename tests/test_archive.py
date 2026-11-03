from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from patchbridge.archive import safe_extract
from patchbridge.errors import AppError


def _make_zip(path: Path, entries: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)


@pytest.mark.parametrize("name", ["../evil.txt", "/absolute.txt", "C:/windows.txt", "a/../../evil.txt"])
def test_safe_extract_rejects_unsafe_names(tmp_path: Path, name: str):
    archive = tmp_path / "bad.zip"
    _make_zip(archive, {name: b"bad"})
    target = tmp_path / "out"
    with pytest.raises(AppError):
        safe_extract(archive, target)
    assert not (tmp_path / "evil.txt").exists()
    assert not target.exists()


def test_safe_extract_accepts_relative_tree(tmp_path: Path):
    archive = tmp_path / "good.zip"
    _make_zip(archive, {"meta.json": b"{}", "patches/p0001.diff": b"+ x\n"})
    target = tmp_path / "out"
    safe_extract(archive, target)
    assert (target / "meta.json").read_bytes() == b"{}"
    assert (target / "patches" / "p0001.diff").read_bytes() == b"+ x\n"


def test_safe_extract_rejects_symlink_entry(tmp_path: Path):
    archive = tmp_path / "symlink.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        info = zipfile.ZipInfo("link")
        info.create_system = 3
        info.external_attr = (0xA1FF << 16)
        zf.writestr(info, "/etc/passwd")
    with pytest.raises(AppError):
        safe_extract(archive, tmp_path / "out")
