from __future__ import annotations

import difflib
from typing import Any

from .fsutil import decode_text_file

MAX_DIFF_ROWS = 8000


def _decode(data: bytes) -> list[str]:
    if not data:
        return []
    try:
        text = decode_text_file(data).text
    except Exception:
        text = data.decode("utf-8", errors="replace")
    return text.splitlines()


def build_diff_rows(old: bytes, new: bytes) -> dict[str, Any]:
    """Return side-by-side rows; the UI groups them into hunks with its own context."""
    old_lines = _decode(old)
    new_lines = _decode(new)
    rows: list[dict[str, Any]] = []
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                rows.append(
                    {
                        "type": "equal",
                        "old_line": i1 + offset + 1,
                        "new_line": j1 + offset + 1,
                        "old_text": old_lines[i1 + offset],
                        "new_text": new_lines[j1 + offset],
                    }
                )
        elif tag == "delete":
            for offset in range(i2 - i1):
                rows.append(
                    {
                        "type": "del",
                        "old_line": i1 + offset + 1,
                        "new_line": None,
                        "old_text": old_lines[i1 + offset],
                        "new_text": "",
                    }
                )
        elif tag == "insert":
            for offset in range(j2 - j1):
                rows.append(
                    {
                        "type": "add",
                        "old_line": None,
                        "new_line": j1 + offset + 1,
                        "old_text": "",
                        "new_text": new_lines[j1 + offset],
                    }
                )
        else:
            count = max(i2 - i1, j2 - j1)
            for offset in range(count):
                old_index = i1 + offset
                new_index = j1 + offset
                old_present = old_index < i2
                new_present = new_index < j2
                rows.append(
                    {
                        "type": "change" if old_present and new_present else ("del" if old_present else "add"),
                        "old_line": old_index + 1 if old_present else None,
                        "new_line": new_index + 1 if new_present else None,
                        "old_text": old_lines[old_index] if old_present else "",
                        "new_text": new_lines[new_index] if new_present else "",
                    }
                )
        if len(rows) >= MAX_DIFF_ROWS:
            rows = rows[:MAX_DIFF_ROWS]
            return {"rows": rows, "truncated": True, "old_lines": len(old_lines), "new_lines": len(new_lines)}
    return {"rows": rows, "truncated": False, "old_lines": len(old_lines), "new_lines": len(new_lines)}
