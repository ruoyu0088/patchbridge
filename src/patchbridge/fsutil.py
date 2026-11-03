from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Union

from .errors import AppError

PathLike = Union[str, os.PathLike[str]]

_BOMS: tuple[tuple[bytes, str, str], ...] = (
    (b"\xef\xbb\xbf", "utf-8", "utf-8-sig"),
    (b"\xff\xfe\x00\x00", "utf-32-le", "utf-32"),
    (b"\x00\x00\xfe\xff", "utf-32-be", "utf-32"),
    (b"\xff\xfe", "utf-16-le", "utf-16"),
    (b"\xfe\xff", "utf-16-be", "utf-16"),
)


class UnsupportedTextError(ValueError):
    pass


@dataclass
class TextFileInfo:
    text: str
    encoding: str
    bom: bytes = b""
    eol: str = "\n"
    final_newline: bool = True

    @property
    def bom_present(self) -> bool:
        return bool(self.bom)


@dataclass
class Line:
    content: str
    eol: str


def ensure_dir(path: PathLike) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: PathLike) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_write_bytes(path: PathLike, data: bytes, *, mode: int | None = None) -> None:
    p = Path(path)
    parent = p.parent
    ensure_dir(parent)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{p.name}.", suffix=".tmp", dir=parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        if mode is not None:
            try:
                os.chmod(tmp, mode)
            except OSError:
                pass
        os.replace(tmp, p)
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def atomic_write_text(path: PathLike, text: str, encoding: str = "utf-8") -> None:
    atomic_write_bytes(path, text.encode(encoding))


def atomic_write_json(path: PathLike, obj: Any) -> None:
    atomic_write_text(
        path,
        json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
    )


