# PatchBridge User Guide

> English companion to `docs/USER_GUIDE.md`. The UI can switch between 中文 and English; Chinese labels are quoted in parentheses where useful.

## 1. Startup

Requires Python 3.11+ and Git. Install dependencies once:

```bat
python -m pip install -r requirements.txt
```

Then double-click `start.bat` in the project root. The browser opens:

```text
http://127.0.0.1:8765/
```

If the port is taken, the app automatically tries 8766, 8767, … and opens whichever port it actually binds.

`start.bat` does not install packages automatically. If a package is missing, `start.py` lists it, prints the install command, and waits for Enter before closing.

### Interface language

The **中文 / English** switch at the bottom of the sidebar is saved in the browser. Switching reloads the page so the UI, backend diagnostics, and generated prompts use the same language. The API also honours `Accept-Language`.

## 2. Creating a Project

Go to "Projects" → "New Project" (工程 → 新建工程) and edit the profile:

```ini
# PatchBridge profile v1
name: My Project
root: C:\Users\me\code\my-project
mode: exclude

[rules]
.git/
node_modules/
dist/
*.min.js
*.log
!dist/keep.js
```

- `root` must be an absolute path.
- `mode: exclude` means everything is included by default and matching rules remove files.
- `mode: include` means only files matched by rules are included.
- `!` re-includes a file.
- After saving, if the root directory is missing or inaccessible, the card shows a red "Unavailable" (不可用) badge and the project cannot be opened or packed.

## 3. Selecting Files and Packing

1. Open the project.
2. Search paths on the left, tick the files you want, or tick a directory to select its children recursively.
3. Below the file tree the app lists the **paths of binary files** that were excluded automatically. Clicking a path copies its absolute path, so you can confirm whether the file really is binary.
4. Under "Answer format" (回答格式) choose **Python script** (the default) or **Unified diff**. Python mode lets the AI call the built-in patch API, so it does not have to compute line numbers or copy context character by character; diff mode exists for compatibility with old sessions and external tools.
5. On the right, describe the requirement as precisely as you can: expected behaviour, edge cases, acceptance criteria.
6. Click "Generate bundle text" (生成打包文本).

The result area shows:

- file count, total size, rough token count;
- the **full path** of the bundle file;
- a **Copy full text** button;
- a **Copy file path** button;
- buttons to download the text file and preview the text.

Pick one of the two ways below:

### Way A: copy the full text

Click "Copy full text" (复制完整文本), open the Web AI chat, and paste.

### Way B: copy the file path

Click "Copy file path" (复制文件路径), open that path in Explorer, and upload `bundle.txt` to an AI that accepts files; or double-click the file and copy its contents.

The bundle contains a fixed prompt that asks the AI to answer in the following format.

Python mode:

````markdown
## 修改说明
...
## Commit 建议
...
## Python 补丁脚本
```python
replace_text("src/foo.py", "旧文本", "新文本", expected=1)
assert_count("src/foo.py", "新文本", 1)
```
````

diff mode:

````markdown
## 修改说明
...
## Commit 建议
...
## 文件补丁
### 相对路径
```diff
...
```
````

## 4. Pasting the AI Answer

Go to the session review page, paste the **entire** AI output into the "Paste the AI's full answer" (粘贴 AI 的完整回答) box, and click parse.

The app will automatically:

- find the change description and the commit suggestion;
- in Python mode, extract the code block, execute it in an **in-memory workspace**, and generate candidate patches;
- in diff mode, find the unified diff for each file;
- recognise `a/`, `b/`, absolute paths, missing language tags, missing headings, and similar variations;
- accept section headings such as "修改说明 / Commit 建议 / Python 补丁脚本" with or without `#` — a plain line works too;
- show warnings;
- normalise paths and work out the original `-pN`.

Parsed results are never applied automatically; you must review them. If a Python script fails, the real files are still untouched. Open the "Python Script" tab to inspect each step, the warnings, and stdout, then fix the script and run it again.

## 5. Reviewing Patches

Each file card shows:

- the path and the number of added/removed lines;
- `hash 一致` (hash matches) / `hash 变化` (hash changed) / `文件缺失` (file missing) / `新增文件` (new file);
- `可应用` (appliable) / `冲突` (conflict) / `不支持` (unsupported);
- `范围内` (in scope) / `工程外` (outside the project) / `被 profile 排除` (excluded by the profile);
- an expandable diff with line numbers.

