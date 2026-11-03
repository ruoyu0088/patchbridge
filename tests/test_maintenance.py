from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from patchbridge.applying import apply_session, revert_session
from patchbridge.sessions import SessionStore
from tests.conftest import make_session


ANSWER = """## 修改说明
x
## Commit 建议
fix: x
## 文件补丁
```diff
diff --git a/src/calculator.py b/src/calculator.py
--- a/src/calculator.py
+++ b/src/calculator.py
@@ -1,2 +1,2 @@
 def add(left, right):
-    return left + right
+    return left + right + 1
```
"""


def test_abandon_and_auto_archive(store: SessionStore, profile):
    session_id = make_session(store, profile)
    store.append_event(session_id, "abandon", {})
    assert store.derived_status(session_id) == "abandoned"
    meta = store.meta(session_id)
    meta["updated_at"] = (
        datetime.now(timezone.utc) - timedelta(days=90)
    ).isoformat().replace("+00:00", "Z")
    store.write_json(session_id, "meta.json", meta)
    settings = store.config.load_settings()
    settings["auto_archive_enabled"] = True
    settings["auto_archive_days"] = 1
    store.config.save_settings(settings)
    archived = store.auto_archive()
    assert session_id in archived
    assert store.is_archived(session_id)


def test_backup_cleanup_keeps_active_and_removes_old(store: SessionStore, profile):
    session_id = make_session(store, profile, answer=ANSWER)
    result = apply_session(store, session_id, ["p0001"])
    apply_id = result["apply_id"]
    backup_dir = store.config.backups_dir / session_id / apply_id
    assert backup_dir.exists()
    # Active apply must never be removed, even if old.
    old = time.time() - 90 * 86400
    os.utime(backup_dir, (old, old))
    settings = store.config.load_settings()
    settings["backup_retention_days"] = 1
    store.config.save_settings(settings)
    store.cleanup_backups()
    assert backup_dir.exists()
    revert_session(store, session_id)
    os.utime(backup_dir, (old, old))
    store.cleanup_backups()
    assert not backup_dir.exists()
