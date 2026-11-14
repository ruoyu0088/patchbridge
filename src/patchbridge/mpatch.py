from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import AppConfig
from .i18n import get_language, tr
from .fsutil import (
    decode_text_file,
    ensure_dir,
    normalize_rel_path,
    safe_target,
    sha256_bytes,
)

# mpatch is intentionally optional.  A missing binary must never break the
# strict engine; it only means the "fuzzy repair" branch is unavailable.
KNOWN_MPATCH_PATHS = (
    r"C:\portable_apps\bin\mpatch.exe",
    "/usr/local/bin/mpatch",
    "/opt/homebrew/bin/mpatch",
)


@dataclass
class MpatchOutcome:
    status: str
    reason: str = ""
    final_patch: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)
    stdout: str = ""
    stderr: str = ""
    version: str | None = None
    dry_run_rc: int | None = None
    apply_rc: int | None = None
    elapsed_ms: int = 0
    path: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": tr(self.reason),
            "path": self.path,
            "version": self.version,
            "dry_run_rc": self.dry_run_rc,
            "apply_rc": self.apply_rc,
            "elapsed_ms": self.elapsed_ms,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "diagnostics": _localize_structure(self.diagnostics),
        }


def _localize_structure(value: Any) -> Any:
    if isinstance(value, str):
        return tr(value)
    if isinstance(value, list):
        return [_localize_structure(item) for item in value]
    if isinstance(value, tuple):
        return [_localize_structure(item) for item in value]
    if isinstance(value, dict):
        return {key: _localize_structure(item) for key, item in value.items()}
    return value


def _clip(value: str, limit: int = 20000) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "\n…（输出已截断）"


def resolve_mpatch(settings: dict[str, Any]) -> Path | None:
    """Find mpatch from settings, PATH, then a few conventional locations."""
    configured = str(settings.get("mpatch_path") or "").strip()
    candidates: list[str] = []
    if configured:
        candidates.append(os.path.expanduser(configured))
    found = shutil.which("mpatch")
    if found:
        candidates.append(found)
    if os.name == "nt":
        candidates.append(KNOWN_MPATCH_PATHS[0])
    else:
        candidates.extend(KNOWN_MPATCH_PATHS[1:])
    for candidate in candidates:
        path = Path(candidate)
        if path.is_file() and os.access(path, os.X_OK):
            return path.resolve()
    return None


