# PatchBridge Design Notes

> English companion to `docs/DESIGN.md`.

## 1. Goals and Boundaries

PatchBridge solves the context-transport problem of "let a Web-based AI change a few lines of code when the codebase is large":

- The tool calls no online model API.
- The tool does no browser automation.
- The user copies manually between the tool and the Web AI.
- The tool is responsible for: profile filtering, the file tree, packing, answer parsing, patch preview, dry-run, backup, apply, revert, history, and archiving.

Applying a patch requires the project to be inside a git repository; the tool checks `git rev-parse --is-inside-work-tree`. Writing to disk uses the built-in transactional line-level engine so that CRLF/BOM/encoding stay under control; an exported standard patch can still be verified and applied with `git apply`. If the strict engine fails, an external mpatch may be invoked on a disposable copy to do similarity matching, but the final write still goes through the strict engine — mpatch never touches the real project directory directly.

## 2. Technology Choices

| Layer | Choice | Notes |
|---|---|---|
| Backend | Python 3.11+, FastAPI, Uvicorn | Single-process local HTTP service |
| Frontend | Vue 3 global runtime + plain CSS | No build step, works offline |
| File matching | pathspec | gitignore semantics, supports `!` negation |
| Encoding detection | charset-normalizer | Conservative detection of non-UTF-8 text |
| Testing | pytest + FastAPI TestClient | Core logic is testable without a GUI |
| Storage | Plain text + JSON + JSONL | No database |

## 3. Runtime Shape

- Binds `127.0.0.1:8765` by default; on a port conflict it tries the following ports in order.
- Single process, single user. Operations are locked per session/filesystem.
- `start.bat` has no hardcoded interpreter path: it tries `python` on PATH (3.11+), then falls back to `py`; `start.py` only checks dependencies and prints the install command, never installing automatically.
- All filesystem writes happen in the backend; the frontend only acts through the JSON API.

## 4. Data Directory

```text
data/
  settings.json
  index.json
  profiles/<id>.profile
  sessions/<session_id>/
    meta.json
    requirement.md
    selection.json
    bundle.txt
    answer.md
    parsed.json
    patches/
      manifest.json
      p0001.diff
    script/
      script.py
      report.json
    mpatch/
      p0001.json
      p0001.patch
      p0001.repair.md
    events.jsonl
  sessions/<session_id>.zip
  backups/<session_id>/<apply_id>/
    manifest.json
    before/0000.bin
    after/0000.bin
    combined.patch
    journal.json
  tmp/
  logs/app.log
```

### 4.1 Profile

Plain text, managed by the app, with this syntax:

```ini
# PatchBridge profile v1
name: sample-project
root: C:\Users\me\project
mode: exclude

[rules]
.git/
node_modules/
*.log
!keep.log
```

- `root` must be an absolute path; `~` expansion is allowed.
- `mode`:
  - `exclude`: everything is selectable by default, matching rules exclude files, `!` includes them again.
  - `include`: only files matched by rules are selectable; `!` excludes them again.
- Rules follow gitignore semantics; the last match wins.
- `.git/`, `.hg/`, `.svn/` are always skipped; the tool's data directory is also skipped if it lives inside the project.
- If the root directory is inaccessible the project is still shown, but scanning and packing are disabled.

### 4.2 Bundle Text

Fixed delimiters, containing relative paths:

```text
# PATCHBRIDGE BUNDLE v1
MODE: python
project: ...
root: ...
generated_at: ...
files: 3
bytes: 12345

===== PATCHBRIDGE INSTRUCTIONS BEGIN =====
...
===== PATCHBRIDGE INSTRUCTIONS END =====

===== PATCHBRIDGE TREE BEGIN =====
...
===== PATCHBRIDGE TREE END =====

===== PATCHBRIDGE REQUIREMENT BEGIN =====
...
===== PATCHBRIDGE REQUIREMENT END =====

===== PATCHBRIDGE FILE BEGIN: src/app.py =====
<original content>
===== PATCHBRIDGE FILE END: src/app.py =====
```

- File contents are not escaped, re-indented, or newline-normalised.
- If a file has no trailing newline, only a single structural newline is inserted so that the end marker sits on its own line; `selection.json` records `final_newline:false`.
- Before packing, the requirement and the file contents are scanned for reserved markers; on a conflict the pack is refused and the offending files are listed.
- `selection.json` stores each file's `sha256`, encoding, BOM, EOL, and final-newline information.
- The token count is a rough hint (about 4 characters/token for ASCII, about 1 character/token for non-ASCII), not a hard limit.

**Two ways to hand it to the AI**: the UI offers both "copy full text" and "copy file path". The first is for pasting directly; the second is for opening `bundle.txt` locally or uploading it.

