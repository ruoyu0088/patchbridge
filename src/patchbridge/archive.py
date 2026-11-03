from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Iterable

from .errors import AppError
from .fsutil import ensure_dir, safe_zip_name, zip_entry_is_symlink

MAX_ENTRIES = 100_000
MAX_UNCOMPRESSED = 2 * 1024 * 1024 * 1024


def create_zip(source_dir: Path, zip_path: Path) -> None:
    source_dir = source_dir.resolve()
    ensure_dir(zip_path.parent)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{zip_path.name}.", suffix=".tmp", dir=zip_path.parent
    )
    os.close(fd)
    temp = Path(temp_name)
    try:
        with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(source_dir.rglob("*")):
                if not path.is_file():
                    continue
                rel = path.relative_to(source_dir).as_posix()
                safe_zip_name(rel)
                zf.write(path, rel)
        with open(temp, "rb+") as fh:
            os.fsync(fh.fileno())
        os.replace(temp, zip_path)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


def list_zip(zip_path: Path) -> list[zipfile.ZipInfo]:
    try:
        with zipfile.ZipFile(zip_path) as zf:
            return zf.infolist()
    except (OSError, zipfile.BadZipFile) as exc:
        raise AppError("archive_invalid", f"无法读取压缩包：{exc}") from exc


def read_zip_bytes(zip_path: Path, name: str) -> bytes:
    name = safe_zip_name(name)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            info = zf.getinfo(name)
            if zip_entry_is_symlink(info):
                raise AppError("unsafe_zip_entry", f"压缩包条目是符号链接：{name}")
            return zf.read(info)
    except KeyError as exc:
        raise AppError("archive_entry_missing", f"压缩包内缺少：{name}", status=404) from exc
    except (OSError, zipfile.BadZipFile) as exc:
        raise AppError("archive_invalid", f"无法读取压缩包：{exc}") from exc


def read_zip_text(zip_path: Path, name: str, encoding: str = "utf-8") -> str:
    return read_zip_bytes(zip_path, name).decode(encoding)


def safe_extract(zip_path: Path, target_dir: Path) -> None:
    target_dir = target_dir.resolve()
    ensure_dir(target_dir)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_ENTRIES:
                raise AppError("archive_too_large", "压缩包条目数量超过安全上限")
            total = 0
            names: set[str] = set()
            for info in infos:
                name = safe_zip_name(info.filename)
                if name in names:
                    raise AppError("unsafe_zip_entry", f"压缩包包含重复路径：{name}")
                names.add(name)
                if zip_entry_is_symlink(info):
                    raise AppError("unsafe_zip_entry", f"压缩包包含符号链接：{name}")
                total += max(0, int(info.file_size))
                if total > MAX_UNCOMPRESSED:
                    raise AppError("archive_too_large", "压缩包解压后体积超过安全上限")
            for info in infos:
                name = safe_zip_name(info.filename)
                destination = (target_dir / Path(*name.split("/"))).resolve()
                try:
                    destination.relative_to(target_dir)
                except ValueError as exc:
                    raise AppError(
                        "unsafe_zip_entry", f"压缩包条目越界：{name}"
                    ) from exc
                if info.is_dir():
                    ensure_dir(destination)
                    continue
                ensure_dir(destination.parent)
                with zf.open(info) as src, open(destination, "wb") as dst:
                    shutil.copyfileobj(src, dst, length=1024 * 1024)
    except AppError:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise
    except (OSError, zipfile.BadZipFile) as exc:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise AppError("archive_extract_failed", f"解压失败：{exc}") from exc


def cleanup_tmp(tmp_dir: Path) -> None:
    if not tmp_dir.exists():
        return
    for child in tmp_dir.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            try:
                child.unlink()
            except OSError:
                pass