def mpatch_version(path: Path, *, timeout: float = 10.0) -> str | None:
    for flag in ("--version", "-V"):
        try:
            proc = subprocess.run(
                [str(path), flag],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        text = (proc.stdout or proc.stderr or "").strip()
        if text:
            return text.splitlines()[0][:200]
    return None


def _run(
    args: list[str],
    *,
    cwd: Path,
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    # Keep temporary repositories independent from a user's global git config
    # and from locale-dependent diagnostics.
    env.setdefault("GIT_CONFIG_NOSYSTEM", "1")
    env["LC_ALL"] = "C.UTF-8"
    return subprocess.run(
        args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=env,
    )


def _git(work: Path, args: list[str], *, timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
    return _run(["git", "-C", str(work), *args], cwd=work, timeout=timeout)


def _normalize_copy_text(text: str) -> str:
    """mpatch works on plain UTF-8/LF text; the real file keeps its encoding."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _diagnostics(stderr: str, stdout: str, threshold: float) -> dict[str, Any]:
    text = "\n".join(part for part in (stderr, stdout) if part)
    result: dict[str, Any] = {
        "kind": "unknown",
        "threshold": threshold,
        "raw": _clip(text, 12000),
    }
    hunk = re.search(
        r"Hunk\s+(\d+)\s+failed.*?(?:line\s+(\d+))?.*?(?:score|similarity)\s*[:=]?\s*([0-9.]+)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if hunk:
        result.update(
            {
                "kind": "hunk_failed",
                "hunk": int(hunk.group(1)),
                "line": int(hunk.group(2)) if hunk.group(2) else None,
                "similarity": _number(hunk.group(3)),
            }
        )
    near = re.search(
        r"Near-miss candidate at line\s+(\d+)\s*\(similarity:\s*([0-9.]+)%,\s*required:\s*([0-9.]+)%\)",
        text,
        flags=re.IGNORECASE,
    )
    if near:
        if result.get("line") is None:
            result["line"] = int(near.group(1))
        if result.get("similarity") is None:
            result["similarity"] = _number(near.group(2)) / 100.0
        result["required_similarity"] = _number(near.group(3)) / 100.0
    elif result.get("similarity") is None:
        score = re.search(
            r"(?:score|similarity)\s*[:=]?\s*([0-9.]+)",
            text,
            flags=re.IGNORECASE,
        )
        if score:
            result["similarity"] = _number(score.group(1))
    if re.search(r"Context not found", text, flags=re.IGNORECASE):
        result["kind"] = "context_not_found"
        result["message"] = "补丁上下文在当前文件中找不到"
    ambiguous = re.search(
        r"Ambiguous (?:exact|fuzzy) match found at (?:lines|locations):\s*\[([^\]]*)\]",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if ambiguous:
        result["kind"] = "ambiguous"
        result["message"] = "补丁可匹配多个位置，mpatch 拒绝猜测"
        result["candidates"] = ambiguous.group(1).strip()
    if result["kind"] == "unknown" and text.strip():
        result["message"] = text.strip().splitlines()[-1][:300]
    return result


def _number(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _changed_paths(work: Path, timeout: float) -> set[str]:
    proc = _git(work, ["diff", "--cached", "--name-only", "-z"], timeout=timeout)
    if proc.returncode != 0:
        return set()
    names = [name for name in (proc.stdout or "").split("\x00") if name]
    return {name.replace("\\", "/") for name in names}


def run_mpatch_file(
    patch_text: str,
    *,
    root: Path,
    path: str,
    new_file: bool,
    config: AppConfig,
    settings: dict[str, Any],
    timeout: float | None = None,
) -> MpatchOutcome:
    """Run mpatch in a disposable copy and return a final unified diff.

    The real worktree is never passed to mpatch.  The returned patch is the
    ``git diff --cached`` product of the copy, not mpatch's stdout, so it can be
    replayed by the strict, encoding-preserving engine.
    """
    started = time.monotonic()
    exe = resolve_mpatch(settings)
    if exe is None:
        return MpatchOutcome(
            status="unavailable",
            reason="未找到 mpatch",
            path=path,
            diagnostics={"kind": "unavailable"},
        )
    try:
        path = normalize_rel_path(path)
    except Exception as exc:
        return MpatchOutcome(status="unsupported", reason=str(exc), path=path)
    threshold = float(settings.get("mpatch_fuzz_factor") or 0.7)
    timeout_seconds = float(timeout or settings.get("mpatch_timeout_seconds") or 60)
    temp = Path(tempfile.mkdtemp(prefix="mpatch-", dir=str(ensure_dir(config.tmp_dir))))
    work = temp / "work"
    patch_file = temp / "input.patch"
    try:
        ensure_dir(work)
        patch_file.write_text(patch_text, encoding="utf-8", newline="\n")
        source = safe_target(root, path)
        if new_file:
            dest = safe_target(work, path)
            ensure_dir(dest.parent)
        else:
            if not source.is_file():
                return MpatchOutcome(
                    status="failed",
                    reason=f"目标文件不存在：{path}",
                    path=path,
                    diagnostics={"kind": "missing"},
                )
            try:
                info = decode_text_file(source.read_bytes())
            except Exception as exc:
                return MpatchOutcome(
                    status="unsupported",
                    reason=f"目标文件不是受支持的文本：{exc}",
                    path=path,
                    diagnostics={"kind": "encoding"},
                )
            dest = safe_target(work, path)
            ensure_dir(dest.parent)
            dest.write_text(
                _normalize_copy_text(info.text),
                encoding="utf-8",
                newline="\n",
            )

        init = _git(work, ["init", "-q"], timeout=timeout_seconds)
        if init.returncode != 0:
            return MpatchOutcome(
                status="failed",
                reason="无法在临时副本中初始化 git",
                path=path,
                diagnostics={"kind": "git_init"},
                stderr=_clip(init.stderr or ""),
            )
        _git(work, ["config", "user.email", "patchbridge@local"])
        _git(work, ["config", "user.name", "PatchBridge"])
        if not new_file:
            add = _git(work, ["add", "-A"], timeout=timeout_seconds)
            commit = _git(
                work,
                ["commit", "-q", "--no-gpg-sign", "-m", "base"],
                timeout=timeout_seconds,
            )
            if add.returncode != 0 or commit.returncode != 0:
                return MpatchOutcome(
                    status="failed",
                    reason="无法建立临时基线",
                    path=path,
                    diagnostics={"kind": "git_baseline"},
                    stderr=_clip((add.stderr or "") + (commit.stderr or "")),
                )

        args = [
            str(exe),
            "-a",
            "-f",
            f"{threshold:.3f}",
            str(patch_file),
            str(work),
        ]
        try:
            dry = _run([str(exe), "-n", *args[1:]], cwd=work, timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            return MpatchOutcome(
                status="failed",
                reason=f"mpatch dry-run 超时（{timeout_seconds:g} 秒）",
                path=path,
                diagnostics={"kind": "timeout"},
            )
        except OSError as exc:
            return MpatchOutcome(
                status="unavailable",
                reason=f"无法启动 mpatch：{exc}",
                path=path,
                diagnostics={"kind": "unavailable"},
            )
        diag = _diagnostics(dry.stderr or "", dry.stdout or "", threshold)
        if dry.returncode != 0:
            return MpatchOutcome(
                status="failed",
                reason=_failure_reason(diag),
                path=path,
                diagnostics=diag,
                stdout=_clip(dry.stdout or ""),
                stderr=_clip(dry.stderr or ""),
                dry_run_rc=dry.returncode,
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )

        try:
            applied = _run(args, cwd=work, timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            return MpatchOutcome(
                status="failed",
                reason=f"mpatch 应用超时（{timeout_seconds:g} 秒）",
                path=path,
                diagnostics={"kind": "timeout"},
                dry_run_rc=0,
            )
        diag = _diagnostics(
            (dry.stderr or "") + "\n" + (applied.stderr or ""),
            (dry.stdout or "") + "\n" + (applied.stdout or ""),
            threshold,
        )
        if applied.returncode != 0:
            return MpatchOutcome(
                status="failed",
                reason=_failure_reason(diag),
                path=path,
                diagnostics=diag,
                stdout=_clip(applied.stdout or ""),
                stderr=_clip(applied.stderr or ""),
                dry_run_rc=0,
                apply_rc=applied.returncode,
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )

        add = _git(work, ["add", "-A"], timeout=timeout_seconds)
        if add.returncode != 0:
            return MpatchOutcome(
                status="failed",
                reason="无法收集 mpatch 结果",
                path=path,
                diagnostics={"kind": "git_add"},
                stderr=_clip(add.stderr or ""),
            )
        changed = _changed_paths(work, timeout_seconds)
        if changed != {path}:
            return MpatchOutcome(
                status="failed",
                reason=f"mpatch 修改了非预期路径：{sorted(changed) or ['（无变化）']}",
                path=path,
                diagnostics={"kind": "unexpected_paths", "paths": sorted(changed)},
                dry_run_rc=0,
                apply_rc=0,
            )
        diff = _git(
            work,
            [
                "diff",
                "--cached",
                "--no-color",
                "--no-ext-diff",
                "--src-prefix=a/",
                "--dst-prefix=b/",
            ],
            timeout=timeout_seconds,
        )
        if diff.returncode != 0 or not (diff.stdout or "").strip():
            return MpatchOutcome(
                status="failed",
                reason="mpatch 执行成功，但副本没有产生 diff",
                path=path,
                diagnostics={"kind": "empty_diff"},
                stderr=_clip(diff.stderr or ""),
                dry_run_rc=0,
                apply_rc=0,
            )
        return MpatchOutcome(
            status="ok",
            reason="mpatch 模糊应用成功，已生成待复验的最终补丁",
            final_patch=diff.stdout,
            path=path,
            diagnostics={**diag, "changed_paths": sorted(changed)},
            stdout=_clip(applied.stdout or ""),
            stderr=_clip(applied.stderr or ""),
            dry_run_rc=0,
            apply_rc=0,
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return MpatchOutcome(
            status="failed",
            reason=f"mpatch 副本流程失败：{exc}",
            path=path,
            diagnostics={"kind": "internal", "message": str(exc)},
        )
    finally:
        shutil.rmtree(temp, ignore_errors=True)


def _failure_reason(diag: dict[str, Any]) -> str:
    kind = diag.get("kind")
    if kind == "context_not_found":
        return "mpatch 找不到补丁上下文"
    if kind == "ambiguous":
        return "mpatch 找到多个可能位置，拒绝猜测"
    if kind == "hunk_failed":
        line = diag.get("line")
        similarity = diag.get("similarity")
        threshold = diag.get("threshold")
        bits = ["mpatch 未能达到相似度阈值"]
        if line:
            bits.append(f"最佳位置第 {line} 行")
        if isinstance(similarity, (int, float)):
            bits.append(f"相似度 {similarity * 100:.1f}%")
        if isinstance(threshold, (int, float)):
            bits.append(f"阈值 {threshold * 100:.0f}%")
        return "，".join(bits)
    if kind == "timeout":
        return "mpatch 超时"
    return diag.get("message") or "mpatch 未能应用补丁"


def _numbered_excerpt(text: str, line: int | None, before: int, after: int) -> str:
    lines = _normalize_copy_text(text).split("\n")
    if line is None:
        start = 1
        end = min(len(lines), before + after + 1)
    else:
        start = max(1, line - before)
        end = min(len(lines), line + after)
    rows = []
    for no in range(start, end + 1):
        rows.append(f"{no:>6} | {lines[no - 1]}")
    if start > 1:
        rows.insert(0, "…")
    if end < len(lines):
        rows.append("…")
    return "\n".join(rows)


def build_repair_request(
    *,
    meta: dict[str, Any],
    entry: dict[str, Any],
    path: str,
    current: bytes | None,
    outcome: MpatchOutcome | None,
    strict_reason: str = "",
    settings: dict[str, Any] | None = None,
) -> str:
    """Build a copy-paste request for the Web AI after both engines fail."""
    settings = settings or {}
    full_limit = int(settings.get("mpatch_repair_full_file_bytes") or 16384)
    context_lines = int(settings.get("mpatch_repair_context_lines") or 30)
    english = get_language() == "en"
    text = ""
    if current:
        try:
            text = decode_text_file(current).text
        except Exception:
            text = ""
    if text and len(current or b"") <= full_limit:
        if english:
            file_block = "Full current file (without line numbers):\n```text\n" + _normalize_copy_text(text) + "\n```"
        else:
            file_block = "下面是当前文件完整内容（不含行号）：\n```text\n" + _normalize_copy_text(text) + "\n```"
    elif text:
        line = (outcome.diagnostics or {}).get("line") if outcome else None
        if english:
            file_block = (
                f"The file is large; only about ±{context_lines} lines around the failing hunk are included "
                "(line numbers are for locating, not file content):\n"
                "```text\n"
                + _numbered_excerpt(text, line if isinstance(line, int) else None, context_lines, context_lines)
                + "\n```"
            )
        else:
            file_block = (
                f"当前文件较大，只附上失败 hunk 附近约 ±{context_lines} 行（行号仅用于定位，不属于文件内容）：\n"
                "```text\n"
                + _numbered_excerpt(text, line if isinstance(line, int) else None, context_lines, context_lines)
                + "\n```"
            )
    else:
        file_block = (
            "The current file is not decodable text; its content cannot be attached."
            if english
            else "当前文件不是可解码文本，无法附上内容。"
        )

    diag = ""
    if outcome is not None:
        diagnostic = outcome.diagnostics or {}
        bits = [tr(outcome.reason or outcome.status)]
        if english:
            if diagnostic.get("hunk"):
                bits.append(f"failed hunk: {diagnostic['hunk']}")
            if diagnostic.get("line"):
                bits.append(f"best match line: {diagnostic['line']}")
            if diagnostic.get("similarity") is not None:
                bits.append(f"similarity: {float(diagnostic['similarity']) * 100:.1f}%")
            if diagnostic.get("threshold") is not None:
                bits.append(f"threshold: {float(diagnostic['threshold']) * 100:.0f}%")
            if diagnostic.get("candidates"):
                bits.append(f"candidates: {diagnostic['candidates']}")
            diag = "; ".join(bits)
        else:
            if diagnostic.get("hunk"):
                bits.append(f"失败 hunk：{diagnostic['hunk']}")
            if diagnostic.get("line"):
                bits.append(f"最佳匹配行：{diagnostic['line']}")
            if diagnostic.get("similarity") is not None:
                bits.append(f"相似度：{float(diagnostic['similarity']) * 100:.1f}%")
            if diagnostic.get("threshold") is not None:
                bits.append(f"阈值：{float(diagnostic['threshold']) * 100:.0f}%")
            if diagnostic.get("candidates"):
                bits.append(f"候选位置：{diagnostic['candidates']}")
            diag = "；".join(bits)
    else:
        diag = strict_reason or ("Strict matching failed" if english else "严格匹配失败")
    requirement = str(meta.get("requirement") or "").strip()
    original = str(entry.get("content") or "").strip()
    if english:
        return f"""# Patch repair request

Project: {meta.get('project_name') or ''}
File: {path}
Original requirement:
{requirement or '(not recorded)'}

Strict-match failure: {strict_reason or 'Context mismatch'}
mpatch diagnostics: {diag}

{file_block}

Original patch (reference only; do not copy its incorrect context):
```diff
{original}
```

Please regenerate the unified diff for this file and satisfy:
1. Context lines must match the current file character for character, especially leading spaces and tabs.
2. Change only lines related to the requirement; do not reorder or reformat unrelated code.
3. Use a/{path} and b/{path} in the file headers.
4. Output only one diff code block; do not include explanations or other files.
"""
    return f"""# 补丁修正请求

工程：{meta.get('project_name') or ''}
文件：{path}
原始需求：
{requirement or '（未记录）'}

严格匹配失败原因：{strict_reason or '上下文不匹配'}
mpatch 诊断：{diag}

{file_block}

原始补丁（仅作参考，不要照抄错误的上下文）：
```diff
{original}
```

请重新生成这个文件的 unified diff，并满足：
1. 上下文行必须与当前文件逐字符一致，特别注意前导空格和 Tab；
2. 只修改与需求相关的行，不要重排或格式化无关代码；
3. 文件头使用 a/{path} 和 b/{path}；
4. 只输出一个 diff 代码块，不要输出解释或其他文件。
"""


def artifact_payload(
    outcome: MpatchOutcome,
    *,
    entry: dict[str, Any],
    current_sha256: str | None,
    repair: str | None,
) -> dict[str, Any]:
    final = outcome.final_patch or ""
    return {
        "version": 1,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "patch_id": entry.get("id"),
        "path": outcome.path or entry.get("path"),
        "status": outcome.status,
        "reason": outcome.reason,
        "engine": "mpatch" if outcome.status == "ok" else "none",
        "original_sha256": entry.get("sha256"),
        "current_sha256": current_sha256,
        "final_patch_sha256": sha256_bytes(final.encode("utf-8")) if final else None,
        "report": outcome.as_dict(),
        "has_repair": bool(repair),
        "repair_bytes": len(repair.encode("utf-8")) if repair else 0,
    }


def dump_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False)