### 4.3 Answer Parsing

Before packing, the answer format is chosen in `MODE: python|diff` and written into both `bundle.txt` and `selection.json`; the default is Python.

The built-in Python-mode prompt asks for:

````markdown
## 修改说明
## Commit 建议
## Python 补丁脚本
```python
replace_text("src/app.py", "old", "new", expected=1)
```
````

The built-in diff-mode prompt asks for:

````markdown
## 修改说明
## Commit 建议
## 文件补丁
### src/app.py
```diff
...
```
````

The Python-mode parser extracts the first Python code block; when there is none, it falls back to parsing the answer as a diff for compatibility with older answers and emits a warning.
The diff-mode parser is tolerant:

- Chinese and English headings, keywords, and missing headings are all recognised as far as possible; headings such as `Commit 建议` or `Python 补丁脚本` do not need a Markdown `#`.
- Code blocks may have a language tag or not.
- Without code fences it scans for `diff --git` / `---` / `+++` / `@@`.
- Paths may use `a/`, `b/`, absolute paths, backslashes, or the path in the heading.
- The original `-pN` is computed automatically and normalised to `p1`.
- `..`, absolute paths escaping the root, `.git/`, duplicate paths, and delete/rename/binary patches are rejected.
- Every uncertainty becomes a warning; the parse result can be edited by hand.

### 4.4 Sessions and Events

- Session IDs are time-ordered strings and unique.
- `patches/manifest.json` explicitly records the mapping between stored file names and relative paths; deriving a path from a file name is forbidden.
- `events.jsonl` is append-only. Event types include `pack`, `parse`, `dry_run`, `apply`, `revert`, `archive`, `reload`, `edit`, `abandon`, `apply_failed`.
- The status in `meta.json` is a cache; the list status is derived from the events and whether parsed data exists.
- `index.json` is a cache, written with a temporary file + `os.replace` + fsync; it is validated at startup and when listing, and rebuilt automatically when the set of directories/archives does not match the index. It can also be rebuilt manually.

### 4.5 Backups and State Machine

Before applying, the following is saved for every affected file:

- original relative path
- backup file location
- whether it existed before applying
- sha256 before applying
- sha256 after applying
- file mode (if readable)
- content after applying (used for the "after apply vs current disk" comparison)

States:

```text
packed -> parsed -> applied -> reverted
                    |  ^
                    |  └── other unapplied files can still be applied in batches
                    └── patches/commit locked after the first apply
```

- Each apply batch is a transaction; the batch `apply_id` is recorded in the event.
- A file can be applied at most once per session.
- After a partial apply the remaining files can still be applied, but the patch content can no longer be edited.
- Revert is strictly LIFO: only the last un-reverted batch can be reverted.
- To change an already applied patch, use "Reload" to create a new session.
- If the current file content no longer matches the post-apply state, revert requires explicit confirmation; once confirmed, the file is restored from backup.

### 4.6 Patch Engine

File line model:

- Each original line keeps its EOL; new lines use the file's dominant EOL.
- UTF-8/UTF-16 BOMs are preserved; other encodings are detected conservatively via charset-normalizer, and anything that cannot round-trip losslessly is treated as unsupported text.
- Hunk context is matched exactly; when that fails, the file is searched for a unique/nearest match and an offset warning is recorded.
- New files are supported; deletion, renaming, mode changes, and binary patches are not.
- Before applying, everything is computed in memory; then backups are written, the journal is written, and files are replaced atomically one by one; any failure rolls the whole batch back from the backups.
- At startup, unfinished journals are scanned: if the `apply` event was not yet persisted the batch is rolled back; if the event was persisted only the journal is cleaned up.

### 4.7 mpatch Fuzzy Fallback

Every `evaluate_patch` tries the following in order, all automatically:

1. the strict line-level engine (the original behaviour);
2. if strict fails, `align_patch_indentation`, which accepts only a single uniform space/Tab offset per hunk;
3. if alignment still fails, or the strict retry after alignment fails, the external mpatch is invoked.

How mpatch is isolated:

- A disposable copy of each file is created under `data/tmp/`, and only the copy's path is given to mpatch; the real project directory is never mpatch's target.
- The copy is normalised to UTF-8/LF; mpatch is run with `-n -a -f <threshold>`, first as a dry-run and then applied; afterwards only the target file may have changed, and `git diff --cached` is used to produce a standard unified diff.
- That diff is re-parsed and applied once more with the strict engine against the current real file content; only if this step succeeds is the result marked appliable. CRLF/BOM and the original encoding therefore remain the responsibility of the existing encoding layer.
- The original patch text is not modified; `Evaluation.final_patch` holds the derived result, and `apply_session` prefers it when merging.
- The original patch is still locked after the first apply; changing it requires "Reload".

