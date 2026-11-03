from __future__ import annotations

from pathlib import Path

import pytest

from patchbridge.errors import AppError
from patchbridge.fsutil import looks_binary
from patchbridge.profiles import parse_profile_text, serialize_profile
from patchbridge.scanner import scan_project


def test_profile_comments_and_negation(tmp_path: Path):
    profile = parse_profile_text(
        """# comment
name: Example
root: C:\\work\\example
mode: exclude

[rules]
dist/
*.log
!dist/keep.log
""",
        profile_id="p1",
    )
    assert profile.name == "Example"
    assert profile.is_visible("src/a.py")
    assert not profile.is_visible("dist/a.js")
    assert profile.is_visible("dist/keep.log")


def test_include_mode_whitelist(tmp_path: Path):
    profile = parse_profile_text(
        """name: Example
root: C:\\work\\example
mode: include

[rules]
src/**
README.md
!src/generated/**
""",
        profile_id="p1",
    )
    assert profile.is_visible("src/a.py")
    assert profile.is_visible("README.md")
    assert not profile.is_visible("other.py")
    assert not profile.is_visible("src/generated/x.py")


def test_relative_root_rejected():
    with pytest.raises(AppError):
        parse_profile_text("root: relative/path\nmode: exclude\n", profile_id="x")


def test_root_status_missing(tmp_path: Path):
    profile = parse_profile_text(
        f"root: {tmp_path / 'missing'}\nmode: exclude\n", profile_id="x"
    )
    assert not profile.root_status().accessible


def test_scanner_skips_git_binary_large(tmp_path: Path):
    root = tmp_path / "p"
    (root / ".git").mkdir(parents=True)
    (root / ".git" / "config").write_text("secret")
    (root / "src").mkdir()
    (root / "src" / "a.py").write_text("print(1)\n")
    (root / "src" / "b.bin").write_bytes(b"\x00\x01\x02")
    (root / "src" / "large.py").write_text("x" * 4000)
    profile = serialize_profile(
        profile_id="p",
        name="P",
        root=str(root),
        mode="exclude",
        rules=[],
    )
    result = scan_project(profile, {"large_file_bytes": 1000, "max_files": 100})
    paths = [item.path for item in result.files]
    assert paths == ["src/a.py"]
    assert result.skipped["binary"] == 1
    assert result.skipped["large"] == 1
    assert result.skipped["ignored"] >= 1


def test_utf8_boundary_is_not_binary(tmp_path: Path):
    payload = b"a" * 8191 + "中".encode("utf-8") + b"\nconst answer = 1;\n"
    assert not looks_binary(payload)
    assert not looks_binary(payload[:8192], truncated=True)

    root = tmp_path / "p"
    (root / "src").mkdir(parents=True)
    (root / "src" / "content.js").write_bytes(payload)
    profile = serialize_profile(
        profile_id="p",
        name="P",
        root=str(root),
        mode="exclude",
        rules=[],
    )
    result = scan_project(profile, {"large_file_bytes": 1024 * 1024, "max_files": 100})
    assert [item.path for item in result.files] == ["src/content.js"]


def test_scanner_include_mode(tmp_path: Path):
    root = tmp_path / "p"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("a")
    (root / "other.py").write_text("b")
    profile = serialize_profile(
        profile_id="p",
        name="P",
        root=str(root),
        mode="include",
        rules=["src/**"],
    )
    result = scan_project(profile, {"large_file_bytes": 1000, "max_files": 100})
    assert [item.path for item in result.files] == ["src/a.py"]