You can:

- choose how many context lines the side-by-side diff shows from the "Context" (上下文) drop-down (0–50, redrawn immediately);
- click "View original patch" (查看原始补丁) to switch back to the unified diff;
- click "Dry-run this file" (单文件 dry-run) or "Dry-run all" (全部 dry-run);
- click "Edit patch" (编辑补丁), change it, and save — the tool re-parses and re-checks;
- edit the commit suggestion;
- tick only some files to apply them partially.

### Python Script page

Python sessions have an extra "Python Script" (Python 脚本) tab:

- it shows the script produced by the AI; you can edit it and click "Run script" (执行脚本); the script is also executed once automatically when the answer is pasted;
- the script editor has line numbers; execution steps and error positions show "line N" (第 N 行), and clicking one moves the cursor/selection to that line;
- the execution steps list every API call, its path, and the expected/actual match count;
- when `expected` does not match, the actual match count is applied and a warning is recorded instead of aborting the remaining steps;
- a failed assertion only records a warning and returns `False`;
- a runtime exception keeps the modifications made before it and produces a partial patch; a timeout discards the whole in-memory workspace;
- a syntax error is shown as `invalid`, produces no patch, and keeps the last successfully generated patch;
- the script may only modify the files selected for this session, or create files that are visible to the profile and do not yet exist on disk; there is no API for deleting, renaming, or overwriting a whole file;
- the script only touches memory — real files stay unchanged until the patch is applied.

### Patch conflict location and editor

When the patch context does not match the current file, the card explains why and offers "Open patch editor" (打开补丁编辑器).

The upper half of the editor is **conflict location** (冲突定位):

- on the left, the patch's context/deleted/added lines;
- on the right, the corresponding lines of the current file;
- the first mismatch is highlighted;
- if the only difference is indentation, it shows how many leading spaces the patch and the file each have;
- it shows the hunk header, the patch line numbers, and the current file line numbers.

The lower half is a patch editor with line numbers. Saving re-parses and re-runs the dry-run; Tab inserts two spaces.

If the conflict is purely an indentation difference, you can click **"Align indentation in one step"** (一键对齐缩进):

- it computes one uniform offset per hunk (for example, everything is two spaces short);
- it aligns the context/deleted lines and shifts the added lines by the same amount (the "also shift added lines" (同时平移新增行) option can be turned off);
- the result is only written into the editor if the final dry-run passes;
- it does not save automatically — after checking, you still click "Save and re-check" (保存并重新检查);
- "Undo alignment" (撤销对齐) is supported.

If different lines within the same hunk need different offsets, the content itself differs, or tabs and spaces are mixed, the tool refuses to align automatically and leaves you the manual route.

### Fuzzy apply and AI repair request

The dry-run order is automatic; there is nothing extra to tick:

1. **Strict engine**: exact context match;
2. **Automatic indentation alignment**: only handles a uniform shortfall/surplus of spaces across a whole block;
3. **mpatch fuzzy matching**: locates hunks by similarity inside a disposable copy; the real project directory is never handed to mpatch for writing.

If mpatch succeeds, the patch card shows `mpatch 模糊` (mpatch fuzzy) and displays the final patch generated by `git diff` in the copy; applying the patch still re-validates it with the strict engine. If mpatch also fails:

- the card shows `mpatch 未命中` (mpatch missed) and `待 AI 修正` (awaiting AI repair);
- expand "Repair request content" (修正请求内容) and copy it to the Web AI so it can regenerate the patch;
- for small files (≤ 16 KB by default) the complete current file is attached; for large files, ±30 lines around the failure point are attached;
- the repair request does not modify the original patch and is never applied automatically.

Manual patch editing still exists, but you normally no longer need to nudge individual spaces. When mpatch is not installed or unavailable, step 3 is skipped and you get the repair request directly.

The automatic preview shown when opening a history detail only computes status: it does not write mpatch reports and does not unpack archived sessions. Reports are only saved when you explicitly click "dry-run" or apply a patch.

### hash changes

If a file was modified externally after packing:

1. the card shows "hash 变化" (hash changed);
2. applying directly is refused;
3. clicking apply opens a confirmation dialog where you must tick each item before continuing;
4. if the patch context no longer matches, a conflict is still reported and the apply is still refused.

### Applying

Click "Apply selected patches" (应用选中补丁):