On failure:

- `Hunk N failed`, the best matching line/similarity, near-miss, and ambiguous information are parsed from stderr;
- `<patch_id>.repair.md` is generated: small files get the full current file, large files get context around the failing line;
- the status becomes `待 AI 修正` (awaiting AI repair); nothing is applied automatically and the original patch is untouched;
- the user can copy the repair request back into the Web AI, or keep using the manual editor.

Artifacts (`sessions/<id>/mpatch/`):

- `<patch_id>.json`: status, reason, original/current/final patch hashes, diagnostics, mpatch version and duration;
- `<patch_id>.patch`: the final patch produced by mpatch (only on success);
- `<patch_id>.repair.md`: the repair request (only on failure).

Any patch edit, merge, or re-parse invalidates that patch's mpatch artifacts, so stale results are never applied to a new patch. An archived zip keeps the same structure; viewing an archived session reads members individually instead of unpacking everything.

### 4.8 Archiving

- The entries of an archive zip are paths relative to the session directory; the structure matches the unarchived directory.
- Absolute paths, drive letters, `..`, backslashes, symlinks, duplicate entries, and unpacked sizes over the limit are rejected.
- Viewing archive details reads members individually instead of unpacking everything.
- Mutations such as revert/apply first unpack the zip safely back into the session directory.
- Reload reads members from the zip and creates a new session without modifying the original.
- Automatic archiving is off by default; it only handles sessions with no un-reverted apply, status `reverted` or `abandoned`, and older than the configured number of days. Manual archiving with an un-reverted apply requires a second confirmation.

### 4.9 Python Script Mode

The AI no longer outputs a diff; it outputs a Python program that only calls the PatchBridge patch API. The goal is to remove "compute line numbers, copy context, handle encoding/EOL" from the model's output and keep only "what to change".

**In-memory workspace**

- At the start of a run all selected files are read into a `Workspace`; each file stores `original_text` (the on-disk content when the run started), `current_text`, encoding/BOM/EOL/final_newline; the sha256 of the packed snapshot is still validated before applying.
- The API only modifies `current_text` in memory; scripts cannot read or write files directly and have no `open`/`os`/`pathlib`.
- After the run, original and current are compared file by file; changed files get a textual diff from `difflib.unified_diff`, which then goes through the existing `parse_unified_diff` → `ParsedPatch`; dry-run/apply/backup/revert are fully reused afterwards.
- New files produce a `/dev/null`-style patch; no API exists for deletion, renaming, or permission changes.

**API semantics**

- Location: `read_text`, `count`, `replace_text`, `replace_regex`, `insert_before`, `insert_after`, `replace_between`, `create_file`.
- Validation: `assert_count`, `assert_contains`, `assert_not_contains`, `assert_python_syntax`.
- Every modifying API must receive `expected` (the expected match count). When the actual count differs, the actual matches are still applied and a warning is recorded instead of being silently skipped; `limit` can cap the number of replacements in one call.
- Execution is sequential; a later step sees the `current_text` of earlier steps; `replace_between` requires the anchor pair to be unique.
- A runtime exception keeps the partial modifications made before it and produces a partial patch; a timeout discards the whole run; a syntax error produces no patch.
- Only files selected for this run, or files visible to the profile that do not exist yet, may be modified; paths must be relative and must not escape the root.

**Restricted execution**

- Uses `exec` with custom builtins, allowing `re, collections, itertools, functools, math, json, textwrap, string, difflib, typing, dataclasses`, and blocks `open/eval/exec/compile/__import__/...`.
- Runs in a daemon thread; `sys.settrace` checks the deadline. A timeout can only stop Python bytecode, not preempt C-extension calls, so a timed-out result is discarded entirely and the possibly-still-changing in-memory workspace is never read.
- Script stdout is truncated to the configured limit; steps, warnings, stdout, and exceptions are written to `script/report.json`.

**Storage and UI**

- The session's `meta.json`/`selection.json` record `mode`; `script/script.py` holds the last executed script, `script/report.json` holds the execution report; patches are still stored under `patches/`.
- The review page offers a "Python Script" tab for editing and re-running the script; pasting an answer runs it once automatically. The editor has line numbers; `ScriptStep.line`/`ScriptResult.error_line` record the AI script line of each API call and exception, and the frontend can jump to it on click.
- The diff preview is built by `diff_view.build_diff_rows` into side-by-side rows, trimmed by the context-line count; the original unified diff is kept in a collapsible area.
- An archive zip has the same structure; scripts/reports are read as members, streamed.

### 4.10 Interface Language and i18n