def read_json(path: PathLike, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AppError(
            "invalid_json",
            f"无法读取 JSON 文件：{p}",
            details={"path": str(p), "reason": str(exc)},
        ) from exc


def read_bytes(path: PathLike) -> bytes:
    try:
        return Path(path).read_bytes()
    except OSError as exc:
        raise AppError(
            "read_failed",
            f"无法读取文件：{path}",
            details={"path": str(path), "reason": str(exc)},
        ) from exc


def looks_binary(data: bytes, *, truncated: bool = False) -> bool:
    if not data:
        return False
    for bom, _, _ in _BOMS:
        if data.startswith(bom):
            return False
    if b"\x00" in data:
        return True
    # Large files are classified from a sample; a UTF-8 sample can end in the
    # middle of a multi-byte character.  Only trim for genuinely truncated
    # samples, never for a complete file with invalid trailing bytes.
    attempts = [data]
    if truncated:
        attempts.extend(data[: len(data) - trim] for trim in range(1, 4))
    for candidate in attempts:
        if not candidate:
            continue
        try:
            candidate.decode("utf-8")
            return False
        except UnicodeDecodeError:
            continue
    try:
        from charset_normalizer import from_bytes

        best = from_bytes(data[:8192]).best()
        if best is None:
            return True
        if best.encoding and best.encoding.lower().replace("_", "-") in {
            "utf-8",
            "utf-16",
            "utf-16-le",
            "utf-16-be",
            "utf-32",
            "utf-32-le",
            "utf-32-be",
        }:
            return False
        # A high-chaos guess is safer treated as binary than mangled on write.
        return float(getattr(best, "chaos", 1.0) or 1.0) > 0.35
    except Exception:
        return True


def decode_text_file(data: bytes) -> TextFileInfo:
    """Decode bytes while retaining enough metadata to write them back safely."""
    if not data:
        return TextFileInfo(text="", encoding="utf-8", bom=b"", eol="\n", final_newline=False)

    bom = b""
    encoding = ""
    for candidate, enc, _ in _BOMS:
        if data.startswith(candidate):
            bom = candidate
            encoding = enc
            break

    if encoding:
        payload = data[len(bom) :]
        try:
            text = payload.decode(encoding)
        except UnicodeDecodeError as exc:
            raise UnsupportedTextError(f"BOM 指示的编码无法解码：{encoding}") from exc
    else:
        try:
            text = data.decode("utf-8")
            encoding = "utf-8"
        except UnicodeDecodeError:
            try:
                from charset_normalizer import from_bytes

                best = from_bytes(data).best()
                if best is None or best.encoding is None:
                    raise UnsupportedTextError("无法识别文本编码")
                encoding = best.encoding
                text = str(best)
                # Only accept a guess that round-trips exactly.
                if text.encode(encoding) != data:
                    raise UnsupportedTextError(
                        f"编码猜测 {encoding} 无法无损还原，按不支持文本处理"
                    )
            except UnsupportedTextError:
                raise
            except Exception as exc:
                raise UnsupportedTextError(f"无法识别文本编码：{exc}") from exc

    eol = detect_dominant_eol(text)
    final_newline = text.endswith(("\n", "\r"))
    return TextFileInfo(
        text=text,
        encoding=encoding,
        bom=bom,
        eol=eol,
        final_newline=final_newline,
    )


def read_text_file(path: PathLike) -> TextFileInfo:
    return decode_text_file(read_bytes(path))


def encode_text_file(info: TextFileInfo, text: str | None = None) -> bytes:
    content = info.text if text is None else text
    try:
        payload = content.encode(info.encoding)
    except UnicodeEncodeError as exc:
        raise AppError(
            "encoding_error",
            "修改后的内容无法用原文件编码保存",
            details={"encoding": info.encoding, "reason": str(exc)},
        ) from exc
    return info.bom + payload


def detect_dominant_eol(text: str) -> str:
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    cr = text.count("\r") - crlf
    if crlf >= lf and crlf >= cr and crlf > 0:
        return "\r\n"
    if cr > lf and cr > 0:
        return "\r"
    return "\n"


def split_lines_keep_eol(text: str) -> list[Line]:
    lines: list[Line] = []
    pos = 0
    for match in re.finditer(r"\r\n|\n|\r", text):
        lines.append(Line(text[pos : match.start()], match.group(0)))
        pos = match.end()
    if pos < len(text):
        lines.append(Line(text[pos:], ""))
    return lines


def join_lines(lines: Iterable[Line]) -> str:
    return "".join(line.content + line.eol for line in lines)


def normalize_rel_path(value: str) -> str:
    value = value.strip().replace("\\", "/")
    if value.startswith("./"):
        value = value[2:]
    p = PurePosixPath(value)
    if not value or value in {".", "/"}:
        raise AppError("invalid_path", "补丁路径为空")
    if p.is_absolute() or re.match(r"^[A-Za-z]:", value):
        raise AppError("absolute_path", f"补丁路径不是相对路径：{value}")
    parts = [part for part in p.parts if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise AppError("path_traversal", f"补丁路径包含上级目录：{value}")
    if parts and parts[0].lower() == ".git":
        raise AppError("protected_path", f"不允许修改 .git 目录：{value}")
    return "/".join(parts)


def is_relative_to(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (OSError, ValueError):
        return False


def safe_target(root: Path, rel: str) -> Path:
    """Resolve a project-relative path, rejecting symlink/junction escapes."""
    root = root.resolve()
    rel = normalize_rel_path(rel)
    target = root / Path(*PurePosixPath(rel).parts)
    parent = target.parent
    # A non-existing parent must not escape via a symlinked ancestor.
    try:
        parent.resolve().relative_to(root)
    except (OSError, ValueError) as exc:
        raise AppError(
            "path_outside_root",
            f"目标路径不在工程根目录内：{rel}",
            details={"path": rel},
        ) from exc
    if target.exists():
        try:
            target.resolve().relative_to(root)
        except (OSError, ValueError) as exc:
            raise AppError(
                "path_outside_root",
                f"目标路径通过链接指向工程外：{rel}",
                details={"path": rel},
            ) from exc
    return target


def is_git_repo(root: Path) -> bool:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return proc.returncode == 0 and proc.stdout.strip() == "true"
    except (OSError, subprocess.SubprocessError):
        return False


def safe_zip_name(name: str) -> str:
    if not name or "\x00" in name:
        raise AppError("unsafe_zip_entry", "压缩包包含空文件名")
    if "\\" in name:
        raise AppError("unsafe_zip_entry", f"压缩包路径包含反斜杠：{name}")
    p = PurePosixPath(name)
    if p.is_absolute() or name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        raise AppError("unsafe_zip_entry", f"压缩包包含绝对路径：{name}")
    parts = [part for part in p.parts if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise AppError("unsafe_zip_entry", f"压缩包路径包含上级目录：{name}")
    return "/".join(parts)


def zip_entry_is_symlink(info: Any) -> bool:
    # Unix mode is stored in the high 16 bits; 0xA000 is a symlink.
    mode = (int(getattr(info, "external_attr", 0)) >> 16) & 0xF000
    return mode == 0xA000


def copy_file(src: Path, dst: Path) -> None:
    ensure_dir(dst.parent)
    shutil.copyfile(src, dst)


def remove_empty_parents(path: Path, stop: Path) -> None:
    current = path
    stop = stop.resolve()
    while current.exists() and current.resolve() != stop:
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def file_size(path: Path) -> int:
    return path.stat().st_size