1. the backend runs the dry-run again;
2. it validates the path scope, the git repository, and the hash confirmation;
3. it merges the selected patches (files that succeeded via fuzzy matching use the mpatch result, others use the original patch), and writes the backup manifest and journal;
4. it writes transactionally; any failure rolls everything back;
5. it records an `apply` event.

After the first apply, the patches and commit text of this session are locked. Files that were not applied can still be applied later; to change a patch, use "Reload" (重新载入) to create a new session.

## 6. Revert

While there is an un-reverted apply, the review page shows "Revert the most recent apply" (撤回最近一次应用).

- Strictly LIFO: the most recent apply is reverted first;
- before reverting, the current file is compared with the "after apply" hash;
- if a file was changed externally, a confirmation is shown;
- modified files are restored from backup, and newly created files are deleted;
- reverting an archived session unpacks it first.

Revert operations are recorded in the event timeline.

## 7. Session History

"Session history" (历史会话) supports:

- filtering by project, status, and date;
- searching by title/project/ID;
- viewing the requirement, the file snapshot, the bundle, the raw answer, the parse result, the patches, and the events;
- exporting a Markdown document;
- exporting a `.patch` file (usable with `git apply` on a clean copy);
- comparing "after apply" against the current disk contents;
- reloading (creates a new session and keeps the original one);
- archiving as a zip;
- deleting (does not restore files on disk).

If you delete `data/sessions/<id>/` by hand, the index detects the inconsistency and rebuilds itself; you can also click "Rebuild" (重建).

## 8. Archiving

- Manual archive: the session directory becomes `data/sessions/<id>.zip`; it stays visible in the list and its details remain readable.
- If an apply has not been reverted, the app warns that "reverting will unpack it first".
- Automatic archiving is off by default; when enabled in Settings with a number of days, it only archives old sessions that have no un-reverted apply and whose status is `reverted` / `abandoned`.

## 9. Settings

- Large-file threshold (MB)
- Automatic archive switch / days
- Prompt template path (diff mode)
- Prompt template path for Python mode
- Python script timeout in seconds (default 20, range 1–300)
- Maximum characters of script stdout (default 20000)
- Default context lines for the side-by-side diff (default 3, range 0–50)
- mpatch executable path (leave empty to search PATH and `C:\portable_apps\bin\mpatch.exe`)
- mpatch fuzzy similarity threshold (default 0.7)
- mpatch timeout in seconds (default 60)
- AI repair request: whole-file attachment limit (default 16384 bytes), context lines around the failure point (default 30)
- Backup retention days
- Maximum number of scanned files
- Maximum size of a single bundle

Leaving a prompt template empty uses the built-in template; placeholders such as `{{PROJECT_NAME}}`, `{{FILE_COUNT}}`, `{{TOTAL_BYTES}}`, `{{MODE}}` are supported.

## 10. FAQ

**"Project root is inaccessible"** (工程根目录不可访问)

Check that the profile's `root` is an absolute path, that the directory exists, and that the current user can read it.

**No patch can be parsed**

In diff mode, confirm that the AI answer contains a unified diff (with `---`, `+++`, `@@`); in Python mode, confirm that the answer contains API calls such as `replace_text` or `insert_before`. You can edit the patch or script by hand, then run or apply it. If the answer is not in a supported format at all, the tool does not guess. If a diff is pasted into a Python session, the app warns and parses it as a diff, for compatibility with older answers.

**"Patch context does not match the current file"** (补丁上下文与当前文件不匹配)

The file changed after packing, or the line numbers/context supplied by the AI are wrong. The tool automatically tries indentation alignment and mpatch; if those still fail, copy the "AI repair request" from the card back into the Web AI to regenerate the patch, or fix it by hand in the patch editor.

**The Settings page shows "mpatch unavailable"** (mpatch 不可用)

Install mpatch 1.8+ and put the executable on PATH or at `C:\portable_apps\bin\mpatch.exe`, or enter an absolute path in Settings. Not having mpatch does not affect the strict engine, indentation alignment, applying, or reverting; it only removes one fuzzy-matching layer.

**"Not a git repository"** (不是 git 仓库)

Run this in the project root:

```bash
git init
```

**After an apply fails**

The tool rolls back from the backups. If the process is killed, the next startup automatically rolls back unfinished applies based on the journal.

**Redoing a patch that has already been applied**

Do not edit the patch directly. Click "Reload" (重新载入) to create a new session, re-validate the hash, and then proceed.