- The backend keeps Chinese diagnostic text as the source key. `i18n.MESSAGES_EN` plus dynamic-message regexes provide English; `tr()` translates at the API boundary, in `AppError`, session details, script reports, and mpatch reports. Unknown keys fall back to Chinese.
- FastAPI middleware reads `Accept-Language` and stores the request language in a `ContextVar`. Chinese is the default, so existing tests and sessions keep their current behaviour.
- The frontend provides `web/js/i18n.js` and `$t`. The sidebar switch writes the choice to `localStorage` and reloads the page. `api.js` sends the current language in `Accept-Language`, so backend diagnostics and prompts match the UI.
- Built-in prompts are selected by language: `prompts/default.md` and `prompts/python.md` are Chinese; `prompts/default_en.md` and `prompts/python_en.md` are English. A custom prompt path still wins.
- Sessions store the prompt and answer that were generated; switching languages does not rewrite history, only new requests and new bundles.

## 5. Security Baselines

1. All write operations happen only in the backend.
2. Before apply: dry-run again + validate hash/scope/git repository; a hash change requires explicit confirmation.
3. Back up before applying; reverting a new file deletes it.
4. Revert is LIFO + after-hash validation.
5. Encoding, BOM, and newlines are preserved.
6. mpatch runs only on disposable copies; the temporary directory is cleaned up whether it succeeds or throws; the final write is re-validated strictly.
7. Zip extraction is safe, and temporary directories are cleaned up on exceptions.
8. Events are append-only; meta/index/settings are written atomically.
9. Global exception handling returns structured JSON and never throws stack traces at the frontend.
10. Parse results may be corrected by hand.
11. Python scripts run only in the in-memory workspace and are not given filesystem objects; imports and builtins are whitelisted; a timeout discards the result and an exception keeps only the partial in-memory modifications. The final path is still "generate patch → dry-run → backup → apply".
12. Binds to the loopback address; there is no authentication design for public exposure.

## 6. Known Limitations

- v1 does not support hunk-level selection.
- Only text patches are supported; delete/rename/binary/permission patches are rejected.
- Applying requires a git repository; the internal engine does not depend on `git apply` for writing.
- Non-UTF-8 encodings rely on heuristic detection; when detection is uncertain the file is treated as binary/unsupported.
- mpatch is an optional external dependency, and its CLI reads the copy as UTF-8; PatchBridge normalises the copy to UTF-8/LF first, and the strict engine still writes back using the original encoding/BOM. Only text that cannot be identified reliably is rejected. An mpatch timeout, crash, or incompatible output is always treated as "no match" and never writes to the real project.
- After backups expire, the "after apply vs current disk" content difference is unavailable.
- Cross-session revert conflicts rely on hash validation and user confirmation; there is no global apply stack.
- A local single-user tool, not suitable for direct exposure to the public internet.
- Scanning large projects has a `max_files` cap; narrow the profile when it is exceeded.
- Python mode only supports text modifications within selected files and creating new files; it does not support deletion/renaming/whole-file overwrite. A timeout cannot preempt C extensions, so the run's in-memory workspace is discarded and the last successful patch is kept.
- Python scripts are limited by the whitelist and are not suitable for tasks needing third-party libraries or complex refactors; such tasks can still use diff mode.

## 7. Platform Dependencies

| Platform | Startup | Dependencies |
|---|---|---|
| Windows 10/11 | Double-click `start.bat` | Python 3.11+, Git, dependencies; optional mpatch 1.8+ |
| macOS / Linux | `PYTHONPATH=src python -m patchbridge --open` | Python 3.11+, Git, dependencies; optional mpatch 1.8+ |

`start.bat` uses CRLF line endings and hardcodes no interpreter path: it prefers `python` on `PATH`, validates Python 3.11+, and falls back to `py`; `start.py` reports the install command when dependencies are missing and never installs automatically.
The Vue frontend runtime is vendored, so no network access or Node build is needed.

## 8. Testing Strategy

- Unit: profile, scanning, packing, parsing, diff, encoding, zip safety.
- Integration: sessions, index, backup, partial apply, LIFO revert, archiving, reload.
- mpatch: copy isolation, fuzzy apply, failure repair request, indentation-first, BOM/CRLF preservation.
- Python mode: bundle mode header, script/answer parsing, in-memory API, `expected` mismatch, out-of-scope paths, new files, syntax errors/timeouts, BOM/CRLF preservation, side-by-side diff row structure.
- End-to-end: the FastAPI flow, and the exported patch applied with `git apply` on a clean git copy.
- Frontend: manual smoke testing; core logic does not depend on the browser.
- Row-by-row acceptance mapping: see `docs/ACCEPTANCE_MATRIX.en.md`.
